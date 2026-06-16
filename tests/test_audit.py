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


from gatekeeper.audit import display_status


def _row(**kw):
    base = {"verdict": "allow", "executed": False, "error": None, "pending_after": False}
    base.update(kw)
    return base


def test_display_status_all_branches():
    assert display_status(_row(executed=True)) == "executed"
    assert display_status(_row(error="HA 500")) == "failed"
    assert display_status(_row(error="x", executed=True)) == "failed"   # error 优先
    assert display_status(_row(verdict="reject")) == "rejected"
    assert display_status(_row(verdict="answer")) == "answered"
    assert display_status(_row(verdict="confirm", pending_after=True)) == "pending"
    assert display_status(_row(verdict="ask", pending_after=True)) == "pending"
    assert display_status(_row(verdict="confirm", pending_after=False)) == "cancelled"


def test_summary_omits_reason_on_query_and_inferred():
    # query 的 reason 是渲染出的实时设备状态(含名字/开关),绝不能进 INFO 日志
    q = build_record("前门锁着吗", _outcome("answer", stage="query", device_id="lock.front",
                                            operation=None, reason="前门锁:已开"), False)
    s = summary(q)
    assert "已开" not in s and "前门锁" not in s   # 实时状态不泄露
    assert "answer/query" in s                       # 但 verdict/stage 仍在
    # inferred 的 reason 是模型自由文本(notes),同样不进 INFO
    inf = build_record("有点冷", _outcome("confirm", stage="inferred", device_id="climate.ac",
                                          operation="set_temperature",
                                          reason="室外14°C偏凉,建议调到26度"), True)
    assert "偏凉" not in summary(inf) and "26" not in summary(inf)
