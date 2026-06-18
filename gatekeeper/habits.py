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
    return dt.hour * 60 + dt.minute


def _iso_week(dt: date | datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return (iso.year, iso.week)
