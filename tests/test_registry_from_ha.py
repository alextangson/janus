import json
from pathlib import Path

from gatekeeper.registry import Registry
from gatekeeper.engine import Engine
from gatekeeper.models import ParseResult

from tests._helpers import FakeParser

FIX = Path(__file__).resolve().parent / "fixtures"


def _ha():
    return (
        json.loads((FIX / "ha_states.json").read_text(encoding="utf-8")),
        json.loads((FIX / "ha_services.json").read_text(encoding="utf-8")),
    )


def test_from_ha_builds_registry():
    states, services = _ha()
    reg = Registry.from_ha(states, services)
    assert reg.get("lock.front_door").name == "大门门锁"
    assert reg.is_dangerous("lock.front_door", "unlock") is True
    assert reg.is_dangerous("lock.front_door", "lock") is False
    assert reg.get("sensor.temperature") is None  # filtered


def test_engine_runs_on_ha_registry():
    states, services = _ha()
    reg = Registry.from_ha(states, services)
    # a confident, correct parse of a dangerous op -> confirm via the code danger gate
    parse = ParseResult.model_validate(
        {"recognized": True, "device_id": "lock.front_door", "operation": "unlock",
         "params": {}, "confidence": 0.99})
    decision = Engine(FakeParser(parse), reg, tau=0.7).decide("开锁")
    assert decision.verdict == "confirm"
    assert decision.stage == "safety"
