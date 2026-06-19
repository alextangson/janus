"""Task 5:/v1/turn 见到 outcome.schedule → 建定时 + 返回 "scheduled" 确认。

全 fake,绝不 import anthropic。fake controller 的 .handle 直接产出携带
ScheduleIntent 的 Outcome;用真 ScheduleStore(path=None) 内存态验证建任务。
"""
from gatekeeper.controller import Outcome
from gatekeeper.models import Decision, Device, ScheduleIntent
from gatekeeper.registry import Registry
from service.app import create_app
from service.schedule_store import ScheduleStore
from tests.test_engine_factory import FakeHA

from fastapi.testclient import TestClient

TOKEN = "s3cret"


def _auth(t=TOKEN):
    return {"Authorization": f"Bearer {t}"}


def _registry():
    return Registry({"climate.ac": Device(name="空调", type="climate", area="客厅")})


class _FakeEngine:
    def __init__(self):
        self.registry = _registry()


class _FakeController:
    """.handle(utterance) 返回预设 Outcome。带 .engine.registry 供 describe_action 解名。"""

    def __init__(self, outcome):
        self._outcome = outcome
        self.engine = _FakeEngine()

    def handle(self, utterance):
        return self._outcome


def _schedule_outcome():
    intent = ScheduleIntent(kind="recurring", hour=23, minute=0, recurrence="daily")
    d = Decision(verdict="allow", stage="passed", device_id="climate.ac",
                 operation="turn_off", params={}, confidence=1.0,
                 reason="已安排定时", schedule=intent)
    return Outcome(decision=d, executed=False, schedule=intent)


def _executed_outcome():
    d = Decision(verdict="allow", stage="passed", device_id="climate.ac",
                 operation="turn_off", params={}, confidence=1.0)
    return Outcome(decision=d, executed=True)


def _app(outcome, store=None, max_schedules=50):
    store = store if store is not None else ScheduleStore(path=None, max_schedules=max_schedules)
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=lambda deadline=None: _FakeController(outcome),
                     schedule_store=store)
    return TestClient(app), store


# ---- 1. schedule turn → 200 scheduled + 建 1 条 entry ----
def test_schedule_turn_creates_entry():
    c, store = _app(_schedule_outcome())
    r = c.post("/v1/turn", headers=_auth(), json={"utterance": "每天23点关空调"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scheduled"
    assert body["message"]                      # 有确认文案
    entries = store.list()
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "recurring"
    assert e.minute_of_day == 1380             # 23*60


# ---- 2. 非定时 turn → 行为如前(executed),store 不变 ----
def test_non_schedule_turn_unchanged():
    c, store = _app(_executed_outcome())
    r = c.post("/v1/turn", headers=_auth(), json={"utterance": "关空调"})
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert store.list() == []


# ---- 3. 超上限 → error/rejected + 限额文案,store 计数不变 ----
def test_schedule_turn_over_limit():
    store = ScheduleStore(path=None, max_schedules=1)
    # 预填到上限
    from service.schedule_store import ScheduleEntry
    import time as _t
    store.add(ScheduleEntry(
        id="pre1", device_id="light.a", operation="turn_off", params={},
        kind="once", at=_t.time() + 3600, minute_of_day=None, days=None,
        tz="Asia/Shanghai", enabled=True, next_fire_at=_t.time() + 3600,
        created_at=_t.time()))
    c, _ = _app(_schedule_outcome(), store=store)
    r = c.post("/v1/turn", headers=_auth(), json={"utterance": "每天23点关空调"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("error", "rejected")
    assert "上限" in body["message"]
    assert len(store.list()) == 1              # 仍在上限,未 +1


# ---- 4. 幂等:同 key 两次只建 1 条 ----
def test_schedule_turn_idempotent():
    c, store = _app(_schedule_outcome())
    payload = {"utterance": "每天23点关空调", "conversation_id": "c1",
               "idempotency_key": "k1"}
    r1 = c.post("/v1/turn", headers=_auth(), json=payload)
    r2 = c.post("/v1/turn", headers=_auth(), json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(store.list()) == 1              # 只建一条,非两条
    assert r2.json() == r1.json()              # 第二次 == 第一次(缓存)
