"""Task 5 — scheduler wiring into app lifespan + tz resolution.

全程 fake,不 import anthropic。覆盖:
1. 端点建 schedule + 执行器共享同一 store,手动驱 tick 触发。
2. resolve_tz:正常取 / 异常回退 / 非法 tz 回退。
3. lifespan 无 scheduler → 不起循环、client 正常。
4. lifespan 有 fake scheduler → start() 入、stop() 出(await)。
"""
import time

from fastapi.testclient import TestClient

from gatekeeper.controller import Outcome
from gatekeeper.models import Decision
from service.app import create_app
from service.schedule_store import ScheduleEntry, ScheduleStore
from service.scheduler import Scheduler
from service.scheduler_tz import resolve_tz
from tests.test_engine_factory import FakeHA

TOKEN = "s3cret"


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# ---------- fakes ----------

class _RecordingController:
    """记录 .control(...) 调用,按预设 verdict 返回 Outcome(给执行器读 .executed)。"""

    def __init__(self, decision):
        self._decision = decision
        self.calls = []
        # schedules 端点建时闸用 engine.decide_resolved
        self.engine = _FakeEngine(decision)

    def control(self, device_id, operation, params):
        self.calls.append((device_id, operation, dict(params)))
        executed = self._decision.verdict == "allow"
        return Outcome(decision=self._decision, executed=executed,
                       needs_confirmation=self._decision.verdict == "confirm")


class _FakeEngine:
    def __init__(self, decision):
        self._d = decision

    def decide_resolved(self, device_id, operation, params=None):
        return self._d


def _allow(device_id="light.a", operation="turn_off"):
    return Decision(verdict="allow", stage="passed", device_id=device_id,
                    operation=operation, reason="")


# ---------- 1. end-to-end: endpoint 建 + 执行器同 store + 手动 tick ----------

def test_endpoint_created_schedule_fires_via_shared_store():
    store = ScheduleStore(path=None)
    ctrl = _RecordingController(_allow())
    factory = lambda deadline=None: ctrl
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=factory, schedule_store=store)
    client = TestClient(app)

    past = time.time() - 5  # 已到期
    r = client.post("/v1/schedules", headers=_auth(), json={
        "device_id": "light.a", "operation": "turn_off", "params": {"brightness": 50},
        "kind": "once", "at": past})
    assert r.status_code in (200, 201)
    sid = r.json()["id"]

    # 执行器跑在同一 store 上,手动驱 tick(不依赖 live loop)
    scheduler = Scheduler(store, factory, tz_name="Asia/Shanghai", lock_path=None)
    scheduler.tick(now=time.time())

    assert ctrl.calls == [("light.a", "turn_off", {"brightness": 50})]
    entry = store.get(sid)
    assert entry.last_outcome == "executed"
    assert entry.enabled is False  # once 触发后停用


def test_tick_fires_directly_added_entry():
    store = ScheduleStore(path=None)
    ctrl = _RecordingController(_allow(operation="turn_on"))
    factory = lambda deadline=None: ctrl
    store.add(ScheduleEntry(
        id="e1", device_id="light.a", operation="turn_on", params={},
        kind="once", at=time.time() - 1, minute_of_day=None, days=None,
        tz="Asia/Shanghai", enabled=True, next_fire_at=time.time() - 1,
        created_at=time.time()))
    scheduler = Scheduler(store, factory, tz_name="Asia/Shanghai", lock_path=None)
    scheduler.tick(now=time.time())
    assert ctrl.calls == [("light.a", "turn_on", {})]
    assert store.get("e1").last_outcome == "executed"


# ---------- 2. resolve_tz ----------

class _FakeHAConfig:
    def __init__(self, config=None, raise_exc=False):
        self._config = config
        self._raise = raise_exc

    def fetch_config(self):
        if self._raise:
            raise RuntimeError("HA unreachable")
        return self._config


def test_resolve_tz_reads_time_zone():
    ha = _FakeHAConfig({"time_zone": "America/New_York"})
    assert resolve_tz(ha) == "America/New_York"


def test_resolve_tz_falls_back_on_exception():
    ha = _FakeHAConfig(raise_exc=True)
    assert resolve_tz(ha, default="Asia/Shanghai") == "Asia/Shanghai"


def test_resolve_tz_falls_back_on_missing():
    assert resolve_tz(_FakeHAConfig({})) == "Asia/Shanghai"
    assert resolve_tz(_FakeHAConfig({"time_zone": ""})) == "Asia/Shanghai"
    assert resolve_tz(_FakeHAConfig(None)) == "Asia/Shanghai"


def test_resolve_tz_falls_back_on_invalid_zone():
    ha = _FakeHAConfig({"time_zone": "Not/AZone"})
    assert resolve_tz(ha, default="Europe/London") == "Europe/London"


# ---------- 3. lifespan no-op without scheduler ----------

def test_lifespan_noop_without_scheduler():
    store = ScheduleStore(path=None)
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=lambda deadline=None: _RecordingController(_allow()),
                     schedule_store=store)
    # 进入 context 触发 lifespan(无 scheduler → 不应起循环、不应崩)
    with TestClient(app) as client:
        assert client.get("/v1/schedules", headers=_auth()).status_code == 200


# ---------- 4. lifespan with fake scheduler ----------

class _FakeScheduler:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return True

    async def stop(self):
        self.stopped += 1


def test_lifespan_starts_and_stops_scheduler():
    store = ScheduleStore(path=None)
    fake = _FakeScheduler()
    app = create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                     model="m", tau=0.7, api_token=TOKEN, request_timeout=5.0,
                     controller_factory=lambda deadline=None: _RecordingController(_allow()),
                     schedule_store=store, scheduler=fake)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert fake.started == 1
        assert fake.stopped == 0
    # 退出 context → shutdown → stop awaited
    assert fake.stopped == 1
