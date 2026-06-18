from gatekeeper.models import Decision, Device, OperationSpec
from gatekeeper.phrasing import describe_action
from gatekeeper.registry import Registry


def _reg():
    return Registry({
        "climate.ac": Device(name="空调", type="climate", area="卧室",
                             operations={"set_temperature": OperationSpec(),
                                         "set_hvac_mode": OperationSpec(), "turn_off": OperationSpec()}),
        "lock.door": Device(name="入户门锁", type="lock", area="门厅",
                            operations={"unlock": OperationSpec(dangerous=True)}),
        "light.a": Device(name="主灯", type="light", area="客厅",
                          operations={"turn_on": OperationSpec(), "turn_off": OperationSpec()}),
        "cover.c": Device(name="窗帘", type="cover", area="客厅",
                          operations={"open_cover": OperationSpec(), "set_percentage": OperationSpec()}),
    })


def _d(op, params=None, device_id="climate.ac"):
    return Decision(verdict="confirm", stage="inferred", device_id=device_id, operation=op, params=params or {})


def test_set_temperature_natural():
    assert describe_action(_d("set_temperature", {"temperature": 28}), _reg()) == "把空调调到 28°C"


def test_set_hvac_mode_chinese():
    assert describe_action(_d("set_hvac_mode", {"hvac_mode": "heat"}), _reg()) == "把空调切到制热"


def test_turn_on_off_use_device_name():
    assert describe_action(_d("turn_on", device_id="light.a"), _reg()) == "打开主灯"
    assert describe_action(_d("turn_off", device_id="light.a"), _reg()) == "关闭主灯"


def test_unlock_lock():
    assert describe_action(_d("unlock", device_id="lock.door"), _reg()) == "解锁入户门锁"


def test_cover_open_and_percentage():
    assert describe_action(_d("open_cover", device_id="cover.c"), _reg()) == "打开窗帘"
    assert describe_action(_d("set_percentage", {"percentage": 60}, device_id="cover.c"), _reg()) == "把窗帘调到 60%"


def test_no_leak_for_unknown_op():
    s = describe_action(_d("weird_op", {"foo": "bar"}), _reg())
    assert "climate.ac" not in s and "weird_op" not in s and "{" not in s and "}" not in s


def test_unknown_device_never_leaks_entity_id():
    s = describe_action(_d("turn_on", device_id="switch.ghost_xyz"), _reg())
    assert "switch.ghost_xyz" not in s


def test_set_fan_mode_natural():
    assert describe_action(_d("set_fan_mode", {"fan_mode": "high"}), _reg()) == "把空调风速调到高"


def test_set_preset_mode_natural():
    assert describe_action(_d("set_preset_mode", {"preset_mode": "sleep"}), _reg()) == "把空调切到睡眠模式"


def test_set_swing_mode_fallback_is_localized():
    # swing 走兜底,但参数名与值都中文化(注意是全角括号)
    assert describe_action(_d("set_swing_mode", {"swing_mode": "vertical"}), _reg()) == "调节空调（上下扫风 上下）"
