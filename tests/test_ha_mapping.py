import json
from pathlib import Path

from gatekeeper.ha_mapping import map_ha

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
    pos = devices["cover.garage_door"].operations["set_cover_position"].params["position"]
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
    # garage cover: opening is dangerous
    assert d["cover.garage_door"].operations["open_cover"].dangerous is True
    assert d["cover.garage_door"].operations["set_cover_position"].dangerous is True
    # curtain cover: safe
    assert d["cover.living_room_curtain"].operations["open_cover"].dangerous is False


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
