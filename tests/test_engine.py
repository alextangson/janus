import math

import pytest

from gatekeeper.engine import Engine
from gatekeeper.models import ParseResult

from tests._helpers import FakeParser, RaisingParser, ValidatingParser


def _engine(registry, result, tau=0.7):
    return Engine(FakeParser(result), registry, tau=tau)


def _pr(**kw):
    base = {"recognized": True, "confidence": 1.0}
    base.update(kw)
    return ParseResult.model_validate(base)


def test_unrecognized_is_rejected(registry):
    eng = _engine(registry, _pr(recognized=False, confidence=0.0))
    d = eng.decide("把那个东西弄一下")
    assert d.verdict == "reject"
    assert d.stage == "parse"


def test_safe_feasible_confident_is_allowed(registry):
    eng = _engine(registry, _pr(device_id="light.living_room", operation="turn_on"))
    d = eng.decide("开客厅灯")
    assert d.verdict == "allow"
    assert d.stage == "passed"
    assert d.device_id == "light.living_room"


def test_out_of_range_is_rejected_at_feasibility(registry):
    eng = _engine(registry, _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": 50}))
    d = eng.decide("空调开到50度")
    assert d.verdict == "reject"
    assert d.stage == "feasibility"
    assert "超出范围" in d.reason


def test_low_confidence_is_confirmed(registry):
    eng = _engine(registry, _pr(device_id="light.living_room", operation="turn_on", confidence=0.4))
    d = eng.decide("把灯弄一下")
    assert d.verdict == "confirm"
    assert d.stage == "confidence"


def test_dangerous_operation_is_confirmed(registry):
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.95))
    d = eng.decide("开大门锁")
    assert d.verdict == "confirm"
    assert d.stage == "safety"


def test_confidence_gate_precedes_safety_gate(registry):
    # 危险操作但置信度低 -> 先在置信度关被拦
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.4))
    d = eng.decide("好像要开门?")
    assert d.verdict == "confirm"
    assert d.stage == "confidence"


def test_feasibility_precedes_safety(registry):
    # 危险设备 + 不可行(未知参数) -> 先在可行性关被拒
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", params={"speed": 9}, confidence=0.95))
    d = eng.decide("开锁快点")
    assert d.verdict == "reject"
    assert d.stage == "feasibility"


def test_parser_error_fails_closed(registry):
    eng = Engine(RaisingParser(), registry, tau=0.7)
    d = eng.decide("开客厅灯")
    assert d.verdict != "allow"
    assert d.stage == "error"


@pytest.mark.parametrize("bad_conf", [math.nan, math.inf, 1.5])
def test_invalid_confidence_payload_fails_closed(registry, bad_conf):
    payload = {"recognized": True, "device_id": "light.living_room",
               "operation": "turn_on", "confidence": bad_conf}
    eng = Engine(ValidatingParser(payload), registry, tau=0.7)
    d = eng.decide("开客厅灯")
    assert d.verdict != "allow"
    assert d.stage == "error"


def test_recognized_but_missing_device_or_operation_fails_closed(registry):
    eng_no_device = _engine(registry, _pr(device_id=None, operation="turn_on"))
    assert eng_no_device.decide("x").verdict != "allow"
    eng_no_op = _engine(registry, _pr(device_id="light.living_room", operation=None))
    assert eng_no_op.decide("x").verdict != "allow"
