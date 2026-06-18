"""习惯挖掘的纯层:ObservationLog(带 ts) → 可读 Habit。
无 IO、无 HA;tz/now 由调用方注入,保持确定可测(validator.py 风格,零 ML)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo


@dataclass(frozen=True)
class ObservedEvent:
    ts: float          # epoch 秒(HA 落盘时盖)
    entity_id: str
    new_state: str
    source: str        # user / automation / physical


@dataclass(frozen=True)
class MineConfig:
    min_support: int = 6
    min_weeks: int = 3
    min_consistency: float = 0.8
    max_spread_min: int = 20
    sources: frozenset[str] = frozenset({"user"})
    domains: frozenset[str] = frozenset({"light", "cover", "lock"})


@dataclass(frozen=True)
class Habit:
    entity_id: str
    domain: str
    new_state: str
    daytype: str          # weekday | weekend
    typical_minute: int
    support: int          # 不同天数
    eligible_days: int
    weeks: int
    consistency: float
    spread_min: int


def _local(ts: float, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def _daytype(d: date | datetime) -> str:
    # date 与 datetime 都有 weekday();周六=5、周日=6
    return "weekend" if d.weekday() >= 5 else "weekday"


def _minute_of_day(dt: datetime) -> int:
    # 分钟粒度(丢秒):窗口/spread 全按分钟,秒级精度对习惯无意义
    return dt.hour * 60 + dt.minute


def _iso_week(dt: date | datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return (iso.year, iso.week)


def _best_window(points: list[tuple[int, date]], max_spread: int
                 ) -> tuple[list[tuple[int, date]], int, int]:
    """points = [(minute_of_day, local_date)]。在所有宽 max_spread 的窗 [m, m+max_spread]
    里,取**不同天数最多**的窗(平手:实际 spread 小者优先,再 typical 早者)。
    返回 (窗内成员, spread_min, typical_minute=窗内 minute 中位)。空输入 → ([], 0, 0)。
    """
    if not points:
        return ([], 0, 0)
    pts = sorted(points, key=lambda p: p[0])
    best_key: tuple[int, int, int] | None = None
    best: tuple[list[tuple[int, date]], int, int] | None = None
    for start_min, _ in pts:
        members = [p for p in pts if start_min <= p[0] <= start_min + max_spread]
        minutes = [m for m, _ in members]
        support = len({d for _, d in members})
        spread = max(minutes) - min(minutes)
        typical = sorted(minutes)[len(minutes) // 2]
        key = (support, -spread, -typical)  # 最大化:支持度↑、spread↓、typical↑早
        if best_key is None or key > best_key:
            best_key = key
            best = (members, spread, typical)
    assert best is not None
    return best


def _eligible_days(start: date, end: date, daytype: str, now_minute: int, typical: int) -> int:
    """[start, end] 内该 daytype 的本地日期数;当天(==end)仅在已过 typical_minute 才计。"""
    n = 0
    d = start
    one = timedelta(days=1)
    while d <= end:
        if _daytype(d) == daytype and (d < end or now_minute >= typical):
            n += 1
        d += one
    return n


def mine(events: list[ObservedEvent], now: float,
         config: MineConfig = MineConfig(), *, tz: tzinfo) -> list[Habit]:
    if not events:
        return []

    # 实体活跃窗起点:该 entity 的最早 ts(任何 source/state)
    first_ts: dict[str, float] = {}
    for e in events:
        if e.entity_id not in first_ts or e.ts < first_ts[e.entity_id]:
            first_ts[e.entity_id] = e.ts
    active_start = {eid: _local(t, tz).date() for eid, t in first_ts.items()}

    now_dt = _local(now, tz)
    now_date = now_dt.date()
    now_minute = _minute_of_day(now_dt)

    groups: dict[tuple[str, str, str], list[tuple[int, date]]] = {}
    for e in events:
        if e.source not in config.sources:
            continue
        if e.entity_id.split(".")[0] not in config.domains:
            continue
        dt = _local(e.ts, tz)
        key = (e.entity_id, e.new_state, _daytype(dt))
        groups.setdefault(key, []).append((_minute_of_day(dt), dt.date()))

    habits: list[Habit] = []
    for (eid, state, daytype), points in groups.items():
        members, spread, typical = _best_window(points, config.max_spread_min)
        if not members:
            continue
        dates = {d for _, d in members}
        support = len(dates)
        weeks = len({_iso_week(d) for d in dates})
        # 分母延伸到 now(spec):近期不再触发的习惯,consistency 应随之衰减、自然出局
        eligible = _eligible_days(active_start[eid], now_date, daytype, now_minute, typical)
        if eligible == 0:
            continue
        consistency = support / eligible
        if (support >= config.min_support and weeks >= config.min_weeks
                and consistency >= config.min_consistency):
            habits.append(Habit(
                entity_id=eid, domain=eid.split(".")[0], new_state=state, daytype=daytype,
                typical_minute=typical, support=support, eligible_days=eligible,
                weeks=weeks, consistency=consistency, spread_min=spread))

    habits.sort(key=lambda h: (-h.consistency, -h.support, h.spread_min))
    return habits
