import os

from service.pin_store import PinStore


def test_env_only_verify():
    s = PinStore(env_pin="246810", path=None)
    assert s.is_configured()
    assert s.verify("246810")
    assert not s.verify("000000")
    assert not s.has_durable_path()


def test_unconfigured():
    s = PinStore(env_pin="", path=None)
    assert not s.is_configured()
    assert not s.verify("x")
    assert not s.verify(None)


def test_set_writes_file_and_shadows_env(tmp_path):
    p = str(tmp_path / "sec.json")
    s = PinStore(env_pin="111111", path=p)
    s.set("654321")
    assert s.verify("654321")
    assert not s.verify("111111")              # 文件覆盖 env
    s2 = PinStore(env_pin="111111", path=p)    # 重载持久
    assert s2.verify("654321")
    assert oct(os.stat(p).st_mode)[-3:] == "600"


def test_corrupt_file_fails_closed(tmp_path):
    p = str(tmp_path / "sec.json")
    with open(p, "w") as f:
        f.write("{bad json")
    s = PinStore(env_pin="111111", path=p)
    assert s.is_configured()                   # 损坏仍算已配
    assert not s.verify("111111")              # 但 fail-closed:不回退 env
    assert not s.verify("any")


def test_change_throttle_locks_after_failures(tmp_path):
    s = PinStore(env_pin="111111", path=str(tmp_path / "s.json"))
    for _ in range(5):
        assert not s.verify_for_change("000000")
    assert s.change_locked() > 0               # 5 失败 → 锁定


def test_verify_for_change_success(tmp_path):
    s = PinStore(env_pin="111111", path=str(tmp_path / "s.json"))
    assert s.verify_for_change("111111")
    assert s.change_locked() == 0              # 成功不锁


def test_set_requires_durable_path():
    s = PinStore(env_pin="111111", path=None)
    try:
        s.set("654321")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
