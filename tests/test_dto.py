from gatekeeper.controller import Outcome
from gatekeeper.models import Decision, Device, OperationSpec
from gatekeeper.registry import Registry
from service.dto import outcome_to_dto


def _reg():
    op = {"turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=op),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=op),
    })


def _dto(outcome, **kw):
    base = dict(conversation_id="c", pending_id=None, expires_at=None,
                request_id="req-1", registry=_reg())
    base.update(kw)
    return outcome_to_dto(outcome, **base)


def test_executed_outcome():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    d = _dto(Outcome(decision=dec, executed=True))
    assert d["status"] == "executed"
    assert d["device"] == "light.a" and d["operation"] == "turn_off"
    assert d["result"] == {"executed": True, "error": None}
    assert d["pending_id"] is None
    assert d["request_id"] == "req-1"


def test_needs_confirmation_with_pending_id():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    d = _dto(Outcome(decision=dec, executed=False, needs_confirmation=True, prompt="确认?"),
             pending_id="pid-1", expires_at=999.0)
    assert d["status"] == "needs_confirmation"
    assert d["pending_id"] == "pid-1" and d["expires_at"] == 999.0
    assert d["message"] == "确认?"


def test_needs_choice_builds_labeled_choices():
    dec = Decision(verdict="confirm", stage="ambiguous", operation="turn_off",
                   candidates=["light.a", "light.b"], reason="多台匹配")
    d = _dto(Outcome(decision=dec, executed=False, needs_confirmation=True,
                     prompt="哪一个?", choices=["light.a", "light.b"]),
             pending_id="pid-2")
    assert d["status"] == "needs_choice"
    assert d["choices"] == [{"id": "light.a", "label": "主灯"},
                            {"id": "light.b", "label": "氛围灯"}]


def test_needs_param():
    dec = Decision(verdict="ask", stage="param", device_id="climate.ac",
                   operation="set_temperature", missing_param="temperature")
    d = _dto(Outcome(decision=dec, executed=False, needs_param=True, prompt="设成多少?"),
             pending_id="pid-3")
    assert d["status"] == "needs_param"
    assert d["message"] == "设成多少?"


def test_answer_and_reject_and_error():
    ans = Decision(verdict="answer", stage="query", reason="客厅 24°C")
    assert _dto(Outcome(decision=ans, executed=False))["status"] == "answer"
    rej = Decision(verdict="reject", stage="feasibility", reason="不支持")
    assert _dto(Outcome(decision=rej, executed=False))["status"] == "rejected"
    err = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    d = _dto(Outcome(decision=err, executed=False, error="HA 500"))
    assert d["status"] == "error" and d["result"]["error"] == "HA 500"
