import pytest

from gatekeeper.ha_client import HAClient


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def json(self):
        return self._payload


class StubHTTP:
    def __init__(self, by_path, status=200):
        self._by_path = by_path
        self._status = status
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        for p, payload in self._by_path.items():
            if url.endswith(p):
                return _Resp(payload, self._status)
        return _Resp({}, self._status)


def test_fetch_returns_states_and_services_with_bearer():
    stub = StubHTTP({"/api/states": [{"entity_id": "light.x"}], "/api/services": [{"domain": "light"}]})
    client = HAClient("http://homeassistant.local:8123/", token="tok", client=stub)
    states, services = client.fetch()
    assert states == [{"entity_id": "light.x"}]
    assert services == [{"domain": "light"}]
    assert any(u.endswith("/api/states") for u, _ in stub.calls)
    assert any(u.endswith("/api/services") for u, _ in stub.calls)
    assert all(h["Authorization"] == "Bearer tok" for _, h in stub.calls)


def test_fetch_propagates_http_errors():
    stub = StubHTTP({"/api/states": {}}, status=401)
    client = HAClient("http://homeassistant.local:8123", token="bad", client=stub)
    with pytest.raises(RuntimeError):
        client.fetch()


class StubPost:
    def __init__(self, status=200):
        self._status = status
        self.calls = []

    def post(self, url, headers=None, json=None):
        self.calls.append((url, headers, json))
        return _Resp({"ok": True}, self._status)


def test_call_service_posts_with_entity_and_params():
    stub = StubPost()
    client = HAClient("http://ha:8123", token="tok", client=stub)
    client.call_service("climate", "set_temperature", "climate.living_room", {"temperature": 24})
    url, headers, body = stub.calls[0]
    assert url.endswith("/api/services/climate/set_temperature")
    assert headers["Authorization"] == "Bearer tok"
    assert body == {"entity_id": "climate.living_room", "temperature": 24}


def test_call_service_no_params_sends_only_entity():
    stub = StubPost()
    HAClient("http://ha:8123", token="t", client=stub).call_service("light", "turn_on", "light.x")
    _, _, body = stub.calls[0]
    assert body == {"entity_id": "light.x"}


def test_call_service_propagates_errors():
    stub = StubPost(status=500)
    client = HAClient("http://ha:8123", token="t", client=stub)
    with pytest.raises(RuntimeError):
        client.call_service("light", "turn_on", "light.x")
