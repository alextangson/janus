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
