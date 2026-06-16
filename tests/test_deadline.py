import pytest

from service.deadline import DeadlineExceeded, DeadlineHAClient


class StubHA:
    def __init__(self):
        self.calls = []
        self.other = "passthrough"

    def call_service(self, domain, service, entity_id, params=None):
        self.calls.append((domain, service, entity_id, params))
        return {"ok": True}

    def fetch(self):
        return (["state"], ["svc"])


def test_call_before_deadline_delegates():
    clock = [100.0]
    inner = StubHA()
    dl = DeadlineHAClient(inner, deadline=200.0, now=lambda: clock[0])
    assert dl.call_service("light", "turn_off", "light.a", {}) == {"ok": True}
    assert inner.calls == [("light", "turn_off", "light.a", {})]


def test_call_after_deadline_raises_before_executing():
    clock = [250.0]
    inner = StubHA()
    dl = DeadlineHAClient(inner, deadline=200.0, now=lambda: clock[0])
    with pytest.raises(DeadlineExceeded):
        dl.call_service("lock", "unlock", "lock.door", {})
    assert inner.calls == []        # 关键:死线后绝不真打 HA


def test_other_attrs_pass_through():
    inner = StubHA()
    dl = DeadlineHAClient(inner, deadline=200.0, now=lambda: 100.0)
    assert dl.fetch() == (["state"], ["svc"])
    assert dl.other == "passthrough"
