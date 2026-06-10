import math

import pytest

from gatekeeper.engine import Engine
from gatekeeper.models import Device, OperationSpec, ParseResult
from gatekeeper.registry import Registry

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


def _amb_registry():
    def on_off():
        return {"turn_on": OperationSpec(), "turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=on_off()),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=on_off()),
        "lock.door": Device(name="门锁", type="lock", area="门厅",
                            operations={"unlock": OperationSpec(dangerous=True),
                                        "lock": OperationSpec()}),
    })


def test_two_valid_candidates_ask_which_one():
    eng = Engine(FakeParser(_pr(operation="turn_off",
                                candidates=["light.a", "light.b"], confidence=0.6)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关掉卧室的灯")
    assert (d.verdict, d.stage) == ("confirm", "ambiguous")  # 置信度0.6<τ 也不落 confidence:歧义优先
    assert d.candidates == ["light.a", "light.b"]


def test_hallucinated_candidates_filtered_then_single_downgrades():
    eng = Engine(FakeParser(_pr(operation="turn_off",
                                candidates=["light.ghost", "light.a", "lock.door"])),
                 _amb_registry(), tau=0.7)
    # ghost 不存在、lock.door 不支持 turn_off → 只剩 light.a → 降级普通解析
    d = eng.decide("关灯")
    assert (d.verdict, d.stage, d.device_id) == ("allow", "passed", "light.a")


def test_single_candidate_still_passes_safety_gate():
    eng = Engine(FakeParser(_pr(operation="unlock", candidates=["lock.door"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("开锁")
    assert (d.verdict, d.stage, d.device_id) == ("confirm", "safety", "lock.door")


def test_single_candidate_still_passes_tau_gate():
    eng = Engine(FakeParser(_pr(operation="turn_off", candidates=["light.a"], confidence=0.4)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert (d.verdict, d.stage) == ("confirm", "confidence")


def test_all_candidates_invalid_rejects_at_parse():
    eng = Engine(FakeParser(_pr(operation="turn_off", candidates=["light.ghost"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert (d.verdict, d.stage) == ("reject", "parse")


def test_ambiguity_wins_over_filled_device_id():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_off",
                                candidates=["light.a", "light.b"])),
                 _amb_registry(), tau=0.7)
    assert eng.decide("关灯").stage == "ambiguous"


def _resolved_engine():
    return Engine(FakeParser(_pr()), _amb_registry(), tau=0.7)


def test_decide_resolved_allows_safe_op():
    d = _resolved_engine().decide_resolved("light.a", "turn_off", {})
    assert (d.verdict, d.stage, d.device_id) == ("allow", "passed", "light.a")


def test_decide_resolved_keeps_safety_gate():
    d = _resolved_engine().decide_resolved("lock.door", "unlock", {})
    assert (d.verdict, d.stage) == ("confirm", "safety")


def test_decide_resolved_rejects_infeasible():
    d = _resolved_engine().decide_resolved("light.a", "set_temperature", {"temperature": 24})
    assert (d.verdict, d.stage) == ("reject", "feasibility")


def test_ambiguous_decision_has_no_device_id():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_off",
                                candidates=["light.a", "light.b"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert d.stage == "ambiguous"
    assert d.device_id is None  # 歧义未消解,不得携带模型偏好的 device_id


def test_decide_resolved_skips_tau_gate():
    # τ 高到 decide() 必拦,decide_resolved 仍放行:用户的明确选择即满置信
    eng = Engine(FakeParser(_pr()), _amb_registry(), tau=0.999)
    d = eng.decide_resolved("light.a", "turn_off", {})
    assert (d.verdict, d.stage) == ("allow", "passed")
