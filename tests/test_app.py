import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from tests.test_engine_factory import FakeHA      # 复用最小假 HAClient


def _client(api_token="s3cret"):
    app = create_app(ha_client=FakeHA(), llm_client=object(),
                     backend="claude", model="m", tau=0.7, api_token=api_token,
                     request_timeout=5.0)
    return TestClient(app)


def _auth(t="s3cret"):
    return {"Authorization": f"Bearer {t}"}


def test_health_open():
    r = _client().get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_devices_requires_bearer():
    c = _client()
    assert c.get("/v1/devices").status_code == 401
    assert c.get("/v1/devices", headers=_auth("wrong")).status_code == 401


def test_devices_lists_with_auth():
    r = _client().get("/v1/devices", headers=_auth())
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()["devices"]]
    assert "light.a" in ids


from gatekeeper.controller import Controller, Outcome
from gatekeeper.models import Decision, Device, OperationSpec
from gatekeeper.registry import Registry
from tests.test_session import FakeEngine, StubHA


def _reg_for_turn():
    return Registry({"light.a": Device(name="主灯", type="light", area="卧室",
                                       operations={"turn_off": OperationSpec()})})


def _exec_app(decision, resolved=None):
    ha = StubHA()
    ctrl = Controller(FakeEngine(decision, resolved=resolved, registry=_reg_for_turn()), ha)
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=lambda deadline=None: ctrl)
    return TestClient(app), ha


def test_turn_allow_executes_returns_dto():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, ha = _exec_app(dec)
    r = c.post("/v1/turn", headers=_auth(), json={"utterance": "关灯", "idempotency_key": "k1"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "executed" and body["conversation_id"]
    assert ha.calls == [("light", "turn_off", "light.a", {})]


def test_turn_requires_auth():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, _ = _exec_app(dec)
    assert c.post("/v1/turn", json={"utterance": "关灯"}).status_code == 401


def test_turn_idempotent_replay_no_double_execute():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, ha = _exec_app(dec)
    cid = c.post("/v1/turn", headers=_auth(),
                 json={"utterance": "关灯", "idempotency_key": "k1"}).json()["conversation_id"]
    c.post("/v1/turn", headers=_auth(),
           json={"utterance": "关灯", "idempotency_key": "k1", "conversation_id": cid})
    assert len(ha.calls) == 1


def test_turn_confirm_issues_pending_id():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha = _exec_app(dec)
    body = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    assert body["status"] == "needs_confirmation"
    assert body["pending_id"] and body["expires_at"]
    assert ha.calls == []


def test_turn_timeout_returns_error_dto_no_ha_call():
    # 安全核心:超时绝不"报成功",且绝不打 HA(执行死线 + wait_for 取消的集成)
    import asyncio

    class HangingEngine(FakeEngine):
        def decide(self, instruction):
            raise asyncio.TimeoutError()      # 模拟 wait_for 超时被取消

    ha = StubHA()
    ctrl = Controller(HangingEngine(registry=_reg_for_turn()), ha)
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=lambda deadline=None: ctrl)
    body = TestClient(app).post("/v1/turn", headers=_auth(),
                                json={"utterance": "关灯"}).json()
    assert body["status"] == "error"
    assert body["pending_id"] is None
    assert ha.calls == []                     # 超时后绝不真打 HA


def test_turn_supersede_burns_old_pending_id():
    # 新指令覆盖旧 pending:第二轮(同会话)烧掉首轮的 pending_id
    dec_confirm = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                           operation="unlock", reason="敏感")
    dec_allow = Decision(verdict="allow", stage="passed", device_id="light.a",
                         operation="turn_off")
    ha = StubHA()
    calls = [0]

    def factory(deadline=None):
        calls[0] += 1
        d = dec_confirm if calls[0] == 1 else dec_allow
        return Controller(FakeEngine(d, registry=_reg_for_turn()), ha)

    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=factory)
    c = TestClient(app)
    r1 = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    cid, old_pid = r1["conversation_id"], r1["pending_id"]
    assert old_pid is not None
    r2 = c.post("/v1/turn", headers=_auth(),
                json={"utterance": "关灯", "conversation_id": cid}).json()
    assert r2["status"] == "executed"
    assert r2["pending_id"] is None           # 旧 pending 被烧,未发新的


def test_reply_confirm_executes_after_pending():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha = _exec_app(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    cid, pid = turn["conversation_id"], turn["pending_id"]
    r = c.post(f"/v1/pending/{pid}/reply", headers=_auth(),
               json={"conversation_id": cid, "kind": "confirm", "value": True})
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert ha.calls == [("lock", "unlock", "lock.door", {})]


def test_reply_one_time_pending_id():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha = _exec_app(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    cid, pid = turn["conversation_id"], turn["pending_id"]
    body = {"conversation_id": cid, "kind": "confirm", "value": True}
    c.post(f"/v1/pending/{pid}/reply", headers=_auth(), json=body)
    again = c.post(f"/v1/pending/{pid}/reply", headers=_auth(), json=body)
    assert again.status_code == 409
    assert len(ha.calls) == 1


def test_reply_wrong_pending_id_rejected():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, _ = _exec_app(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    r = c.post("/v1/pending/bogus/reply", headers=_auth(),
               json={"conversation_id": turn["conversation_id"], "kind": "confirm", "value": True})
    assert r.status_code == 409


def test_reply_requires_auth():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, _ = _exec_app(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    r = c.post(f"/v1/pending/{turn['pending_id']}/reply",
               json={"conversation_id": turn["conversation_id"], "kind": "confirm", "value": True})
    assert r.status_code == 401


def test_reply_wrong_id_preserves_pending_then_correct_id_works():
    # 端点层防猜测:错误 pending_id → 409 且不执行、不烧真 pending;随后真 id 仍可用
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha = _exec_app(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    cid, pid = turn["conversation_id"], turn["pending_id"]
    bad = c.post("/v1/pending/bogus/reply", headers=_auth(),
                 json={"conversation_id": cid, "kind": "confirm", "value": True})
    assert bad.status_code == 409
    assert ha.calls == []                       # 错误猜测绝不执行
    good = c.post(f"/v1/pending/{pid}/reply", headers=_auth(),
                  json={"conversation_id": cid, "kind": "confirm", "value": True})
    assert good.json()["status"] == "executed"  # 真 pending 仍可用
    assert ha.calls == [("lock", "unlock", "lock.door", {})]


def test_confirm_expires_at_is_wallclock_epoch():
    # expires_at 必须是墙钟 epoch 秒(客户端能算倒计时),不是 monotonic
    import time as _t

    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, _ = _exec_app(dec)
    before = _t.time()
    body = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    exp = body["expires_at"]
    assert exp is not None
    assert before <= exp <= before + 200        # 默认 TTL 120s;monotonic(开机秒)会落在此区间外


from service.audit import AuditSink


def _exec_app_audited(decision, resolved=None):
    ha = StubHA()
    ctrl = Controller(FakeEngine(decision, resolved=resolved, registry=_reg_for_turn()), ha)
    audit = AuditSink(":memory:")
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=lambda deadline=None: ctrl, audit=audit)
    return TestClient(app), ha, audit


def test_turn_emits_audit_record():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, ha, audit = _exec_app_audited(dec)
    c.post("/v1/turn", headers=_auth(), json={"utterance": "关灯"})
    rows = audit.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["event"] == "executed" and rows[0]["utterance"] == "关灯"
    assert rows[0]["phase"] == "turn" and rows[0]["caller"]


def test_audit_endpoint_requires_auth_and_returns_records():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, ha, audit = _exec_app_audited(dec)
    c.post("/v1/turn", headers=_auth(), json={"utterance": "关灯"})
    assert c.get("/v1/audit").status_code == 401
    r = c.get("/v1/audit?limit=10", headers=_auth())
    assert r.status_code == 200
    recs = r.json()["records"]
    assert recs and recs[0]["event"] == "executed"
    assert recs[0]["utterance"] == "关灯"


def test_reply_emits_records():
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha, audit = _exec_app_audited(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    c.post(f"/v1/pending/{turn['pending_id']}/reply", headers=_auth(),
           json={"conversation_id": turn["conversation_id"], "kind": "confirm", "value": True})
    events = [r["event"] for r in audit.recent(limit=10)]
    assert "proposed" in events and "executed" in events


def test_supersede_emits_superseded_event():
    dec_confirm = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                           operation="unlock", reason="敏感")
    dec_allow = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    ha = StubHA()
    calls = [0]

    def factory(deadline=None):
        calls[0] += 1
        d = dec_confirm if calls[0] == 1 else dec_allow
        return Controller(FakeEngine(d, registry=_reg_for_turn()), ha)

    audit = AuditSink(":memory:")
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude", model="m",
                     tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=factory, audit=audit)
    c = TestClient(app)
    cid = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()["conversation_id"]
    c.post("/v1/turn", headers=_auth(), json={"utterance": "关灯", "conversation_id": cid})
    events = [r["event"] for r in audit.recent(limit=10)]
    assert "superseded" in events


def test_audit_none_is_noop():
    dec = Decision(verdict="allow", stage="passed", device_id="light.a", operation="turn_off")
    c, ha = _exec_app(dec)               # 老助手,无 audit
    r = c.post("/v1/turn", headers=_auth(), json={"utterance": "关灯"})
    assert r.json()["status"] == "executed"


def test_turn_timeout_emits_failed_audit():
    # 事故可诊断:超时/崩溃的 turn 也要留审计(event=failed)
    import asyncio

    class HangingEngine(FakeEngine):
        def decide(self, instruction):
            raise asyncio.TimeoutError()

    ha = StubHA()
    ctrl = Controller(HangingEngine(registry=_reg_for_turn()), ha)
    audit = AuditSink(":memory:")
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude", model="m",
                     tau=0.7, api_token="s3cret", request_timeout=5.0,
                     controller_factory=lambda deadline=None: ctrl, audit=audit)
    TestClient(app).post("/v1/turn", headers=_auth(), json={"utterance": "关灯"})
    rows = audit.recent(limit=10)
    assert len(rows) == 1 and rows[0]["event"] == "failed"


def test_reply_deny_audits_cancelled():
    # 否决一个确认:不执行,审计成 cancelled
    dec = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                   operation="unlock", reason="敏感")
    c, ha, audit = _exec_app_audited(dec)
    turn = c.post("/v1/turn", headers=_auth(), json={"utterance": "开锁"}).json()
    c.post(f"/v1/pending/{turn['pending_id']}/reply", headers=_auth(),
           json={"conversation_id": turn["conversation_id"], "kind": "confirm", "value": False})
    events = [r["event"] for r in audit.recent(limit=10)]
    assert "cancelled" in events
    assert ha.calls == []                # 否决不执行
