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
