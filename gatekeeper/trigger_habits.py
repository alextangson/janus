"""触发型习惯挖掘的纯层:ObservedEvent → TriggerHabit(如 离家→关空调)。
无 IO、无 HA;tz/now 由调用方注入,validator.py 风格,零 ML。

与时段型(habits.py)的关键区别:这里学**因果关联**而非时段——动作 A 在触发 T(离家/到家)
后 W 分钟内发生。codex 深审要点已落实:
- 对照/lift:比"有触发时 A 的发生率(K/M)"与"A 的基线发生率"——证关联非巧合(co-occurrence≠causation)。
- 否决门:最小触发数 M、最小周数、最小一致性、最小 lift;记反例(misses)。
- 时段混淆标志(time_confounded):命中动作若在一天内某时刻紧聚集,可能只是重新发现时段而非触发。
- 动作来源含 physical(米家等集成关空调从 HA 看就是 physical),剔除 janus(自家动作)/automation。
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

from .habits import ObservedEvent

# presence 实体跳变到这些状态 = 触发
_TRIGGER_STATE = {"not_home": "departure", "home": "arrival"}


@dataclass(frozen=True)
class TriggerMineConfig:
    window_min: int = 30                # 动作须在触发后 W 分钟内
    dedup_min: int = 10                 # 多住户近时段离家折叠成一次"离家场合"
    min_triggers: int = 6               # M:触发场合数下限
    min_weeks: int = 3                  # 跨周下限
    min_consistency: float = 0.6        # K/M 下限(触发型比时段噪,门略低于 0.8)
    min_lift: float = 3.0               # 触发把动作概率抬到基线的至少 3 倍
    time_spread_min: int = 20           # 命中动作时刻聚集 ≤ 此 → 疑时段混淆
    action_sources: frozenset[str] = frozenset({"user", "physical"})
    action_domains: frozenset[str] = frozenset({"light", "cover", "lock", "climate"})
    presence_domains: frozenset[str] = field(
        default_factory=lambda: frozenset({"person", "device_tracker"}))


@dataclass(frozen=True)
class TriggerHabit:
    trigger: str          # departure | arrival
    entity_id: str        # 动作实体
    new_state: str        # 动作目标状态
    window_min: int
    support: int          # K:触发后命中动作的场合数
    triggers: int         # M:触发场合总数
    misses: int           # M-K:反例(触发了但没跟动作)
    weeks: int
    consistency: float    # K/M
    lift: float           # consistency / 基线发生率
    time_confounded: bool # 命中动作时刻聚集 → 可能时段驱动而非触发


def _local(ts: float, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def _iso_week(ts: float, tz: tzinfo) -> tuple[int, int]:
    iso = _local(ts, tz).isocalendar()
    return (iso[0], iso[1])


def _minute_of_day(ts: float, tz: tzinfo) -> int:
    d = _local(ts, tz)
    return d.hour * 60 + d.minute


def _dedup(ts_list: list[float], dedup_min: int) -> list[float]:
    """近 dedup_min 内的多次触发折叠为一次场合,保留簇内最后一次(更接近'都离家了')。"""
    if not ts_list:
        return []
    s = sorted(ts_list)
    out = [s[0]]
    for t in s[1:]:
        if t - out[-1] > dedup_min * 60:
            out.append(t)
        else:
            out[-1] = t
    return out


def mine_trigger_habits(events: list[ObservedEvent], now: float,
                        config: TriggerMineConfig = TriggerMineConfig(), *,
                        tz: tzinfo) -> list[TriggerHabit]:
    if not events:
        return []
    all_ts = [e.ts for e in events]
    span_min = (max(all_ts) - min(all_ts)) / 60.0
    if span_min <= 0:
        return []

    # 触发场合(按类型,去抖)
    trig: dict[str, list[float]] = {"departure": [], "arrival": []}
    for e in events:
        if e.entity_id.split(".")[0] in config.presence_domains:
            tt = _TRIGGER_STATE.get(e.new_state)
            if tt:
                trig[tt].append(e.ts)
    trig = {k: _dedup(v, config.dedup_min) for k, v in trig.items()}

    # 动作事件按 (实体, 状态) 分组(仅 user/physical;剔 janus/automation)
    actions: dict[tuple[str, str], list[float]] = {}
    for e in events:
        if (e.source in config.action_sources
                and e.entity_id.split(".")[0] in config.action_domains):
            actions.setdefault((e.entity_id, e.new_state), []).append(e.ts)
    actions = {k: sorted(v) for k, v in actions.items()}

    window_s = config.window_min * 60
    habits: list[TriggerHabit] = []
    for trigger_type, occasions in trig.items():
        m = len(occasions)
        if m < config.min_triggers:
            continue
        for (eid, state), ats in actions.items():
            hit_weeks: set[tuple[int, int]] = set()
            hit_action_ts: list[float] = []
            for t in occasions:
                lo = bisect.bisect_right(ats, t)  # 第一个 > t 的动作
                if lo < len(ats) and ats[lo] <= t + window_s:
                    hit_weeks.add(_iso_week(t, tz))
                    hit_action_ts.append(ats[lo])
            k = len(hit_action_ts)
            if k == 0:
                continue
            consistency = k / m
            weeks = len(hit_weeks)
            # 基线:动作在任意 W 窗里出现的概率 ≈ 动作次数 × W / 总观察时长(封顶 1)
            base_rate = min(1.0, len(ats) * config.window_min / span_min)
            lift = consistency / base_rate if base_rate > 0 else float("inf")
            mins = sorted(_minute_of_day(t, tz) for t in hit_action_ts)
            time_confounded = k >= 2 and (mins[-1] - mins[0]) <= config.time_spread_min
            if (consistency >= config.min_consistency and weeks >= config.min_weeks
                    and lift >= config.min_lift):
                habits.append(TriggerHabit(
                    trigger=trigger_type, entity_id=eid, new_state=state,
                    window_min=config.window_min, support=k, triggers=m, misses=m - k,
                    weeks=weeks, consistency=round(consistency, 3), lift=round(lift, 2),
                    time_confounded=time_confounded))
    habits.sort(key=lambda h: (-h.lift, -h.consistency, h.entity_id))
    return habits
