import time

from fastapi.testclient import TestClient

from gatekeeper.models import Decision
from service.app import create_app
from service.schedule_store import ScheduleEntry, ScheduleStore
from tests.test_engine_factory import FakeHA

TOKEN = "s3cret"


def _auth(t=TOKEN):
    return {"Authorization": f"Bearer {t}"}


class _FakeEngine:
    """仅 schedules 端点用到的 decide_resolved，返回预设 Decision。"""

    def __init__(self, decision):
        self._d = decision

    def decide_resolved(self, device_id, operation, params=None):
        return self._d


class _FakeController:
    def __init__(self, decision):
        self.engine = _FakeEngine(decision)


def _allow(reason=""):
    return Decision(verdict="allow", stage="passed", device_id="light.a",
                    operation="turn_off", reason=reason)


def _confirm(reason="危险操作需确认"):
    return Decision(verdict="confirm", stage="safety", dangerous=True,
                    device_id="lock.door", operation="unlock", reason=reason)


def _reject(reason="无法执行"):
    return Decision(verdict="reject", stage="feasibility", device_id="light.a",
                    operation="turn_off", reason=reason)


def _app(decision, store=None):
    store = store if store is not None else ScheduleStore(path=None)
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=lambda deadline=None: _FakeController(decision),
                     schedule_store=store)
    return TestClient(app), store


def _once_body(at=None):
    return {"device_id": "light.a", "operation": "turn_off", "params": {},
            "kind": "once", "at": at if at is not None else time.time() + 3600}


def _recurring_body(minute_of_day=480, days=None):
    return {"device_id": "light.a", "operation": "turn_off", "params": {},
            "kind": "recurring", "minute_of_day": minute_of_day,
            "days": days if days is not None else [0, 1, 2]}


# ---- 1. POST once allow ----
def test_post_once_allow_creates(_=None):
    c, store = _app(_allow())
    r = c.post("/v1/schedules", headers=_auth(), json=_once_body())
    assert r.status_code in (200, 201)
    body = r.json()
    assert "id" in body and body["next_fire_at"] is not None
    assert len(store.list()) == 1
    assert store.get(body["id"]) is not None


# ---- 2. POST confirm (dangerous) → 422, detail=reason, nothing stored ----
def test_post_confirm_rejected_422():
    c, store = _app(_confirm("门锁危险:需当面确认"))
    r = c.post("/v1/schedules", headers=_auth(), json=_once_body())
    assert r.status_code == 422
    assert r.json()["detail"] == "门锁危险:需当面确认"
    assert store.list() == []


# ---- 3. POST reject (infeasible) → 422 ----
def test_post_reject_422():
    c, store = _app(_reject("缺少参数"))
    r = c.post("/v1/schedules", headers=_auth(), json=_once_body())
    assert r.status_code == 422
    assert r.json()["detail"] == "缺少参数"
    assert store.list() == []


# ---- 4. POST once missing `at` → 422 (shape) ----
def test_post_once_missing_at_422():
    c, store = _app(_allow())
    body = {"device_id": "light.a", "operation": "turn_off", "params": {},
            "kind": "once"}
    r = c.post("/v1/schedules", headers=_auth(), json=body)
    assert r.status_code == 422
    assert store.list() == []


# ---- 5. recurring shape validation ----
def test_post_recurring_missing_days_422():
    c, _ = _app(_allow())
    r = c.post("/v1/schedules", headers=_auth(), json=_recurring_body(days=[]))
    assert r.status_code == 422


def test_post_recurring_no_days_key_422():
    c, _ = _app(_allow())
    body = {"device_id": "light.a", "operation": "turn_off", "params": {},
            "kind": "recurring", "minute_of_day": 480}
    r = c.post("/v1/schedules", headers=_auth(), json=body)
    assert r.status_code == 422


def test_post_recurring_minute_out_of_range_422():
    c, _ = _app(_allow())
    r = c.post("/v1/schedules", headers=_auth(), json=_recurring_body(minute_of_day=1440))
    assert r.status_code == 422
    r2 = c.post("/v1/schedules", headers=_auth(), json=_recurring_body(minute_of_day=-1))
    assert r2.status_code == 422


def test_post_recurring_bad_day_value_422():
    c, _ = _app(_allow())
    r = c.post("/v1/schedules", headers=_auth(), json=_recurring_body(days=[0, 7]))
    assert r.status_code == 422


def test_post_recurring_allow_creates():
    c, store = _app(_allow())
    r = c.post("/v1/schedules", headers=_auth(), json=_recurring_body())
    assert r.status_code in (200, 201)
    assert len(store.list()) == 1


# ---- 6. GET lists ----
def test_get_lists_with_status_fields():
    c, store = _app(_allow())
    c.post("/v1/schedules", headers=_auth(), json=_once_body())
    r = c.get("/v1/schedules", headers=_auth())
    assert r.status_code == 200
    schedules = r.json()["schedules"]
    assert len(schedules) == 1
    e = schedules[0]
    for field in ("id", "device_id", "operation", "kind", "enabled",
                  "next_fire_at", "created_at", "last_outcome"):
        assert field in e


# ---- 7. DELETE ----
def test_delete_existing_and_missing():
    c, store = _app(_allow())
    sid = c.post("/v1/schedules", headers=_auth(), json=_once_body()).json()["id"]
    r = c.delete(f"/v1/schedules/{sid}", headers=_auth())
    assert r.status_code in (200, 204)
    assert store.get(sid) is None
    r2 = c.delete("/v1/schedules/nope", headers=_auth())
    assert r2.status_code == 404


# ---- 8. PATCH ----
def test_patch_disable():
    c, store = _app(_allow())
    sid = c.post("/v1/schedules", headers=_auth(), json=_once_body()).json()["id"]
    r = c.patch(f"/v1/schedules/{sid}", headers=_auth(), json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert store.get(sid).enabled is False


def test_patch_missing_404():
    c, _ = _app(_allow())
    r = c.patch("/v1/schedules/nope", headers=_auth(), json={"enabled": False})
    assert r.status_code == 404


def test_patch_reenable_recurring_recomputes_next_fire():
    store = ScheduleStore(path=None)
    entry = ScheduleEntry(
        id="rec1", device_id="light.a", operation="turn_off", params={},
        kind="recurring", at=None, minute_of_day=480, days=[0, 1, 2, 3, 4, 5, 6],
        tz="Asia/Shanghai", enabled=False, next_fire_at=None, created_at=time.time())
    store.add(entry)
    c, _ = _app(_allow(), store=store)
    r = c.patch("/v1/schedules/rec1", headers=_auth(), json={"enabled": True})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["next_fire_at"] is not None


# ---- 9. limit → 429 ----
def test_post_beyond_limit_429():
    store = ScheduleStore(path=None, max_schedules=1)
    c, _ = _app(_allow(), store=store)
    r1 = c.post("/v1/schedules", headers=_auth(), json=_once_body())
    assert r1.status_code in (200, 201)
    r2 = c.post("/v1/schedules", headers=_auth(), json=_once_body())
    assert r2.status_code == 429


# ---- 10. auth ----
def test_no_auth_401():
    c, _ = _app(_allow())
    assert c.get("/v1/schedules").status_code == 401
    assert c.post("/v1/schedules", json=_once_body()).status_code == 401
    assert c.delete("/v1/schedules/x").status_code == 401
    assert c.patch("/v1/schedules/x", json={"enabled": False}).status_code == 401


def test_bad_auth_401():
    c, _ = _app(_allow())
    assert c.get("/v1/schedules", headers=_auth("wrong")).status_code == 401


# ---- 11. store None → 503 ----
def test_store_none_returns_503():
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=lambda deadline=None: _FakeController(_allow()),
                     schedule_store=None)
    c = TestClient(app)
    assert c.get("/v1/schedules", headers=_auth()).status_code == 503
    assert c.post("/v1/schedules", headers=_auth(), json=_once_body()).status_code == 503


# ---- 12. CORS preflight for DELETE/PATCH ----
def test_cors_preflight_allows_delete():
    c, _ = _app(_allow())
    r = c.options("/v1/schedules", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "DELETE",
    })
    assert r.status_code == 200
    assert "DELETE" in r.headers.get("access-control-allow-methods", "")


def test_cors_preflight_allows_patch():
    c, _ = _app(_allow())
    r = c.options("/v1/schedules", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "PATCH",
    })
    assert r.status_code == 200
    assert "PATCH" in r.headers.get("access-control-allow-methods", "")
