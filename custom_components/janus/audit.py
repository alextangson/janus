"""HA 层审计 sink:在线有界 deque + 脱敏 _LOGGER + Store 去抖持久化。
record() 即注入给 Repl 的 sink(跑在 executor 线程);save 在 loop 线程。
本文件含 homeassistant 导入,只能被 __init__.py 函数内导入(红线)。
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import asdict

from homeassistant.util import dt as dt_util

from .gatekeeper.audit import summary

_LOGGER = logging.getLogger(__name__)
_MAX = 200


class DecisionAudit:
    def __init__(self, hass, store):
        self._hass = hass
        self._store = store
        self._log: deque = deque(maxlen=_MAX)
        self._lock = threading.Lock()

    def record(self, rec) -> None:
        """注入给 Repl 的 sink;审计失败绝不冒泡进控制流。"""
        try:
            row = {**asdict(rec), "ts": dt_util.utcnow().isoformat()}
            with self._lock:
                self._log.append(row)
            _LOGGER.info("%s", summary(rec))
            _LOGGER.debug("janus decision: %s", row)
        except Exception:  # noqa: BLE001 — 审计绝不影响执行
            _LOGGER.exception("janus audit record failed")

    def snapshot(self) -> list:
        with self._lock:
            return list(self._log)

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001 — 畸形/缺失 → 空起步
            _LOGGER.exception("janus audit load failed")
            data = None
        if data:
            with self._lock:
                self._log.extend(data[-_MAX:])

    def schedule_save(self) -> None:
        """loop 线程调用:去抖落盘,避免每轮写。"""
        self._store.async_delay_save(self.snapshot, 10)

    async def async_flush(self) -> None:
        """卸载/重载前立即落盘:async_save 即时写并清掉待触发的去抖句柄,
        既防 10s 窗口内重载丢记录,也防旧定时器晚触发覆盖重载后的新快照。"""
        await self._store.async_save(self.snapshot())
