from gatekeeper.observations import Observation, build_observation, classify_source


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
