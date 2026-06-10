import json as _json

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


def test_fetch_config_gets_api_config():
    stub = StubHTTP({"/api/config": {"unit_system": {"temperature": "°F"}}})
    client = HAClient("http://ha:8123", token="tok", client=stub)
    cfg = client.fetch_config()
    assert cfg["unit_system"]["temperature"] == "°F"
    assert any(u.endswith("/api/config") for u, _ in stub.calls)
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


class StubWS:
    """重放 HA WS:auth_required → auth_ok → 三条 result。记录发出的消息。"""
    def __init__(self, results_by_id):
        self._outbox = [{"type": "auth_required"}]
        self._results = results_by_id  # {id: result-list}
        self.sent = []
        self.closed = False

    def recv(self):
        if self._outbox:
            return _json.dumps(self._outbox.pop(0))
        raise AssertionError("recv with empty outbox")

    def send(self, raw):
        msg = _json.loads(raw)
        self.sent.append(msg)
        if msg.get("type") == "auth":
            self._outbox.append({"type": "auth_ok"})
        elif "id" in msg:
            self._outbox.append({"id": msg["id"], "type": "result", "success": True,
                                 "result": self._results.get(msg["id"], [])})

    def close(self):
        self.closed = True


def test_fetch_registries_auth_and_three_lists():
    ws = StubWS({1: [{"entity_id": "light.x"}], 2: [{"id": "d1"}], 3: [{"area_id": "a1"}]})
    client = HAClient("http://ha:8123", token="tok", client=object())
    entities, devices, areas = client.fetch_registries(ws_connect=lambda url: ws)
    assert entities == [{"entity_id": "light.x"}]
    assert devices == [{"id": "d1"}]
    assert areas == [{"area_id": "a1"}]
    assert ws.sent[0] == {"type": "auth", "access_token": "tok"}
    assert [m["type"] for m in ws.sent[1:]] == [
        "config/entity_registry/list", "config/device_registry/list", "config/area_registry/list"]
    assert ws.closed is True


def test_fetch_registries_auth_failure_raises():
    class BadAuthWS(StubWS):
        def send(self, raw):
            msg = _json.loads(raw)
            self.sent.append(msg)
            if msg.get("type") == "auth":
                self._outbox.append({"type": "auth_invalid", "message": "bad token"})
    ws = BadAuthWS({})
    client = HAClient("http://ha:8123", token="bad", client=object())
    with pytest.raises(RuntimeError):
        client.fetch_registries(ws_connect=lambda url: ws)


def test_fetch_registries_command_failure_raises():
    class FailCmdWS(StubWS):
        def send(self, raw):
            msg = _json.loads(raw)
            self.sent.append(msg)
            if msg.get("type") == "auth":
                self._outbox.append({"type": "auth_ok"})
            elif "id" in msg:
                self._outbox.append({"id": msg["id"], "type": "result", "success": False,
                                     "error": {"message": "no permission"}})
    ws = FailCmdWS({})
    client = HAClient("http://ha:8123", token="t", client=object())
    with pytest.raises(RuntimeError):
        client.fetch_registries(ws_connect=lambda url: ws)


def test_fetch_registries_unexpected_first_message_raises():
    class NoAuthRequiredWS(StubWS):
        def __init__(self, results_by_id):
            super().__init__(results_by_id)
            self._outbox = [{"type": "result"}]  # 首条不是 auth_required
    ws = NoAuthRequiredWS({})
    client = HAClient("http://ha:8123", token="t", client=object())
    with pytest.raises(RuntimeError):
        client.fetch_registries(ws_connect=lambda url: ws)


def test_ws_url_derivation():
    assert HAClient("https://ha:8123/", token="t", client=object())._ws_url() == "wss://ha:8123/api/websocket"
    assert HAClient("http://localhost:8123", token="t", client=object())._ws_url() == "ws://localhost:8123/api/websocket"
