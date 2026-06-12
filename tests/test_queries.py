from gatekeeper.queries import answer_query
from gatekeeper.models import Device, OperationSpec
from gatekeeper.registry import Registry


def _reg():
    op = {"turn_on": OperationSpec(), "turn_off": OperationSpec()}
    return Registry({
        "climate.ac": Device(name="客厅空调", type="climate", area="客厅", operations=op),
        "light.a": Device(name="主灯", type="light", area="卧室", operations=op),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=op),
        "cover.curtain": Device(name="窗帘", type="cover", area="客厅", operations=op),
        "lock.door": Device(name="大门", type="lock", area="门厅", operations=op),
        "fan.f": Device(name="风扇", type="fan", area="卧室", operations=op),
        "switch.plug": Device(name="插座", type="switch", area="厨房", operations=op),
    })


def _st(eid, state, **attrs):
    return {"entity_id": eid, "state": state, "attributes": attrs}


def test_climate_full():
    states = [_st("climate.ac", "cool", current_temperature=24.0, temperature=22)]
    assert answer_query("climate.ac", [], states, _reg()) == "客厅空调:制冷,当前 24.0°C,设定 22°C"


def test_climate_off_shows_off():
    states = [_st("climate.ac", "off", current_temperature=24.0, temperature=22)]
    assert answer_query("climate.ac", [], states, _reg()) == "客厅空调:关"


def test_climate_missing_fields():
    states = [_st("climate.ac", "heat")]
    assert answer_query("climate.ac", [], states, _reg()) == "客厅空调:制热"


def test_light_on_off():
    assert answer_query("light.a", [], [_st("light.a", "on")], _reg()) == "主灯:开"
    assert answer_query("light.a", [], [_st("light.a", "off")], _reg()) == "主灯:关"


def test_switch_on():
    assert answer_query("switch.plug", [], [_st("switch.plug", "on")], _reg()) == "插座:开"


def test_cover_with_position():
    states = [_st("cover.curtain", "open", current_position=60)]
    assert answer_query("cover.curtain", [], states, _reg()) == "窗帘:开,60%"


def test_cover_without_position():
    assert answer_query("cover.curtain", [], [_st("cover.curtain", "closed")], _reg()) == "窗帘:关"


def test_lock():
    assert answer_query("lock.door", [], [_st("lock.door", "locked")], _reg()) == "大门:已锁"
    assert answer_query("lock.door", [], [_st("lock.door", "unlocked")], _reg()) == "大门:已开"


def test_fan_with_percentage():
    assert answer_query("fan.f", [], [_st("fan.f", "on", percentage=40)], _reg()) == "风扇:开,40%"


def test_device_not_found():
    assert answer_query("light.ghost", [], [], _reg()) == "没查到「light.ghost」"


def test_device_in_registry_but_no_state():
    assert answer_query("light.a", [], [], _reg()) == "没查到「light.a」"


def test_candidates_render_each_line():
    states = [_st("light.a", "on"), _st("light.b", "off")]
    out = answer_query(None, ["light.a", "light.b"], states, _reg())
    assert out == "主灯:开\n氛围灯:关"


def test_no_target_at_all():
    assert answer_query(None, [], [], _reg()) == "没听清要查哪个设备"
