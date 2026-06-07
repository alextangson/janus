import json
from pathlib import Path

from gatekeeper.registry import Registry
from gatekeeper.engine import Engine
from gatekeeper.models import ParseResult
from gatekeeper.ha_mapping import build_registry_snapshot

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


def test_from_ha_passes_snapshot_through():
    states, services = _ha()
    snap = build_registry_snapshot(
        [{"entity_id": "lock.front_door", "device_id": "lockdev",
          "area_id": "a1", "entity_category": None}],
        [{"id": "lockdev", "area_id": "a1"}],
        [{"area_id": "a1", "name": "门厅"}],
    )
    reg = Registry.from_ha(states, services, snapshot=snap)
    d = reg.get("lock.front_door")
    assert d.device_id == "lockdev"
    assert d.area == "门厅"


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
