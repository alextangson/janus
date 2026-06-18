from __future__ import annotations

import asyncio
import fcntl
import os
import time
from pathlib import Path
from uuid import uuid4

from .schedule_time import compute_next_fire


class Scheduler:
    """定时任务执行器:每 tick 把到期任务经 Janus 闸放行执行。

    安全是要点:每次触发用一个全新的无状态 Controller(经注入的 controller_factory),
    走 control() → decide_resolved 复审;只有 verdict=="allow"(outcome.executed)才执行。
    绝不调 confirm(),绝不复用用户会话。executed/skipped/failed 都推进窗口,同一窗口不重试。
    """

    def __init__(
        self,
        store,
        controller_factory,
        *,
        tz_name: str,
        audit=None,
        caller: str = "scheduler",
        tick_seconds: float = 30.0,
        max_due_per_tick: int = 20,
        lock_path: str | Path | None = None,
    ) -> None:
        self._store = store
        self._controller_factory = controller_factory
        self._tz_name = tz_name
        self._audit = audit
        self._caller = caller
        self.tick_seconds = tick_seconds
        self._max_due_per_tick = max_due_per_tick
        self._lock_path = str(lock_path) if lock_path is not None else None
        self._lock_fd: int | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    # ---- owner lock ----

    def acquire_owner_lock(self) -> bool:
        """无 lock_path → 直接 True(测试/单进程开发)。
        否则 flock LOCK_EX|LOCK_NB:成功留住 fd 返 True;被占 → 返 False。"""
        if self._lock_path is None:
            return True
        # 全新部署时 data/ 可能尚不存在:O_CREAT 只建文件不建父目录,
        # 先建父目录(与 ScheduleStore._atomic_write 同纪律),否则 os.open 抛 FileNotFoundError。
        parent = os.path.dirname(self._lock_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # 仅锁竞争(另一 worker 持锁)才返 False;其它 OSError(权限等)向上抛,
            # 让真实配置错误在启动时炸出来,而非伪装成"锁被占"被静默吞掉。
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    # ---- core ----

    def tick(self, now: float) -> None:
        """同步、确定、可单测。挑出到期任务,逐个经闸触发并推进窗口。"""
        due = [
            e
            for e in self._store.list()
            if e.enabled and e.next_fire_at is not None and e.next_fire_at <= now
        ]
        due.sort(key=lambda e: e.next_fire_at)
        due = due[: self._max_due_per_tick]

        for e in due:
            self._fire(e, now)

    def _fire(self, e, now: float) -> None:
        e.last_attempt = now
        try:
            ctrl = self._controller_factory()  # 每次触发拿全新无状态控制器
            outcome = ctrl.control(e.device_id, e.operation, e.params)
            if outcome.executed:
                e.last_outcome = "executed"
                e.last_skipped_reason = None
                e.last_error = None
                self._audit_event("schedule_fired", e)
            else:
                # 变危险→confirm 或 不可行→reject:跳过,绝不强推
                e.last_outcome = "skipped"
                e.last_skipped_reason = getattr(outcome.decision, "reason", None)
                self._audit_event("schedule_skipped", e)
        except Exception as exc:  # 逐条隔离:一个失败不拖垮整 tick
            e.last_outcome = "failed"
            e.last_error = str(exc)
            self._audit_event("schedule_failed", e)

        # 无论 executed/skipped/failed 都推进:一次尝试一个窗口,不重试同窗口
        if e.kind == "recurring":
            nf = compute_next_fire(
                kind="recurring",
                at=None,
                minute_of_day=e.minute_of_day,
                days=e.days,
                tz_name=e.tz,  # 用条目自身的 tz(创建时锁定),非 self._tz_name —— 防跨时区漂移
                after=now,
            )
            e.next_fire_at = nf
            if nf is None:
                e.enabled = False
                self._audit_event("schedule_disabled", e)
        else:  # once
            e.enabled = False
            e.next_fire_at = None
            self._audit_event("schedule_disabled", e)

        self._store.update(e)

    def _audit_event(self, event: str, e) -> None:
        if self._audit is None:
            return
        self._audit.record_lifecycle(
            event=event,
            request_id=uuid4().hex,
            conversation_id=f"schedule:{e.id}",
            caller=self._caller,
            device_id=e.device_id,
            operation=e.operation,
        )

    # ---- run loop ----

    async def run(self) -> None:
        while not self._stopped:
            self.tick(time.time())
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> bool:
        """拿到 owner 锁才起循环;非 owner 直接返 False(单写者)。"""
        if not self.acquire_owner_lock():
            return False
        self._stopped = False
        self._task = asyncio.ensure_future(self.run())
        return True

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._release_lock()
