from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time

_ITERATIONS = 300_000
_FAIL_LIMIT = 5
_LOCK_SECONDS = 300.0


def _pbkdf2(pin: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)


class PinStore:
    """危险操作 PIN 的权威持有者。

    活跃 PIN = 文件哈希(若已设)> env_pin > 无。文件覆盖 env;文件损坏 fail-closed
    (configured 仍 True 但 verify 恒 False,不回退 env)。改 PIN 在线爆破靠失败节流。
    """

    def __init__(self, env_pin: str = "", path: str | None = None):
        self._env_pin = env_pin or ""
        self._path = path
        self._lock = threading.Lock()
        self._fails = 0
        self._locked_until = 0.0
        # 预读文件态:None=无文件, "corrupt"=损坏, dict=有效记录
        self._record: dict | str | None = self._load_record()

    # ---- 文件 ----
    def _load_record(self):
        if not self._path or not os.path.exists(self._path):
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                rec = json.load(f)
            if isinstance(rec, dict) and {"salt", "hash", "iterations"} <= rec.keys():
                return rec
            return "corrupt"
        except Exception:
            return "corrupt"

    def _file_set(self) -> bool:
        return self._record is not None  # 含 "corrupt"

    def has_durable_path(self) -> bool:
        return self._path is not None

    def is_configured(self) -> bool:
        return self._file_set() or bool(self._env_pin)

    def verify(self, pin: str | None) -> bool:
        if not pin:
            return False
        rec = self._record
        if rec == "corrupt":
            return False  # fail-closed:损坏文件不验、不回退 env
        if isinstance(rec, dict):
            expected = bytes.fromhex(rec["hash"])
            got = _pbkdf2(pin, bytes.fromhex(rec["salt"]), int(rec["iterations"]))
            return hmac.compare_digest(got, expected)
        if self._env_pin:
            return hmac.compare_digest(pin, self._env_pin)
        return False

    def set(self, new_pin: str) -> None:
        if not self._path:
            raise RuntimeError("PinStore 无持久路径,无法写 PIN")
        salt = os.urandom(16)
        rec = {"alg": "pbkdf2_sha256", "iterations": _ITERATIONS,
               "salt": salt.hex(), "hash": _pbkdf2(new_pin, salt, _ITERATIONS).hex()}
        with self._lock:
            self._atomic_write(rec)
            self._record = rec

    def _atomic_write(self, rec: dict) -> None:
        d = os.path.dirname(self._path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = f"{self._path}.tmp.{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f)
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

    # ---- 改 PIN 节流(在线爆破防护)----
    def change_locked(self) -> float:
        """返回剩余锁定秒数(>0=锁定中)。"""
        remaining = self._locked_until - time.time()
        return remaining if remaining > 0 else 0.0

    def verify_for_change(self, pin: str | None) -> bool:
        """校验旧 PIN(供改 PIN 端点);失败计数,达阈值锁定;成功清零。"""
        with self._lock:
            if self.verify(pin):
                self._fails = 0
                self._locked_until = 0.0
                return True
            self._fails += 1
            if self._fails >= _FAIL_LIMIT:
                self._locked_until = time.time() + _LOCK_SECONDS
            return False
