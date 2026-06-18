from datetime import datetime
from zoneinfo import ZoneInfo

from gatekeeper.habits import (
    ObservedEvent, MineConfig, Habit,
    _local, _daytype, _minute_of_day, _iso_week,
)

TZ = ZoneInfo("Asia/Shanghai")  # UTC+8,无 DST


def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_daytype_weekday_vs_weekend():
    # 2024-01-01 是周一,2024-01-06 是周六(公认参照)
    assert _daytype(_local(_ts(2024, 1, 1, 7, 0), TZ)) == "weekday"
    assert _daytype(_local(_ts(2024, 1, 6, 7, 0), TZ)) == "weekend"


def test_minute_of_day():
    assert _minute_of_day(_local(_ts(2024, 1, 1, 7, 5), TZ)) == 7 * 60 + 5


def test_iso_week():
    assert _iso_week(_local(_ts(2024, 1, 1, 7, 0), TZ)) == (2024, 1)
    assert _iso_week(_local(_ts(2024, 1, 15, 7, 0), TZ)) == (2024, 3)


def test_iso_week_year_boundary():
    # 2019-12-30(周一)属 ISO 2020-W01(含次年首个周四)——min_weeks 跨年计数靠它
    assert _iso_week(_local(_ts(2019, 12, 30, 7, 0), TZ)) == (2020, 1)


def test_config_and_dataclass_defaults():
    c = MineConfig()
    assert c.min_support == 6 and c.min_weeks == 3
    assert c.min_consistency == 0.8 and c.max_spread_min == 20
    assert c.sources == frozenset({"user"})
    assert c.domains == frozenset({"light", "cover", "lock"})
    e = ObservedEvent(ts=1.0, entity_id="light.a", new_state="on", source="user")
    assert e.entity_id == "light.a"
    h = Habit(entity_id="light.a", domain="light", new_state="on", daytype="weekday",
              typical_minute=425, support=15, eligible_days=15, weeks=3,
              consistency=1.0, spread_min=8)
    assert h.typical_minute == 425
