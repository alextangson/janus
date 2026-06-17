from gatekeeper.controller import Outcome
from gatekeeper.models import Decision
from service.audit import AuditSink


def _sink():
    return AuditSink(":memory:", now=lambda: 1000.0)


def _executed():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    return Outcome(decision=dec, executed=True)


def test_record_decision_roundtrip():
    s = _sink()
    s.record_decision(request_id="r1", conversation_id="c1", caller="cal",
                      phase="turn", utterance="关灯", outcome=_executed(), pending_after=False)
    rows = s.recent(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "executed"
    assert row["ts"] == 1000.0
    assert row["request_id"] == "r1" and row["conversation_id"] == "c1" and row["caller"] == "cal"
    assert row["phase"] == "turn" and row["utterance"] == "关灯"
    assert row["device_id"] == "light.a" and row["operation"] == "turn_off"
    assert row["executed"] == 1 and row["error"] is None


def test_event_derivation_for_pending_and_reject_and_fail():
    s = _sink()
    confirm = Outcome(decision=Decision(verdict="confirm", stage="safety", device_id="lock.door",
                                        operation="unlock", reason="敏感"),
                      executed=False, needs_confirmation=True)
    s.record_decision(request_id="r", conversation_id="c", caller="x", phase="turn",
                      utterance="开锁", outcome=confirm, pending_after=True)
    rej = Outcome(decision=Decision(verdict="reject", stage="feasibility", reason="不支持"),
                  executed=False)
    s.record_decision(request_id="r", conversation_id="c", caller="x", phase="turn",
                      utterance="乱说", outcome=rej, pending_after=False)
    fail = Outcome(decision=Decision(verdict="allow", stage="passed", device_id="light.a",
                                     operation="turn_off"), executed=False, error="HA 500")
    s.record_decision(request_id="r", conversation_id="c", caller="x", phase="reply",
                      utterance="confirm:True", outcome=fail, pending_after=False)
    events = [r["event"] for r in s.recent(limit=10)]
    assert events == ["failed", "rejected", "proposed"]   # recent 新→旧(插入序倒序)


def test_record_lifecycle_superseded():
    s = _sink()
    s.record_lifecycle(event="superseded", request_id="r", conversation_id="c", caller="x",
                       device_id="lock.door", operation="unlock")
    row = s.recent(limit=1)[0]
    assert row["event"] == "superseded" and row["device_id"] == "lock.door"
    assert row["executed"] is None and row["verdict"] is None


def test_recent_orders_newest_first_and_limits():
    s = AuditSink(":memory:", now=lambda: 0.0)
    for i in range(5):
        s.record_lifecycle(event="expired", request_id=f"r{i}", conversation_id="c",
                           caller="x", device_id=None, operation=None)
    rows = s.recent(limit=3)
    assert len(rows) == 3
    assert rows[0]["request_id"] == "r4"     # 最新在前


def test_audit_failure_does_not_raise(tmp_path):
    s = AuditSink(":memory:", now=lambda: 0.0)
    s._conn.close()                          # 故意破坏连接
    s.record_decision(request_id="r", conversation_id="c", caller="x", phase="turn",
                      utterance="x", outcome=_executed(), pending_after=False)  # 不得抛
