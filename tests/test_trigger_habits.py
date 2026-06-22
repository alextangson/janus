"""触发型挖掘器测试:对照-lift、否决门、来源过滤、arrival、时段混淆标志。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from gatekeeper.habits import ObservedEvent
from gatekeeper.trigger_habits import TriggerMineConfig, mine_trigger_habits

TZ = ZoneInfo("Asia/Shanghai")


def _ts(mon, day, h, m):
    return datetime(2026, mon, day, h, m, tzinfo=TZ).timestamp()


def _ev(mon, day, h, m, eid, state, source):
    return ObservedEvent(ts=_ts(mon, day, h, m), entity_id=eid, new_state=state, source=source)


NOW = _ts(6, 30, 23, 0)

# 8 个离家场合,跨 4 周、时刻各异(避开时段混淆):(月,日,时,分)
_DEPARTURES = [(6, 1, 7, 30), (6, 4, 9, 15), (6, 8, 8, 0), (6, 11, 18, 30),
               (6, 15, 7, 45), (6, 18, 12, 0), (6, 22, 8, 20), (6, 25, 21, 0)]


def _departure_events(source_present="physical"):
    return [_ev(mo, d, h, m, "person.alex", "not_home", "physical")
            for (mo, d, h, m) in _DEPARTURES]


def test_departure_action_detected_with_high_lift():
    # 离家后 5 分钟关空调,8 次里命中 7(漏最后一次);空调平时不关 → 基线极低 → lift 巨大
    ev = _departure_events()
    for (mo, d, h, m) in _DEPARTURES[:7]:
        mm = (m + 5) % 60
        hh = h + (1 if m + 5 >= 60 else 0)
        ev.append(_ev(mo, d, hh, mm, "climate.ac", "off", "physical"))
    out = mine_trigger_habits(ev, NOW, tz=TZ)
    assert len(out) == 1
    h0 = out[0]
    assert h0.trigger == "departure" and h0.entity_id == "climate.ac" and h0.new_state == "off"
    assert h0.support == 7 and h0.triggers == 8 and h0.misses == 1
    assert h0.consistency == 0.875 and h0.weeks == 4
    assert h0.lift > 10            # 对照证因果:远高于基线
    assert h0.time_confounded is False   # 命中时刻各异,非时段驱动


def test_high_base_rate_action_rejected_by_lift():
    # 一盏灯每小时关一次(基线极高),即便每次离家也跟着关 → lift≈consistency/0.5 ≤ 2 → 否决
    ev = _departure_events()
    for (mo, d, h, m) in _DEPARTURES:        # 跟随全部 8 次离家
        ev.append(_ev(mo, d, h, (m + 5) % 60, "light.noisy", "off", "physical"))
    base = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
    for i in range(720):                      # 30 天 × 24 次 = 高频噪声 → 基线高
        t = base.timestamp() + i * 3600
        ev.append(ObservedEvent(ts=t, entity_id="light.noisy", new_state="off", source="physical"))
    out = mine_trigger_habits(ev, NOW, tz=TZ)
    assert all(h.entity_id != "light.noisy" for h in out)  # 高基线被 lift 门刷掉


def test_insufficient_triggers_rejected():
    # 只 4 次离家(< min_triggers 6)→ 不出习惯
    deps = _DEPARTURES[:4]
    ev = [_ev(mo, d, h, m, "person.alex", "not_home", "physical") for (mo, d, h, m) in deps]
    for (mo, d, h, m) in deps:
        ev.append(_ev(mo, d, h, (m + 5) % 60, "climate.ac", "off", "physical"))
    assert mine_trigger_habits(ev, NOW, tz=TZ) == []


def test_insufficient_weeks_rejected():
    # 8 次离家全挤在一周(< min_weeks 3)→ 否决
    same_week = [(6, 1, 7, 0), (6, 1, 19, 0), (6, 2, 8, 0), (6, 2, 20, 0),
                 (6, 3, 7, 0), (6, 3, 18, 0), (6, 4, 9, 0), (6, 5, 8, 0)]
    ev = [_ev(mo, d, h, m, "person.alex", "not_home", "physical") for (mo, d, h, m) in same_week]
    for (mo, d, h, m) in same_week:
        ev.append(_ev(mo, d, h, m + 5, "climate.ac", "off", "physical"))
    assert mine_trigger_habits(ev, NOW, tz=TZ) == []


def test_janus_action_excluded_physical_included():
    # 同样模式:source=physical(米家)→ 挖到;source=janus(自家动作)→ 剔除、不学自己
    def build(source):
        ev = _departure_events()
        for (mo, d, h, m) in _DEPARTURES[:7]:
            ev.append(_ev(mo, d, h, (m + 5) % 60, "climate.ac", "off", source))
        return mine_trigger_habits(ev, NOW, tz=TZ)
    assert len(build("physical")) == 1
    assert build("janus") == []
    assert build("automation") == []


def test_arrival_trigger_detected():
    arrivals = [(6, 1, 18, 30), (6, 4, 19, 15), (6, 8, 17, 50), (6, 11, 20, 0),
                (6, 15, 18, 10), (6, 18, 21, 30), (6, 22, 19, 0), (6, 25, 18, 45)]
    ev = [_ev(mo, d, h, m, "person.alex", "home", "physical") for (mo, d, h, m) in arrivals]
    for (mo, d, h, m) in arrivals[:7]:
        ev.append(_ev(mo, d, h, m + 3, "light.entry", "on", "user"))
    out = mine_trigger_habits(ev, NOW, tz=TZ)
    assert len(out) == 1 and out[0].trigger == "arrival"
    assert out[0].entity_id == "light.entry" and out[0].new_state == "on"


def test_time_confounded_flag_when_clustered():
    # 离家与关空调都固定在 ~08:00 → 检出,但 time_confounded=True(可能只是重新发现时段)
    deps = [(6, 1, 8, 0), (6, 4, 8, 0), (6, 8, 8, 0), (6, 11, 8, 0),
            (6, 15, 8, 0), (6, 18, 8, 0), (6, 22, 8, 0), (6, 25, 8, 0)]
    ev = [_ev(mo, d, h, m, "person.alex", "not_home", "physical") for (mo, d, h, m) in deps]
    for (mo, d, h, m) in deps[:7]:
        ev.append(_ev(mo, d, 8, 5, "climate.ac", "off", "physical"))
    out = mine_trigger_habits(ev, NOW, tz=TZ)
    assert len(out) == 1 and out[0].time_confounded is True


def test_dedup_collapses_simultaneous_departures():
    # 两个住户同一时刻附近离家 = 一次"离家场合"(不重复计 M)
    ev = []
    for (mo, d, h, m) in _DEPARTURES:
        ev.append(_ev(mo, d, h, m, "person.alex", "not_home", "physical"))
        ev.append(_ev(mo, d, h, m + 2, "person.sam", "not_home", "physical"))  # 2 分钟内
        ev.append(_ev(mo, d, h, (m + 6) % 60, "climate.ac", "off", "physical"))
    out = mine_trigger_habits(ev, NOW, tz=TZ)
    assert len(out) == 1 and out[0].triggers == 8     # 16 次跳变 → 8 个场合


def test_empty_and_no_presence():
    assert mine_trigger_habits([], NOW, tz=TZ) == []
    only_actions = [_ev(6, 1, 8, 0, "climate.ac", "off", "physical")]
    assert mine_trigger_habits(only_actions, NOW, tz=TZ) == []
