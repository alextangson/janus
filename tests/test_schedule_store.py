import os

import pytest

from service.schedule_store import (
    ScheduleEntry,
    ScheduleLimitExceeded,
    ScheduleStore,
)


def _entry(sid: str = "s1", **over) -> ScheduleEntry:
    base = dict(
        id=sid,
        device_id="light.kitchen",
        operation="turn_on",
        params={"brightness": 80},
        kind="recurring",
        at=None,
        minute_of_day=420,
        days=[0, 1, 2, 3, 4],
        tz="Asia/Shanghai",
        enabled=True,
        next_fire_at=1_700_000_000.0,
        created_at=1_699_000_000.0,
    )
    base.update(over)
    return ScheduleEntry(**base)


def test_in_memory_add_get_list_roundtrip():
    s = ScheduleStore(path=None)
    e = _entry("a")
    s.add(e)
    got = s.get("a")
    assert got == e
    assert s.list() == [e]
    # 字段保真
    assert got.device_id == "light.kitchen"
    assert got.params == {"brightness": 80}
    assert got.days == [0, 1, 2, 3, 4]


def test_add_beyond_max_raises():
    s = ScheduleStore(path=None, max_schedules=2)
    s.add(_entry("a"))
    s.add(_entry("b"))
    with pytest.raises(ScheduleLimitExceeded):
        s.add(_entry("c"))


def test_remove_existing_and_missing():
    s = ScheduleStore(path=None)
    s.add(_entry("a"))
    assert s.remove("a") is True
    assert s.get("a") is None
    assert s.remove("a") is False
    assert s.remove("nope") is False


def test_update_existing_and_absent():
    s = ScheduleStore(path=None)
    s.add(_entry("a", enabled=True))
    s.update(_entry("a", enabled=False, last_outcome="ok"))
    got = s.get("a")
    assert got.enabled is False
    assert got.last_outcome == "ok"
    with pytest.raises(ValueError):
        s.update(_entry("ghost"))


def test_persist_survives_reconstruction(tmp_path):
    p = str(tmp_path / "sched.json")
    s = ScheduleStore(path=p)
    e = _entry(
        "a",
        kind="once",
        at=1_700_500_000.0,
        minute_of_day=None,
        days=None,
        last_attempt=1_700_400_000.0,
        last_outcome="fired",
        last_skipped_reason=None,
        last_error=None,
    )
    s.add(e)
    s2 = ScheduleStore(path=p)
    got = s2.get("a")
    assert got == e
    # 可选字段全保真
    assert got.last_attempt == 1_700_400_000.0
    assert got.last_outcome == "fired"
    assert got.at == 1_700_500_000.0
    assert got.minute_of_day is None
    assert got.days is None


def test_corrupt_file_raises(tmp_path):
    p = str(tmp_path / "sched.json")
    with open(p, "w") as f:
        f.write("{ broken")
    with pytest.raises(Exception):
        ScheduleStore(path=p)


def test_in_memory_never_writes(tmp_path, monkeypatch):
    # 切到一个空目录,确认 path=None 不落盘
    monkeypatch.chdir(tmp_path)
    s = ScheduleStore(path=None)
    s.add(_entry("a"))
    s.update(_entry("a", enabled=False))
    s.remove("a")
    assert os.listdir(tmp_path) == []


def test_entry_dict_roundtrip_preserves_none_optionals():
    e = _entry(
        "a",
        kind="once",
        at=123.0,
        minute_of_day=None,
        days=None,
        next_fire_at=None,
        last_attempt=None,
        last_outcome=None,
        last_skipped_reason=None,
        last_error=None,
    )
    d = e.to_dict()
    assert isinstance(d, dict)
    back = ScheduleEntry.from_dict(d)
    assert back == e


def test_from_dict_tolerates_missing_optional_keys():
    minimal = dict(
        id="a",
        device_id="light.kitchen",
        operation="turn_on",
        params={},
        kind="once",
        at=1.0,
        minute_of_day=None,
        days=None,
        tz="UTC",
        enabled=True,
        next_fire_at=None,
        created_at=1.0,
    )  # 无 last_* 键
    e = ScheduleEntry.from_dict(minimal)
    assert e.last_attempt is None
    assert e.last_outcome is None
    assert e.last_skipped_reason is None
    assert e.last_error is None
