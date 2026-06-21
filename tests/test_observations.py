from gatekeeper.observations import (Observation, build_observation, classify_source,
                                     is_observed_domain, resolve_source)


def test_is_observed_domain():
    # 动作域 + 触发域(presence)都观察;无关域早退
    for eid in ("light.a", "cover.c", "lock.l", "climate.ac",
                "person.alex", "device_tracker.alex_phone"):
        assert is_observed_domain(eid), eid
    for eid in ("switch.x", "sensor.temp", "binary_sensor.motion"):
        assert not is_observed_domain(eid), eid


def test_resolve_source_marks_janus_own_actions():
    janus = {"ctx-janus-1"}
    assert resolve_source(None, None, "ctx-janus-1", janus) == "janus"     # 自己动作的 ctx
    assert resolve_source(None, "ctx-janus-1", "child", janus) == "janus"  # 子事件 parent 命中
    assert resolve_source("alex", None, "ctx-x", janus) == "user"          # 别人(有 user_id)
    assert resolve_source(None, None, "ctx-x", janus) == "physical"        # 真物理/米家
    assert resolve_source(None, None, "ctx-janus-1", None) == "physical"   # 无 janus 集合则不特判
    assert resolve_source(None, None, "ctx-janus-1", set()) == "physical"  # 空集合同理


def test_build_observation_derives_domain():
    o = build_observation("light.bedroom", "on", "user")
    assert o == Observation(entity_id="light.bedroom", domain="light",
                            new_state="on", source="user")


def test_build_observation_cover_lock():
    assert build_observation("cover.living_room_curtain", "open", "physical").domain == "cover"
    assert build_observation("lock.front_door", "locked", "automation").domain == "lock"


def test_classify_source():
    assert classify_source("abc123", None) == "user"        # 有 user_id → 人
    assert classify_source("abc123", "p1") == "user"         # user_id 优先
    assert classify_source(None, "p1") == "automation"       # 仅 parent_id → 自动化
    assert classify_source(None, None) == "physical"         # 都无 → 物理/直报
