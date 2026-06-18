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


from datetime import date as _date
from gatekeeper.habits import _best_window


def test_best_window_picks_max_distinct_day_support():
    # 同一窗内,跨小时边界(06:55±)的多天事件应被一窗捕获
    pts = [
        (415, _date(2024, 1, 1)),  # 06:55
        (420, _date(2024, 1, 2)),  # 07:00
        (418, _date(2024, 1, 3)),  # 06:58
        (700, _date(2024, 1, 4)),  # 离群 11:40,不在窗内
    ]
    members, spread, typical = _best_window(pts, 20)
    days = {d for _, d in members}
    assert days == {_date(2024, 1, 1), _date(2024, 1, 2), _date(2024, 1, 3)}
    assert spread == 420 - 415
    assert typical == 418  # 中位(415,418,420)


def test_best_window_support_counts_distinct_days_not_events():
    # 同一天多次开关不灌水
    pts = [
        (420, _date(2024, 1, 1)), (421, _date(2024, 1, 1)), (419, _date(2024, 1, 1)),
        (420, _date(2024, 1, 2)),
    ]
    members, _, _ = _best_window(pts, 20)
    assert len({d for _, d in members}) == 2


def test_best_window_empty():
    assert _best_window([], 20) == ([], 0, 0)


def test_best_window_tiebreak_prefers_smaller_spread():
    # 两簇支持度都=2(相距 >20min 无法同窗),平手取 spread 小的那簇
    pts = [
        (400, _date(2024, 1, 1)), (401, _date(2024, 1, 2)),  # spread 1
        (500, _date(2024, 1, 1)), (519, _date(2024, 1, 2)),  # spread 19
    ]
    members, spread, _ = _best_window(pts, 20)
    assert spread == 1
    assert {m for m, _ in members} == {400, 401}
