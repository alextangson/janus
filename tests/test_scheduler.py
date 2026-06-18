import os

from service.schedule_store import ScheduleEntry, ScheduleStore
from service.scheduler import Scheduler

SH = "Asia/Shanghai"  # UTC+8, 无 DST,断言确定


# ---- fakes ----


class FakeOutcome:
    def __init__(self, executed, reason=None):
        self.executed = executed
        self.decision = type("D", (), {"reason": reason})()


class RecordingController:
    """记录每次 control() 的入参,返回预置 outcome(或抛异常)。"""

    def __init__(self, outcome=None, exc=None):
        self._outcome = outcome
        self._exc = exc
        self.calls = []

    def control(self, device_id, operation, params):
        self.calls.append((device_id, operation, params))
        if self._exc is not None:
            raise self._exc
        return self._outcome


def factory_returning(outcome):
    ctrl = RecordingController(outcome=outcome)
    return (lambda: ctrl), ctrl


def factory_raising(exc):
    ctrl = RecordingController(exc=exc)
    return (lambda: ctrl), ctrl


class CountingFactory:
    """每次调用返回一个新的 RecordingController,记录工厂被调用次数。"""

    def __init__(self, outcome=None, exc=None):
        self._outcome = outcome
        self._exc = exc
        self.controllers = []

    def __call__(self):
        ctrl = RecordingController(outcome=self._outcome, exc=self._exc)
        self.controllers.append(ctrl)
        return ctrl

    @property
    def total_calls(self):
        return sum(len(c.calls) for c in self.controllers)


class FakeAudit:
    def __init__(self):
        self.events = []

    def record_lifecycle(self, **kw):
        self.events.append(kw)


# ---- helpers ----


def _recurring(sid="s1", *, minute_of_day=600, days=None, next_fire_at=0.0,
               enabled=True, tz=SH):
    return ScheduleEntry(
        id=sid,
        device_id="light.kitchen",
        operation="turn_on",
        params={"brightness": 80},
        kind="recurring",
        at=None,
        minute_of_day=minute_of_day,
        days=days if days is not None else [0, 1, 2, 3, 4, 5, 6],
        tz=tz,
        enabled=enabled,
        next_fire_at=next_fire_at,
        created_at=0.0,
    )


def _once(sid="o1", *, at=100.0, next_fire_at=0.0, enabled=True, tz=SH):
    return ScheduleEntry(
        id=sid,
        device_id="lock.front",
        operation="unlock",
        params={},
        kind="once",
        at=at,
        minute_of_day=None,
        days=None,
        tz=tz,
        enabled=enabled,
        next_fire_at=next_fire_at,
        created_at=0.0,
    )


def _store(*entries):
    s = ScheduleStore(path=None)
    for e in entries:
        s.add(e)
    return s


# ---- 1. due recurring + executed ----


def test_due_recurring_executed_advances_and_invokes_controller():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac, ctrl = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=2000.0)

    got = store.get("s1")
    assert got.last_outcome == "executed"
    assert got.last_skipped_reason is None
    assert got.last_error is None
    assert got.enabled is True
    assert got.next_fire_at is not None and got.next_fire_at > 2000.0
    assert got.last_attempt == 2000.0
    # 控制器被真实调用,入参透传
    assert ctrl.calls == [("light.kitchen", "turn_on", {"brightness": 80})]


# ---- 2. due + not executed → skipped, recurring still advances ----


def test_due_not_executed_records_skip_and_advances():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac, ctrl = factory_returning(FakeOutcome(executed=False, reason="dangerous"))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=2000.0)

    got = store.get("s1")
    assert got.last_outcome == "skipped"
    assert got.last_skipped_reason == "dangerous"
    assert got.last_error is None
    # recurring 仍前进
    assert got.next_fire_at is not None and got.next_fire_at > 2000.0
    assert got.enabled is True


# ---- 3. controller raises → failed, tick survives, second entry still runs ----


def test_controller_exception_isolated_per_entry():
    e1 = _recurring(sid="s1", next_fire_at=1000.0)
    e2 = _recurring(sid="s2", next_fire_at=1100.0)
    store = _store(e1, e2)
    fac = CountingFactory(exc=RuntimeError("boom"))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=2000.0)  # 不应抛

    g1 = store.get("s1")
    assert g1.last_outcome == "failed"
    assert g1.last_error == "boom"
    # 失败也推进窗口:不在同一窗口无限重试
    assert g1.next_fire_at is not None and g1.next_fire_at > 2000.0
    # 即使第一个炸了,第二个仍被处理
    g2 = store.get("s2")
    assert g2.last_outcome == "failed"
    assert g2.last_error == "boom"
    assert g2.next_fire_at is not None and g2.next_fire_at > 2000.0
    # 两个条目都各拿到一个新鲜控制器并被调用
    assert len(fac.controllers) == 2
    assert fac.total_calls == 2


# ---- 4. once entry fires → disabled, next_fire_at None ----


def test_once_fires_then_disables():
    e = _once(next_fire_at=500.0)
    store = _store(e)
    fac, _ = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=600.0)

    got = store.get("o1")
    assert got.last_outcome == "executed"
    assert got.enabled is False
    assert got.next_fire_at is None


# ---- 5. not-yet-due entry untouched ----


def test_not_yet_due_untouched():
    e = _recurring(next_fire_at=5000.0)
    store = _store(e)
    fac, ctrl = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=1000.0)

    got = store.get("s1")
    assert got.last_outcome is None
    assert got.last_attempt is None
    assert got.next_fire_at == 5000.0
    assert ctrl.calls == []


# ---- 6. disabled entry skipped ----


def test_disabled_entry_skipped():
    e = _recurring(next_fire_at=100.0, enabled=False)
    store = _store(e)
    fac, ctrl = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH)

    sched.tick(now=2000.0)

    got = store.get("s1")
    assert got.last_outcome is None
    assert got.last_attempt is None
    assert ctrl.calls == []


# ---- 7. max_due_per_tick caps fires ----


def test_max_due_per_tick_caps():
    entries = [_recurring(sid=f"s{i}", next_fire_at=100.0 + i) for i in range(5)]
    store = _store(*entries)
    fac = CountingFactory(outcome=FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH, max_due_per_tick=2)

    sched.tick(now=2000.0)

    fired = [s for s in store.list() if s.last_outcome == "executed"]
    assert len(fired) == 2
    assert fac.total_calls == 2
    # 取最早到期的两个(next_fire_at 升序)
    fired_ids = {s.id for s in fired}
    assert fired_ids == {"s0", "s1"}


# ---- 8. idempotency: re-tick at same T does not re-fire ----


def test_idempotent_same_tick_no_refire():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac = CountingFactory(outcome=FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH)

    T = 2000.0
    sched.tick(now=T)
    nf_after_first = store.get("s1").next_fire_at
    assert nf_after_first is not None and nf_after_first > T

    sched.tick(now=T)  # 同一时刻再 tick:已不再 <= now
    # 总触发次数仍为 1
    assert fac.total_calls == 1
    assert store.get("s1").next_fire_at == nf_after_first


# ---- 9. owner lock ----


def test_acquire_owner_lock_none_path_true():
    store = _store()
    fac, _ = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH, lock_path=None)
    assert sched.acquire_owner_lock() is True


def test_acquire_owner_lock_mutual_exclusion(tmp_path):
    lock_path = tmp_path / "sched.lock"
    store = _store()
    fac, _ = factory_returning(FakeOutcome(executed=True))

    s1 = Scheduler(store, fac, tz_name=SH, lock_path=lock_path)
    s2 = Scheduler(store, fac, tz_name=SH, lock_path=lock_path)

    assert s1.acquire_owner_lock() is True  # 第一个拿到
    assert s2.acquire_owner_lock() is False  # 第二个被挡(s1 fd 仍开)
    # 释放后第二个可拿
    s1._release_lock()
    assert s2.acquire_owner_lock() is True
    s2._release_lock()


def test_acquire_owner_lock_creates_missing_parent_dir(tmp_path):
    # 全新部署:父目录尚不存在。acquire 应自建目录并成功拿锁,而非被 OSError 静默吞掉。
    lock_path = tmp_path / "nonexistent_subdir" / "scheduler.lock"
    assert not lock_path.parent.exists()
    store = _store()
    fac, _ = factory_returning(FakeOutcome(executed=True))
    sched = Scheduler(store, fac, tz_name=SH, lock_path=lock_path)

    assert sched.acquire_owner_lock() is True
    assert lock_path.parent.is_dir()  # 父目录被创建
    assert lock_path.exists()         # 锁文件被创建

    sched._release_lock()


# ---- 10. audit events ----


def test_audit_executed_event():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac, _ = factory_returning(FakeOutcome(executed=True))
    audit = FakeAudit()
    sched = Scheduler(store, fac, tz_name=SH, audit=audit)

    sched.tick(now=2000.0)

    events = [ev["event"] for ev in audit.events]
    assert "schedule_fired" in events
    fired = next(ev for ev in audit.events if ev["event"] == "schedule_fired")
    assert fired["conversation_id"] == "schedule:s1"
    assert fired["caller"] == "scheduler"
    assert fired["device_id"] == "light.kitchen"
    assert fired["operation"] == "turn_on"
    assert fired["request_id"]  # 非空


def test_audit_skipped_event():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac, _ = factory_returning(FakeOutcome(executed=False, reason="dangerous"))
    audit = FakeAudit()
    sched = Scheduler(store, fac, tz_name=SH, audit=audit)

    sched.tick(now=2000.0)

    assert "schedule_skipped" in [ev["event"] for ev in audit.events]


def test_audit_failed_event():
    e = _recurring(next_fire_at=1000.0)
    store = _store(e)
    fac = CountingFactory(exc=RuntimeError("boom"))
    audit = FakeAudit()
    sched = Scheduler(store, fac, tz_name=SH, audit=audit)

    sched.tick(now=2000.0)

    assert "schedule_failed" in [ev["event"] for ev in audit.events]


def test_audit_once_disabled_event():
    e = _once(next_fire_at=500.0)
    store = _store(e)
    fac, _ = factory_returning(FakeOutcome(executed=True))
    audit = FakeAudit()
    sched = Scheduler(store, fac, tz_name=SH, audit=audit)

    sched.tick(now=600.0)

    events = [ev["event"] for ev in audit.events]
    assert "schedule_fired" in events
    assert "schedule_disabled" in events


def test_audit_recurring_exhausted_disabled_event():
    # days=[] → compute_next_fire 无未来触发 → 条目耗尽被禁用
    e = _recurring(next_fire_at=1000.0, days=[])
    store = _store(e)
    fac, _ = factory_returning(FakeOutcome(executed=True))
    audit = FakeAudit()
    sched = Scheduler(store, fac, tz_name=SH, audit=audit)

    sched.tick(now=2000.0)

    got = store.get("s1")
    assert got.enabled is False
    assert got.next_fire_at is None
    assert "schedule_disabled" in [ev["event"] for ev in audit.events]
