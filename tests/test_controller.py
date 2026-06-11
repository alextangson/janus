from gatekeeper.controller import Controller, Outcome
from gatekeeper.models import Decision, Device, OperationSpec
from gatekeeper.registry import Registry


class FakeEngine:
    def __init__(self, decision):
        self._d = decision

    def decide(self, instruction):
        return self._d


class StubHA:
    def __init__(self, raise_exc=None):
        self.calls = []
        self._raise = raise_exc

    def call_service(self, domain, service, entity_id, params=None):
        self.calls.append((domain, service, entity_id, params))
        if self._raise:
            raise self._raise
        return {"ok": True}


def _decision(verdict, **kw):
    base = {"verdict": verdict, "stage": "passed", "device_id": "light.living_room",
            "operation": "turn_on", "params": {}}
    base.update(kw)
    return Decision(**base)


def test_allow_executes():
    ha = StubHA()
    out = Controller(FakeEngine(_decision("allow")), ha).handle("开灯")
    assert isinstance(out, Outcome)
    assert out.executed is True
    assert out.error is None
    assert ha.calls == [("light", "turn_on", "light.living_room", {})]


def test_allow_with_params_executes():
    ha = StubHA()
    d = _decision("allow", device_id="climate.living_room", operation="set_temperature",
                  params={"temperature": 24})
    out = Controller(FakeEngine(d), ha).handle("空调24度")
    assert out.executed is True
    assert ha.calls == [("climate", "set_temperature", "climate.living_room", {"temperature": 24})]


def test_confirm_does_not_execute():
    ha = StubHA()
    out = Controller(FakeEngine(_decision("confirm", stage="safety")), ha).handle("开锁")
    assert out.executed is False
    assert ha.calls == []


def test_reject_does_not_execute():
    ha = StubHA()
    out = Controller(FakeEngine(_decision("reject", stage="feasibility")), ha).handle("空调50度")
    assert out.executed is False
    assert ha.calls == []


def test_execution_error_is_captured_not_raised():
    ha = StubHA(raise_exc=RuntimeError("HA 500"))
    out = Controller(FakeEngine(_decision("allow")), ha).handle("开灯")
    assert out.executed is False
    assert "HA 500" in out.error
    assert out.decision.verdict == "allow"


def test_end_to_end_allow_executes(registry):
    from gatekeeper.engine import Engine
    from gatekeeper.models import ParseResult
    from tests._helpers import FakeParser

    parse = ParseResult.model_validate(
        {"recognized": True, "device_id": "light.living_room", "operation": "turn_on",
         "params": {}, "confidence": 0.99})
    ha = StubHA()
    out = Controller(Engine(FakeParser(parse), registry, tau=0.7), ha).handle("开客厅灯")
    assert out.decision.verdict == "allow"
    assert out.executed is True
    assert ha.calls == [("light", "turn_on", "light.living_room", {})]


def test_confirm_returns_prompt_and_needs_confirmation():
    ha = StubHA()
    d = _decision("confirm", stage="safety", device_id="lock.front_door",
                  operation="unlock", reason="该操作敏感/不可逆,执行前需确认")
    out = Controller(FakeEngine(d), ha).handle("开锁")
    assert out.needs_confirmation is True
    assert out.executed is False
    assert out.prompt and "unlock" in out.prompt and "lock.front_door" in out.prompt
    assert ha.calls == []


def test_confirm_approved_executes():
    ha = StubHA()
    d = _decision("confirm", device_id="lock.front_door", operation="unlock", params={})
    out = Controller(FakeEngine(d), ha).confirm(d, approved=True)
    assert out.executed is True
    assert ha.calls == [("lock", "unlock", "lock.front_door", {})]


def test_confirm_declined_does_not_execute():
    ha = StubHA()
    d = _decision("confirm", device_id="lock.front_door", operation="unlock")
    out = Controller(FakeEngine(d), ha).confirm(d, approved=False)
    assert out.executed is False
    assert ha.calls == []


def test_confirm_approved_execution_error_is_captured():
    ha = StubHA(raise_exc=RuntimeError("HA down"))
    d = _decision("confirm", device_id="lock.front_door", operation="unlock")
    out = Controller(FakeEngine(d), ha).confirm(d, approved=True)
    assert out.executed is False
    assert "HA down" in out.error


def test_end_to_end_confirm_then_approve(registry):
    from gatekeeper.engine import Engine
    from gatekeeper.models import ParseResult
    from tests._helpers import FakeParser

    parse = ParseResult.model_validate(
        {"recognized": True, "device_id": "lock.front_door", "operation": "unlock",
         "params": {}, "confidence": 0.99})
    ha = StubHA()
    ctrl = Controller(Engine(FakeParser(parse), registry, tau=0.7), ha)
    out = ctrl.handle("把大门打开")
    assert out.needs_confirmation is True and out.executed is False and ha.calls == []
    out2 = ctrl.confirm(out.decision, approved=True)
    assert out2.executed is True
    assert ha.calls == [("lock", "unlock", "lock.front_door", {})]


# ---------------------------------------------------------------------------
# Task 4: choices + choose()
# ---------------------------------------------------------------------------

class FakeResolveEngine(FakeEngine):
    """带 decide_resolved 与 registry 的假引擎,供消歧链路测试。"""

    def __init__(self, decision, resolved=None, registry=None):
        super().__init__(decision)
        self._resolved = resolved
        self.registry = registry
        self.resolved_calls = []

    def decide_resolved(self, device_id: str, operation: str | None,
                        params: dict | None = None) -> Decision:
        self.resolved_calls.append((device_id, operation, params))
        return self._resolved


def _amb_decision(**kw):
    base = {"verdict": "confirm", "stage": "ambiguous", "operation": "turn_off",
            "params": {}, "candidates": ["light.a", "light.b"], "reason": "多台设备匹配"}
    base.update(kw)
    return Decision(**base)


def _mini_registry():
    op = {"turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=op),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=op),
    })


def test_ambiguous_outcome_carries_choices_and_numbered_prompt():
    eng = FakeResolveEngine(_amb_decision(), registry=_mini_registry())
    out = Controller(eng, StubHA()).handle("关掉卧室的灯")
    assert out.needs_confirmation is True
    assert out.choices == ["light.a", "light.b"]
    assert "哪一个" in out.prompt
    assert "主灯" in out.prompt and "氛围灯" in out.prompt


def test_plain_confirm_has_no_choices():
    out = Controller(FakeEngine(_decision("confirm", stage="safety")), StubHA()).handle("开锁")
    assert out.choices is None


def test_choose_executes_allowed_choice():
    ha = StubHA()
    resolved = Decision(verdict="allow", stage="passed", device_id="light.b",
                        operation="turn_off", params={})
    eng = FakeResolveEngine(_amb_decision(), resolved=resolved, registry=_mini_registry())
    out = Controller(eng, ha).choose(_amb_decision(), "light.b")
    assert out.executed is True
    assert ha.calls == [("light", "turn_off", "light.b", {})]
    assert eng.resolved_calls == [("light.b", "turn_off", {})]


def test_choose_outside_candidates_refused():
    ha = StubHA()
    eng = FakeResolveEngine(_amb_decision(), registry=_mini_registry())
    out = Controller(eng, ha).choose(_amb_decision(), "lock.door")
    assert out.executed is False
    assert out.error is not None
    assert ha.calls == []
    assert eng.resolved_calls == []


def test_choose_dangerous_chains_to_confirm():
    ha = StubHA()
    resolved = Decision(verdict="confirm", stage="safety", device_id="lock.a",
                        operation="unlock", params={}, reason="该操作敏感/不可逆,执行前需确认")
    amb = _amb_decision(operation="unlock", candidates=["lock.a", "lock.b"])
    eng = FakeResolveEngine(amb, resolved=resolved)
    ctl = Controller(eng, ha)
    out = ctl.choose(amb, "lock.a")
    assert out.executed is False
    assert out.needs_confirmation is True
    assert ha.calls == []
    # 链式:复用现有 confirm() 完成最终执行
    out2 = ctl.confirm(resolved, approved=True)
    assert out2.executed is True


def test_confirm_refuses_ambiguous_decision():
    ha = StubHA()
    eng = FakeResolveEngine(_amb_decision(), registry=_mini_registry())
    out = Controller(eng, ha).confirm(_amb_decision(device_id="light.a"), approved=True)
    assert out.executed is False
    assert out.error is not None
    assert ha.calls == []


def test_inferred_prompt_shows_proposal_and_params():
    d = _decision("confirm", stage="inferred", device_id="climate.ac",
                  operation="set_temperature", params={"temperature": 26},
                  reason="室外 14°C 偏凉,建议把空调调到 26°C")
    out = Controller(FakeEngine(d), StubHA()).handle("有点冷")
    assert out.needs_confirmation is True
    assert out.prompt.startswith("💡 室外 14°C 偏凉")
    assert "set_temperature → climate.ac" in out.prompt
    assert "'temperature': 26" in out.prompt
