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


from datetime import timedelta
from gatekeeper.habits import mine


def _wake_events(weeks, per_week_days=5, minute=425, source="user", entity="light.bed", state="on"):
    """构造 weeks 周、每周 per_week_days 个工作日、~minute 的事件。起点 2024-01-01(周一)。"""
    evs = []
    start = datetime(2024, 1, 1, 0, 0, tzinfo=TZ)
    for w in range(weeks):
        for dow in range(per_week_days):  # 0..4 = 周一到周五
            day = start + timedelta(days=w * 7 + dow)
            jitter = (dow % 3) - 1  # -1/0/1 分钟,窗内
            evs.append(ObservedEvent(
                ts=datetime(day.year, day.month, day.day, minute // 60, minute % 60 + jitter, tzinfo=TZ).timestamp(),
                entity_id=entity, new_state=state, source=source))
    return evs


def test_mines_weekday_wakeup_habit():
    evs = _wake_events(weeks=3)  # 15 个工作日事件
    now = datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp()
    habits = mine(evs, now, tz=TZ)
    assert len(habits) == 1
    h = habits[0]
    assert h.entity_id == "light.bed" and h.new_state == "on" and h.daytype == "weekday"
    assert 423 <= h.typical_minute <= 427
    assert h.support == 15 and h.weeks == 3
    assert h.consistency >= 0.8


def test_support_boundary_below_6():
    sparse = _wake_events(weeks=3, per_week_days=1)  # 3 事件,3 周 → support 3 < 6
    assert mine(sparse, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), tz=TZ) == []


def test_weeks_boundary_2_vs_3():
    two_weeks = _wake_events(weeks=2)  # 10 天但只跨 2 周
    assert mine(two_weeks, datetime(2024, 1, 15, 9, 0, tzinfo=TZ).timestamp(), tz=TZ) == []


def test_distinct_days_not_inflated_by_same_morning_toggles():
    evs = _wake_events(weeks=3)
    evs.append(ObservedEvent(ts=datetime(2024, 1, 1, 7, 6, tzinfo=TZ).timestamp(),
                             entity_id="light.bed", new_state="on", source="user"))
    habits = mine(evs, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), tz=TZ)
    assert habits[0].support == 15


def test_source_filter_excludes_automation_default_includes_physical_when_configured():
    auto = [ObservedEvent(ts=e.ts, entity_id=e.entity_id, new_state=e.new_state, source="automation")
            for e in _wake_events(weeks=3)]
    assert mine(auto, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), tz=TZ) == []
    phys = [ObservedEvent(ts=e.ts, entity_id=e.entity_id, new_state=e.new_state, source="physical")
            for e in _wake_events(weeks=3)]
    cfg = MineConfig(sources=frozenset({"user", "physical"}))
    assert len(mine(phys, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), cfg, tz=TZ)) == 1


def test_domain_filter_excludes_non_whitelisted():
    evs = [ObservedEvent(ts=e.ts, entity_id="sensor.temp", new_state="on", source="user")
           for e in _wake_events(weeks=3)]
    assert mine(evs, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), tz=TZ) == []


def test_weekday_and_weekend_do_not_merge():
    wk = _wake_events(weeks=3)
    we = []
    start = datetime(2024, 1, 6, 0, 0, tzinfo=TZ)  # 周六
    for w in range(3):
        for dow in range(2):
            day = start + timedelta(days=w * 7 + dow)
            we.append(ObservedEvent(ts=datetime(day.year, day.month, day.day, 7, 5, tzinfo=TZ).timestamp(),
                                    entity_id="light.bed", new_state="on", source="user"))
    habits = mine(wk + we, datetime(2024, 1, 25, 9, 0, tzinfo=TZ).timestamp(), tz=TZ)
    assert {h.daytype for h in habits} == {"weekday"}  # 周末仅 6 天 <6,不挖出


def test_eligible_days_uses_entity_active_window():
    evs = _wake_events(weeks=3)
    habits = mine(evs, datetime(2024, 1, 22, 9, 0, tzinfo=TZ).timestamp(), tz=TZ)
    assert habits[0].eligible_days <= 18  # 该实体活跃窗内工作日数,不是固定大窗


def test_empty_input():
    assert mine([], datetime(2024, 1, 1, 9, 0, tzinfo=TZ).timestamp(), tz=TZ) == []
