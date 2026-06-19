import pytest

from gatekeeper.config import LOCAL_BASE_URL, LOCAL_MODEL, MODEL
from service.engine_factory import build_fresh_controller, resolve_runtime


class FakeHA:
    """最小假 HAClient:fetch/fetch_registries/fetch_config 返回可建 Registry 的形状。"""

    def __init__(self, fail=False):
        self._fail = fail
        self.service_calls = []

    def fetch(self):
        if self._fail:
            raise RuntimeError("HA unreachable")
        states = [{"entity_id": "light.a", "state": "on",
                   "attributes": {"friendly_name": "主灯"}}]
        services = [{"domain": "light", "services": {"turn_off": {}, "turn_on": {}}}]
        return states, services

    def fetch_registries(self):
        entities = [{"entity_id": "light.a", "device_id": None, "area_id": None}]
        return entities, [], []

    def fetch_config(self):
        return {"unit_system": {"temperature": "°C"}}

    def call_service(self, domain, service, entity_id, params=None):
        self.service_calls.append((domain, service, entity_id, params))
        return {"ok": True}


def test_builds_controller_with_live_registry():
    ha = FakeHA()
    ctrl = build_fresh_controller(ha, llm_client=object(), backend="claude",
                                  model="claude-sonnet-4-6", tau=0.7)
    assert "light.a" in ctrl.engine.registry.device_ids()
    assert ctrl.engine.tau == 0.7


def test_fetch_failure_propagates_fail_closed():
    ha = FakeHA(fail=True)
    with pytest.raises(RuntimeError):
        build_fresh_controller(ha, llm_client=object(), backend="claude",
                               model="claude-sonnet-4-6", tau=0.7)


def test_resolve_runtime_local_uses_local_model(monkeypatch):
    # 本地后端必须用 LOCAL_MODEL(发给 Ollama),不能用云端 MODEL,否则 Ollama 404。
    monkeypatch.delenv("GATEKEEPER_LOCAL_BASE_URL", raising=False)
    model, base_url = resolve_runtime("local")
    assert model == LOCAL_MODEL
    assert base_url == LOCAL_BASE_URL


def test_resolve_runtime_local_base_url_env_override(monkeypatch):
    # 容器内服务跨不到 localhost:在 __main__ 读 env,避开 config 模块级常量的 import-time 冻结。
    monkeypatch.setenv("GATEKEEPER_LOCAL_BASE_URL", "http://ollama:11434/v1")
    model, base_url = resolve_runtime("local")
    assert model == LOCAL_MODEL
    assert base_url == "http://ollama:11434/v1"


def test_resolve_runtime_cloud_uses_cloud_model(monkeypatch):
    monkeypatch.delenv("GATEKEEPER_LOCAL_BASE_URL", raising=False)
    model, _ = resolve_runtime("claude")
    assert model == MODEL
