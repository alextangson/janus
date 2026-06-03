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
