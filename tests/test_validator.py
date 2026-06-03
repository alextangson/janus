from gatekeeper.models import ParseResult
from gatekeeper.validator import check_feasibility


def _pr(**kw):
    base = {"recognized": True, "confidence": 1.0}
    base.update(kw)
    return ParseResult.model_validate(base)


def test_valid_command_returns_none(registry):
    pr = _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": 24})
    assert check_feasibility(pr, registry) is None


def test_valid_command_with_no_params(registry):
    pr = _pr(device_id="light.living_room", operation="turn_off")
    assert check_feasibility(pr, registry) is None


def test_unknown_device(registry):
    pr = _pr(device_id="light.garage", operation="turn_on")
    assert "设备不存在" in check_feasibility(pr, registry)


def test_unsupported_operation(registry):
    pr = _pr(device_id="switch.kitchen_socket", operation="set_temperature", params={"temperature": 24})
    assert "不支持操作" in check_feasibility(pr, registry)


def test_missing_required_param(registry):
    pr = _pr(device_id="climate.living_room", operation="set_temperature")
    assert "缺少必填参数" in check_feasibility(pr, registry)


def test_unknown_param(registry):
    pr = _pr(device_id="light.living_room", operation="turn_on", params={"color": "blue"})
    assert "未知参数" in check_feasibility(pr, registry)


def test_int_out_of_range_high(registry):
    pr = _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": 50})
    assert "超出范围" in check_feasibility(pr, registry)


def test_int_out_of_range_low(registry):
    pr = _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": 5})
    assert "低于下限" in check_feasibility(pr, registry)


def test_bool_is_not_a_valid_int(registry):
    pr = _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": True})
    assert "类型应为整数" in check_feasibility(pr, registry)


def test_enum_invalid_value(registry):
    pr = _pr(device_id="climate.living_room", operation="set_mode", params={"mode": "turbo"})
    assert "取值非法" in check_feasibility(pr, registry)


def test_enum_valid_value(registry):
    pr = _pr(device_id="climate.living_room", operation="set_mode", params={"mode": "cool"})
    assert check_feasibility(pr, registry) is None
