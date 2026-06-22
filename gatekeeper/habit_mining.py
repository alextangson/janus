"""习惯挖掘编排(纯层):ObservationLog 落盘记录 → 跑时段型 + 触发型挖掘器 → 候选。
无 IO、无 HA;把"在真观察数据上跑挖掘"与 HA 调度/存储解耦,可测。

codex #14:真数据前别把未验证关联产品化 → 本编排只产出**候选供人工 inspect**,
不投递、不执行。投递(推送)在 HA 层且等数据 + 人工查后才开。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from .habits import Habit, MineConfig, ObservedEvent, mine
from .trigger_habits import TriggerHabit, TriggerMineConfig, mine_trigger_habits

# 时段型也纳入 physical(米家等集成的人为操作从 HA 看是 physical),与触发型一致;剔 janus/automation。
_TIME_CONFIG = MineConfig(sources=frozenset({"user", "physical"}))


@dataclass(frozen=True)
class MiningResult:
    time_habits: list[Habit]
    trigger_habits: list[TriggerHabit]


def records_to_events(records: list[dict]) -> list[ObservedEvent]:
    """ObservationLog.snapshot() 的 dict(ts 为 ISO 串)→ ObservedEvent(ts 为 epoch 秒)。
    形状不全/解析失败的记录跳过,绝不连累整轮挖掘。"""
    out: list[ObservedEvent] = []
    for r in records:
        try:
            ts = r["ts"]
            ts = datetime.fromisoformat(ts).timestamp() if isinstance(ts, str) else float(ts)
            eid, state, src = r["entity_id"], r["new_state"], r.get("source") or "physical"
        except (KeyError, TypeError, ValueError):
            continue
        if eid and state:
            out.append(ObservedEvent(ts=ts, entity_id=eid, new_state=state, source=src))
    return out


def run_miners(records: list[dict], now: float, *, tz: tzinfo,
               time_config: MineConfig = _TIME_CONFIG,
               trigger_config: TriggerMineConfig = TriggerMineConfig()) -> MiningResult:
    events = records_to_events(records)
    return MiningResult(
        time_habits=mine(events, now, time_config, tz=tz),
        trigger_habits=mine_trigger_habits(events, now, trigger_config, tz=tz))
