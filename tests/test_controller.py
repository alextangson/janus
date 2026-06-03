from gatekeeper.controller import Controller, Outcome
from gatekeeper.models import Decision


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
