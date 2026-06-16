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
