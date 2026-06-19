from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from gatekeeper.models import ScheduleIntent
from service.schedule_build import entry_from_intent

TZ = "Asia/Shanghai"  # 无 DST,壁钟可确定性回算
_ZI = ZoneInfo(TZ)


def _epoch(y: int, mo: int, d: int, h: int, mi: int) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=_ZI).timestamp()


# ---- 1. recurring daily 23:00 ----
def test_recurring_daily_2300():
    # now = 2026-06-18 10:00 上海 → 下一个 23:00 是当天
    now = _epoch(2026, 6, 18, 10, 0)
    entry = entry_from_intent(
        "climate.ac", "turn_off", {},
        ScheduleIntent(kind="recurring", hour=23, minute=0, recurrence="daily"),
        tz=TZ, now=now,
    )
    assert entry.kind == "recurring"
    assert entry.minute_of_day == 23 * 60  # 1380
    assert entry.days == [0, 1, 2, 3, 4, 5, 6]
    assert entry.at is None
    assert entry.next_fire_at > now
    assert entry.next_fire_at == _epoch(2026, 6, 18, 23, 0)


# ---- 2. once relative 1200s ----
def test_once_relative_1200():
    now = _epoch(2026, 6, 18, 10, 0)
    entry = entry_from_intent(
        "light.living", "turn_on", {"brightness": 80},
        ScheduleIntent(kind="once", relative_seconds=1200),
        tz=TZ, now=now,
    )
    assert entry.kind == "once"
    assert entry.at == now + 1200
    assert entry.next_fire_at == now + 1200
    assert entry.minute_of_day is None
    assert entry.days is None


# ---- 3. once absolute 08:00, now AFTER 08:00 → 次日 08:00 ----
def test_once_absolute_after_passes_to_next_day():
    now = _epoch(2026, 6, 18, 9, 30)  # 已过当天 08:00
    entry = entry_from_intent(
        "climate.ac", "turn_on", {},
        ScheduleIntent(kind="once", hour=8, minute=0),
        tz=TZ, now=now,
    )
    assert entry.kind == "once"
    assert entry.minute_of_day is None
    assert entry.days is None
    expected = _epoch(2026, 6, 19, 8, 0)  # 次日 08:00
    assert entry.next_fire_at == expected
    assert entry.at == expected


# ---- 4. once absolute 08:00, now BEFORE 08:00 → 当天 08:00 ----
def test_once_absolute_before_stays_today():
    now = _epoch(2026, 6, 18, 6, 30)  # 当天 08:00 之前
    entry = entry_from_intent(
        "climate.ac", "turn_on", {},
        ScheduleIntent(kind="once", hour=8, minute=0),
        tz=TZ, now=now,
    )
    expected = _epoch(2026, 6, 18, 8, 0)  # 当天 08:00
    assert entry.next_fire_at == expected
    assert entry.at == expected


# ---- 5. 字段透传正确 ----
def test_fields_set_correctly():
    now = _epoch(2026, 6, 18, 10, 0)
    params = {"brightness": 50, "color": "warm"}
    entry = entry_from_intent(
        "light.bedroom", "turn_on", params,
        ScheduleIntent(kind="once", relative_seconds=600),
        tz=TZ, now=now,
    )
    assert entry.device_id == "light.bedroom"
    assert entry.operation == "turn_on"
    assert entry.params == params
    assert entry.params is not params  # 防御性拷贝
    assert entry.tz == TZ
    assert entry.enabled is True
    assert isinstance(entry.id, str) and entry.id
    assert entry.created_at == now
    assert entry.last_attempt is None
    assert entry.last_outcome is None


# ---- 6. weekday preset ----
def test_recurring_weekday_preset():
    now = _epoch(2026, 6, 18, 10, 0)
    entry = entry_from_intent(
        "climate.ac", "turn_off", {},
        ScheduleIntent(kind="recurring", hour=7, minute=30, recurrence="weekday"),
        tz=TZ, now=now,
    )
    assert entry.days == [0, 1, 2, 3, 4]
    assert entry.minute_of_day == 7 * 60 + 30


# ---- 7. weekend preset ----
def test_recurring_weekend_preset():
    now = _epoch(2026, 6, 18, 10, 0)
    entry = entry_from_intent(
        "climate.ac", "turn_off", {},
        ScheduleIntent(kind="recurring", hour=9, minute=0, recurrence="weekend"),
        tz=TZ, now=now,
    )
    assert entry.days == [5, 6]


# ---- 8. unique ids ----
def test_unique_ids():
    now = _epoch(2026, 6, 18, 10, 0)
    intent = ScheduleIntent(kind="once", relative_seconds=300)
    a = entry_from_intent("light.a", "turn_on", {}, intent, tz=TZ, now=now)
    b = entry_from_intent("light.b", "turn_on", {}, intent, tz=TZ, now=now)
    assert a.id != b.id
