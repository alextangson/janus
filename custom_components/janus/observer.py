"""习惯观察者:监听 动作(light/cover/lock/climate)+ 触发(person/device_tracker 在/离家)
状态跳变 → 有界 ObservationLog(deque + Store)。含 homeassistant 导入,只能被 __init__.py
函数内导入(红线)。回调在 loop 线程,非阻塞。域过滤/来源判定全在纯层 observations.py,可测。
"""
from __future__ import annotations

import functools
import logging
from collections import deque
from dataclasses import asdict

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CoreState, callback
from homeassistant.util import dt as dt_util

from .gatekeeper.observations import (build_observation, is_observed_domain,
                                      resolve_source)

_LOGGER = logging.getLogger(__name__)
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
        try:
            await self._store.async_save(self.snapshot())
        except Exception:  # noqa: BLE001 — 落盘失败绝不连累卸载
            _LOGGER.exception("janus observation flush failed")


@callback
def _on_state_change(hass, log, janus_ctx_ids, event):
    if hass.state is not CoreState.running:
        return  # 启动/恢复期的 state_changed 是 restore 幻影,不是真行为
    if not is_observed_domain(event.data.get("entity_id", "")):
        return  # 只关心策展域,其余一次域判断即早退
    new = event.data.get("new_state")
    old = event.data.get("old_state")
    if new is None or new.state in ("unavailable", "unknown"):
        return
    if old is not None and old.state == new.state:
        return  # 纯属性变化(如 device_tracker 的 GPS 坐标动而状态不变),非真跳变
    ctx = event.context
    source = resolve_source(getattr(ctx, "user_id", None), getattr(ctx, "parent_id", None),
                            getattr(ctx, "id", None), janus_ctx_ids)
    log.record(build_observation(event.data["entity_id"], new.state, source))


def start_observer(hass, log, janus_ctx_ids=None):
    """监听全量 state_changed 总线(回调按域早退)→ race-free,运行时新设备立即纳入。
    janus_ctx_ids:Janus 自己执行动作时打的 context id 集合,用于把自家动作标 'janus'(剔出挖掘)。
    用 functools.partial 而非 lambda:保住 _on_state_change 的 @callback 标记,回调才在
    loop 线程内联跑(lambda 会被 HA 当 executor 任务、毁掉无锁不变量 + 线程池洪泛)。
    返回 unsub,交给 entry.async_on_unload。"""
    return hass.bus.async_listen(
        EVENT_STATE_CHANGED,
        functools.partial(_on_state_change, hass, log, janus_ctx_ids))


def _mine_and_log(records, tz_name):
    """executor 线程:在观察记录上跑挖掘器,把候选写进日志供人工 inspect。
    **只读、不投递、不执行**(codex #14:真数据前别把未验证关联产品化)。"""
    try:
        import time
        from zoneinfo import ZoneInfo

        from .gatekeeper.habit_mining import run_miners
        res = run_miners(records, time.time(), tz=ZoneInfo(tz_name))
        _LOGGER.info("janus 夜间挖掘:%d 触发候选 / %d 时段候选(共 %d 条观察)",
                     len(res.trigger_habits), len(res.time_habits), len(records))
        for h in res.trigger_habits[:5]:
            _LOGGER.info("  [触发] %s → %s=%s | 命中 %d/%d 周%d 一致性%.2f lift%.1f%s",
                         h.trigger, h.entity_id, h.new_state, h.support, h.triggers,
                         h.weeks, h.consistency, h.lift, " 疑时段混淆" if h.time_confounded else "")
    except Exception:  # noqa: BLE001 — 挖掘失败绝不连累 HA
        _LOGGER.exception("janus 夜间挖掘失败")


def start_nightly_mining(hass, log, tz_name, *, hour: int = 3):
    """每日 hour:00 静默跑挖掘器,候选写日志(只读)。回调在 loop 线程 → 重活 offload 到
    executor,绝不阻塞事件循环。返回 unsub,交给 entry.async_on_unload。"""
    from homeassistant.helpers.event import async_track_time_change

    @callback
    def _fire(_now):
        hass.async_add_executor_job(_mine_and_log, log.snapshot(), tz_name)

    return async_track_time_change(hass, _fire, hour=hour, minute=0, second=0)
