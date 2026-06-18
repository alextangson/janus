from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ScheduleEntry:
    id: str
    device_id: str
    operation: str
    params: dict
    kind: str                 # "once" | "recurring"
    at: float | None
    minute_of_day: int | None
    days: list[int] | None
    tz: str
    enabled: bool
    next_fire_at: float | None
    created_at: float
    last_attempt: float | None = None
    last_outcome: str | None = None
    last_skipped_reason: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleEntry":
        return cls(
            id=d["id"],
            device_id=d["device_id"],
            operation=d["operation"],
            params=d["params"],
            kind=d["kind"],
            at=d["at"],
            minute_of_day=d["minute_of_day"],
            days=d["days"],
            tz=d["tz"],
            enabled=d["enabled"],
            next_fire_at=d["next_fire_at"],
            created_at=d["created_at"],
            last_attempt=d.get("last_attempt"),
            last_outcome=d.get("last_outcome"),
            last_skipped_reason=d.get("last_skipped_reason"),
            last_error=d.get("last_error"),
        )


class ScheduleLimitExceeded(Exception):
    pass


class ScheduleStore:
    """定时任务的持久持有者。

    path=None → 纯内存(永不落盘)。带 path → 构造时 load JSON 数组;
    文件损坏(JSONDecodeError / 非 list / schema 不合)→ raise(fail-closed,
    镜像 PinStore 损坏即不可信的取向)。缺文件 → 空 store。
    增删改经原子临时文件 replace 落盘(与 PinStore._atomic_write 同纪律)。
    """

    def __init__(self, path: str | Path | None = None, max_schedules: int = 50) -> None:
        self._path = str(path) if path is not None else None
        self._max = max_schedules
        self._lock = threading.Lock()
        self._entries: dict[str, ScheduleEntry] = {}
        if self._path is not None:
            self._load()

    # ---- 读 ----
    def list(self) -> list[ScheduleEntry]:
        # 插入序稳定(dict 在 3.7+ 保序)
        return list(self._entries.values())

    def get(self, sid: str) -> ScheduleEntry | None:
        return self._entries.get(sid)

    # ---- 写 ----
    def add(self, entry: ScheduleEntry) -> None:
        with self._lock:
            if len(self._entries) >= self._max:
                raise ScheduleLimitExceeded(
                    f"schedule limit reached ({self._max})"
                )
            self._entries[entry.id] = entry
            self._persist()

    def update(self, entry: ScheduleEntry) -> None:
        with self._lock:
            if entry.id not in self._entries:
                raise ValueError(f"unknown schedule id: {entry.id}")
            self._entries[entry.id] = entry
            self._persist()

    def remove(self, sid: str) -> bool:
        with self._lock:
            if sid not in self._entries:
                return False
            del self._entries[sid]
            self._persist()
            return True

    # ---- 文件 ----
    def _load(self) -> None:
        if not os.path.exists(self._path):
            return  # 缺文件 → 空 store
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)  # 损坏 → JSONDecodeError 上抛(fail-closed)
        if not isinstance(raw, list):
            raise ValueError(f"schedule file must be a JSON array: {self._path}")
        entries: dict[str, ScheduleEntry] = {}
        for item in raw:
            entry = ScheduleEntry.from_dict(item)  # 缺必需键 → KeyError 上抛
            entries[entry.id] = entry
        self._entries = entries

    def _persist(self) -> None:
        if self._path is None:
            return  # 纯内存,永不落盘
        self._atomic_write([e.to_dict() for e in self._entries.values()])

    def _atomic_write(self, data: list[dict]) -> None:
        d = os.path.dirname(self._path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = f"{self._path}.tmp.{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
            dirfd = os.open(d, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
