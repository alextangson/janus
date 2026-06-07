import json
from pathlib import Path

from gatekeeper.ha_mapping import build_registry_snapshot, map_ha

FIX = Path(__file__).resolve().parent / "fixtures"


def _states():
    return json.loads((FIX / "ha_states.json").read_text(encoding="utf-8"))


def _services():
    return json.loads((FIX / "ha_services.json").read_text(encoding="utf-8"))


def test_filters_to_supported_domains():
    devices = map_ha(_states(), _services())
    assert "sensor.temperature" not in devices  # read-only sensor filtered
    assert set(devices) == {
        "light.living_room", "switch.kitchen_socket", "climate.living_room",
        "cover.garage_door", "cover.living_room_curtain", "lock.front_door",
        "alarm_control_panel.home", "fan.bedroom", "valve.gas_main",
    }


def test_basic_fields():
    d = map_ha(_states(), _services())["lock.front_door"]
    assert d.name == "大门门锁"
    assert d.type == "lock"
    assert set(d.operations) == {"lock", "unlock"}


def test_light_brightness_param():
    light = map_ha(_states(), _services())["light.living_room"]
    p = light.operations["turn_on"].params["brightness_pct"]
    assert (p.type, p.min, p.max, p.required) == ("int", 0, 100, False)


def test_climate_temp_and_mode_params():
    c = map_ha(_states(), _services())["climate.living_room"]
    temp = c.operations["set_temperature"].params["temperature"]
    assert (temp.type, temp.min, temp.max, temp.required) == ("int", 16, 30, True)
    mode = c.operations["set_hvac_mode"].params["hvac_mode"]
    assert mode.type == "enum"
    assert mode.enum == ["off", "cool", "heat", "auto"]


def test_position_params():
    devices = map_ha(_states(), _services())
    pos = devices["cover.living_room_curtain"].operations["set_cover_position"].params["position"]
    assert (pos.min, pos.max, pos.required) == (0, 100, True)
    pct = devices["fan.bedroom"].operations["set_percentage"].params["percentage"]
    assert (pct.min, pct.max, pct.required) == (0, 100, True)


def test_operations_filtered_by_available_services():
    # a light whose domain only exposes turn_on (no turn_off) gets only turn_on
    services = [{"domain": "light", "services": {"turn_on": {}}}]
    light = map_ha(_states(), services)["light.living_room"]
    assert set(light.operations) == {"turn_on"}


def test_malformed_entity_is_skipped_not_fatal():
    # entries with no entity_id raise mid-map and must be skipped, not crash the run
    states = _states() + [{"state": "weird"}, {"foo": "bar"}]
    devices = map_ha(states, _services())
    assert "lock.front_door" in devices  # good entities still mapped
    assert len(devices) == 9             # 9 supported domains in the clean fixture; junk skipped


def test_danger_defaults_per_operation():
    d = map_ha(_states(), _services())
    assert d["lock.front_door"].operations["unlock"].dangerous is True
    assert d["lock.front_door"].operations["lock"].dangerous is False
    assert d["alarm_control_panel.home"].operations["alarm_disarm"].dangerous is True
    assert d["alarm_control_panel.home"].operations["alarm_arm_away"].dangerous is False
    assert d["valve.gas_main"].operations["open_valve"].dangerous is True
    assert d["switch.kitchen_socket"].operations["turn_on"].dangerous is False


def test_cover_danger_depends_on_device_class():
    d = map_ha(_states(), _services())
    # garage cover: opening is dangerous; a garage door has no set-position capability
    assert d["cover.garage_door"].operations["open_cover"].dangerous is True
    assert "set_cover_position" not in d["cover.garage_door"].operations
    # curtain cover: safe (and supports position)
    assert d["cover.living_room_curtain"].operations["open_cover"].dangerous is False
    assert d["cover.living_room_curtain"].operations["set_cover_position"].dangerous is False


def test_overrides_tighten_and_relax():
    overrides = {
        "switch.kitchen_socket": {"turn_on": True},   # tighten a safe op
        "lock.front_door": {"unlock": False},          # relax a dangerous op
    }
    d = map_ha(_states(), _services(), overrides)
    assert d["switch.kitchen_socket"].operations["turn_on"].dangerous is True
    assert d["lock.front_door"].operations["unlock"].dangerous is False


def test_load_overrides_missing_file_returns_empty(tmp_path):
    from gatekeeper.ha_mapping import load_overrides
    assert load_overrides(tmp_path / "nope.json") == {}
    f = tmp_path / "ov.json"
    f.write_text('{"lock.front_door": {"unlock": false}}', encoding="utf-8")
    assert load_overrides(f) == {"lock.front_door": {"unlock": False}}


def test_lock_open_unlatch_is_dangerous_when_available():
    states = [{"entity_id": "lock.front_door", "state": "locked", "attributes": {"friendly_name": "大门门锁", "supported_features": 1}}]
    services = [{"domain": "lock", "services": {"lock": {}, "unlock": {}, "open": {}}}]
    d = map_ha(states, services)["lock.front_door"]
    assert "open" in d.operations
    assert d.operations["open"].dangerous is True


def test_lock_without_open_service_has_no_open_op():
    # the standard fixture lock exposes only lock/unlock -> no 'open' op leaks in
    d = map_ha(_states(), _services())["lock.front_door"]
    assert set(d.operations) == {"lock", "unlock"}


def test_cover_without_device_class_defaults_safe():
    states = [{"entity_id": "cover.unknown", "state": "open", "attributes": {"friendly_name": "未知卷帘", "supported_features": 15}}]
    services = [{"domain": "cover", "services": {"open_cover": {}, "close_cover": {}, "set_cover_position": {}}}]
    d = map_ha(states, services)["cover.unknown"]
    assert d.operations["open_cover"].dangerous is False
    assert d.operations["set_cover_position"].dangerous is False


def test_capability_ops_gated_by_supported_features():
    # the 'open' service exists in the domain, but the per-entity OPEN feature bit gates it
    lock_services = [{"domain": "lock", "services": {"lock": {}, "unlock": {}, "open": {}}}]
    no_open = [{"entity_id": "lock.basic", "state": "locked", "attributes": {"friendly_name": "Basic", "supported_features": 0}}]
    assert set(map_ha(no_open, lock_services)["lock.basic"].operations) == {"lock", "unlock"}
    has_open = [{"entity_id": "lock.fancy", "state": "locked", "attributes": {"friendly_name": "Fancy", "supported_features": 1}}]
    assert "open" in map_ha(has_open, lock_services)["lock.fancy"].operations

    # set_cover_position gated by the SET_POSITION bit (4): a garage (sf=3) loses it
    cover_services = [{"domain": "cover", "services": {"open_cover": {}, "close_cover": {}, "set_cover_position": {}}}]
    no_pos = [{"entity_id": "cover.simple", "state": "closed", "attributes": {"friendly_name": "Simple", "supported_features": 3}}]
    assert set(map_ha(no_pos, cover_services)["cover.simple"].operations) == {"open_cover", "close_cover"}


def test_build_snapshot_indexes_by_id():
    entities = [{"entity_id": "light.x", "device_id": "d1", "area_id": None, "entity_category": None}]
    devices = [{"id": "d1", "area_id": "a1"}]
    areas = [{"area_id": "a1", "name": "客厅"}]
    snap = build_registry_snapshot(entities, devices, areas)
    assert snap.by_entity["light.x"]["device_id"] == "d1"
    assert snap.by_device["d1"]["area_id"] == "a1"
    assert snap.by_area["a1"] == "客厅"


def test_build_snapshot_skips_malformed():
    snap = build_registry_snapshot(
        [{"no_entity_id": 1}, "garbage", {"entity_id": "light.ok"}],
        ["bad", {"id": "d1"}],
        [{"name": "no id"}, {"area_id": "a1", "name": "A"}],
    )
    assert list(snap.by_entity) == ["light.ok"]
    assert list(snap.by_device) == ["d1"]
    assert snap.by_area == {"a1": "A"}
