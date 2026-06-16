"""习惯观察者:监听 light/cover/lock 状态跳变 → 有界 ObservationLog(deque + Store)。
含 homeassistant 导入,只能被 __init__.py 函数内导入(红线)。回调在 loop 线程,非阻塞。
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .gatekeeper.observations import build_observation, classify_source

_LOGGER = logging.getLogger(__name__)
_OBSERVED_DOMAINS = {"light", "cover", "lock"}
_MAX = 10000


class ObservationLog:
    """有界事件日志:deque + Store 去抖持久化。record() 在 loop 线程,不用锁。"""

    def __init__(self, hass, store):
        self._hass = hass
        self._store = store
        self._log: deque = deque(maxlen=_MAX)

    def record(self, obs) -> None:
        try:
            self._log.append({**asdict(obs), "ts": dt_util.now().isoformat()})
            self._store.async_delay_save(self.snapshot, 30)
        except Exception:  # noqa: BLE001 — 采集失败绝不连累 HA
            _LOGGER.exception("janus observation record failed")

    def snapshot(self) -> list:
        return list(self._log)

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("janus observation load failed")
            data = None
        if data:
            self._log.extend(data[-_MAX:])

    async def async_flush(self) -> None:
        await self._store.async_save(self.snapshot())


@callback
def _on_state_change(log, event):
    if event.data.get("entity_id", "").split(".")[0] not in _OBSERVED_DOMAINS:
        return  # 只关心 light/cover/lock,其余一次域判断即早退
    new = event.data.get("new_state")
    old = event.data.get("old_state")
    if new is None or new.state in ("unavailable", "unknown"):
        return
    if old is not None and old.state == new.state:
        return  # 纯属性变化,非真跳变
    ctx = event.context
    source = classify_source(getattr(ctx, "user_id", None), getattr(ctx, "parent_id", None))
    log.record(build_observation(event.data["entity_id"], new.state, source))


def start_observer(hass, log):
    """监听全量 state_changed 总线(回调按域早退)→ race-free,运行时新设备立即纳入。
    返回 unsub,交给 entry.async_on_unload。"""
    return hass.bus.async_listen(EVENT_STATE_CHANGED, lambda e: _on_state_change(log, e))
