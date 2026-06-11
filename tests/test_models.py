import math

import pytest
from pydantic import ValidationError

from gatekeeper.models import (
    Device,
    OperationSpec,
    ParamSpec,
    ParseResult,
    Decision,
)


def test_device_validates_from_dict():
    dev = Device.model_validate(
        {
            "name": "客厅空调",
            "type": "climate",
            "area": "客厅",
            "operations": {
                "set_temperature": {
                    "params": {
                        "temperature": {"type": "int", "min": 16, "max": 30, "unit": "°C", "required": True}
                    },
                    "dangerous": False,
                }
            },
        }
    )
    assert dev.operations["set_temperature"].params["temperature"].max == 30
    assert dev.operations["set_temperature"].dangerous is False


def test_parseresult_requires_recognized():
    with pytest.raises(ValidationError):
        ParseResult.model_validate({"device_id": "light.living_room"})


def test_parseresult_defaults_and_types():
    pr = ParseResult.model_validate(
        {"recognized": True, "device_id": "climate.living_room",
         "operation": "set_temperature", "params": {"temperature": 50}, "confidence": 0.93}
    )
    assert pr.params["temperature"] == 50
    assert pr.notes == ""


def test_decision_requires_verdict_and_stage():
    d = Decision(verdict="allow", stage="passed")
    assert d.verdict == "allow"
    assert d.params == {}
    with pytest.raises(ValidationError):
        Decision(verdict="maybe", stage="passed")  # not a valid Verdict


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -0.1, 1.5])
def test_parseresult_rejects_invalid_confidence(bad):
    with pytest.raises(ValidationError):
        ParseResult.model_validate(
            {"recognized": True, "device_id": "light.living_room",
             "operation": "turn_on", "confidence": bad}
        )


def test_device_metadata_fields_default_none():
    from gatekeeper.models import Device
    d = Device(name="x", type="light", area="")
    assert d.entity_category is None
    assert d.device_id is None


def test_device_metadata_fields_set():
    from gatekeeper.models import Device
    d = Device(name="x", type="light", area="Living Room",
               entity_category="config", device_id="abc123")
    assert d.entity_category == "config"
    assert d.device_id == "abc123"


def test_parse_result_candidates_default_empty():
    from gatekeeper.models import ParseResult
    pr = ParseResult(recognized=True)
    assert pr.candidates == []


def test_decision_accepts_ambiguous_stage_and_candidates():
    from gatekeeper.models import Decision
    d = Decision(verdict="confirm", stage="ambiguous", candidates=["light.a", "light.b"])
    assert d.candidates == ["light.a", "light.b"]


def test_parse_result_inferred_defaults_false():
    from gatekeeper.models import ParseResult
    assert ParseResult(recognized=True).inferred is False


def test_decision_accepts_inferred_stage():
    from gatekeeper.models import Decision
    d = Decision(verdict="confirm", stage="inferred", reason="室外偏凉,建议调高空调")
    assert d.stage == "inferred"
