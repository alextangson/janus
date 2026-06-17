from gatekeeper.models import Device, OperationSpec, ParamSpec
from service.device_dto import device_state, capabilities_to_dto, device_to_dto


def test_state_light_on_with_brightness():
    assert device_state("light", "on", {"brightness": 128}) == {"on": True, "brightness_pct": 50}


def test_state_light_off_no_brightness_key():
    assert device_state("light", "off", {}) == {"on": False}


def test_state_climate_running():
    out = device_state("climate", "cool",
                       {"current_temperature": 26, "temperature": 24})
    assert out == {"on": True, "hvac_mode": "cool",
                   "current_temperature": 26, "target_temperature": 24}


def test_state_climate_off():
    assert device_state("climate", "off", {}) == {"on": False, "hvac_mode": "off"}


def test_state_cover_open_with_position():
    assert device_state("cover", "open", {"current_position": 70}) == {"open": True, "position": 70}


def test_state_fan_on_with_percentage():
    assert device_state("fan", "on", {"percentage": 40}) == {"on": True, "percentage": 40}


def test_state_fan_on_missing_percentage_graceful():
    assert device_state("fan", "on", {}) == {"on": True}


def test_state_lock_locked():
    assert device_state("lock", "locked", {}) == {"locked": True}


def test_state_switch_on():
    assert device_state("switch", "on", {}) == {"on": True}


def test_state_unknown_domain_fallback():
    assert device_state("alarm_control_panel", "armed_away", {}) == {"state": "armed_away"}


def test_capabilities_to_dto_serializes_params_and_dangerous():
    dev = Device(name="门锁", type="lock", area="入户",
                 operations={"lock": OperationSpec(),
                             "unlock": OperationSpec(dangerous=True)})
    caps = capabilities_to_dto(dev)
    assert caps["unlock"] == {"dangerous": True, "params": {}}
    assert caps["lock"] == {"dangerous": False, "params": {}}


def test_capabilities_to_dto_param_fields():
    dev = Device(name="空调", type="climate", area="客厅",
                 operations={"set_temperature": OperationSpec(params={
                     "temperature": ParamSpec(type="int", min=16, max=30, unit="°C", required=True)})})
    p = capabilities_to_dto(dev)["set_temperature"]["params"]["temperature"]
    assert p == {"type": "int", "min": 16, "max": 30, "enum": None, "unit": "°C", "required": True}


def test_device_to_dto_shape_no_entity_id_leak_beyond_id():
    dev = Device(name="主灯", type="light", area="卧室", device_id="dev-abc",
                 operations={"turn_on": OperationSpec(), "turn_off": OperationSpec()})
    dto = device_to_dto("light.a", dev, {"on": True})
    assert dto == {
        "id": "light.a", "name": "主灯", "area": "卧室", "type": "light",
        "device_id": "dev-abc",
        "capabilities": {"turn_on": {"dangerous": False, "params": {}},
                         "turn_off": {"dangerous": False, "params": {}}},
        "state": {"on": True},
    }


def test_state_cover_closed():
    assert device_state("cover", "closed", {}) == {"open": False}


def test_state_cover_transitional_is_open():
    # 约定:opening/closing/stopped 均算 open(非 closed),与 queries.py 一致
    assert device_state("cover", "closing", {}) == {"open": True}


def test_state_valve_open_with_position():
    assert device_state("valve", "open", {"current_position": 30}) == {"open": True, "position": 30}


def test_state_lock_unlocked():
    assert device_state("lock", "unlocked", {}) == {"locked": False}
