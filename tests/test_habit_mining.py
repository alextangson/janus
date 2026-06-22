"""挖掘编排测试:ObservationLog 记录(ISO ts)→ 候选;坏记录跳过。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from gatekeeper.habit_mining import records_to_events, run_miners

TZ = ZoneInfo("Asia/Shanghai")


def _iso(mon, day, h, m):
    return datetime(2026, mon, day, h, m, tzinfo=TZ).isoformat()


def _rec(mon, day, h, m, eid, state, source):
    return {"entity_id": eid, "domain": eid.split(".")[0],
            "new_state": state, "source": source, "ts": _iso(mon, day, h, m)}


NOW = datetime(2026, 6, 30, 23, 0, tzinfo=TZ).timestamp()
_DEPS = [(6, 1, 7, 30), (6, 4, 9, 15), (6, 8, 8, 0), (6, 11, 18, 30),
         (6, 15, 7, 45), (6, 18, 12, 0), (6, 22, 8, 20), (6, 25, 21, 0)]


def test_records_to_events_parses_iso_and_skips_bad():
    recs = [
        _rec(6, 1, 8, 0, "climate.ac", "off", "physical"),
        {"entity_id": "light.a"},                 # 缺字段 → 跳
        {"entity_id": "light.b", "new_state": "on", "source": "user", "ts": "not-a-date"},  # 坏 ts → 跳
    ]
    events = records_to_events(recs)
    assert len(events) == 1
    assert events[0].entity_id == "climate.ac" and isinstance(events[0].ts, float)


def test_run_miners_finds_trigger_habit_from_records():
    recs = [_rec(mo, d, h, m, "person.alex", "not_home", "physical") for (mo, d, h, m) in _DEPS]
    for (mo, d, h, m) in _DEPS[:7]:
        recs.append(_rec(mo, d, h, (m + 5) % 60, "climate.ac", "off", "physical"))
    res = run_miners(recs, NOW, tz=TZ)
    assert len(res.trigger_habits) == 1
    th = res.trigger_habits[0]
    assert th.trigger == "departure" and th.entity_id == "climate.ac" and th.support == 7


def test_run_miners_empty():
    res = run_miners([], NOW, tz=TZ)
    assert res.time_habits == [] and res.trigger_habits == []
