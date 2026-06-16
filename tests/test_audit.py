from gatekeeper.audit import DecisionRecord, build_record, summary
from gatekeeper.controller import Outcome
from gatekeeper.models import Decision


def _outcome(verdict, executed=False, error=None, **dkw):
    base = {"verdict": verdict, "stage": "passed", "device_id": "light.a",
            "operation": "turn_on", "params": {}}
    base.update(dkw)
    return Outcome(decision=Decision(**base), executed=executed, error=error)


def test_build_record_maps_fields():
    out = _outcome("allow", executed=True, stage="passed", device_id="climate.ac",
                   operation="set_temperature", params={"temperature": 26}, confidence=0.9)
    rec = build_record("把空调设成26度", out, pending_after=False)
    assert rec.utterance == "把空调设成26度"
    assert rec.verdict == "allow" and rec.stage == "passed"
    assert rec.device_id == "climate.ac" and rec.operation == "set_temperature"
    assert rec.params == {"temperature": 26}
    assert rec.executed is True and rec.error is None
    assert rec.pending_after is False


def test_build_record_carries_pending_and_error():
    out = _outcome("confirm", stage="safety", error=None)
    rec = build_record("开门锁", out, pending_after=True)
    assert rec.verdict == "confirm" and rec.stage == "safety"
    assert rec.executed is False and rec.pending_after is True


def test_summary_is_redacted_no_utterance_no_params():
    out = _outcome("allow", executed=True, device_id="light.bedroom",
                   operation="turn_on", params={"brightness_pct": 80})
    rec = build_record("打开主卧的灯调到80", out, pending_after=False)
    s = summary(rec)
    assert "allow/passed" in s and "light.bedroom" in s and "✓" in s
    assert "主卧" not in s          # 不含 raw utterance
    assert "80" not in s            # 不含 params 值


def test_summary_marks_failure_and_reject():
    err = build_record("开灯", _outcome("allow", executed=False, error="HA 500"), False)
    assert "✗" in summary(err)
    rej = build_record("乱说", _outcome("reject", stage="parse", reason="没识别"), False)
    assert "reject/parse" in summary(rej) and "·" in summary(rej)
