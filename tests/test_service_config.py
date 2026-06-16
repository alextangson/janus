import importlib

import service.config as cfg


def _reload(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(cfg)


def test_defaults(monkeypatch):
    monkeypatch.delenv("JANUS_API_TOKEN", raising=False)
    c = _reload(monkeypatch)
    assert c.PENDING_TTL_S == 120.0
    assert c.REQUEST_TIMEOUT_S == 30.0
    assert c.MAX_CONCURRENCY == 8
    assert c.MAX_SESSIONS == 1000
    assert c.IDEMPOTENCY_TTL_S == 300.0
    assert c.HOST == "127.0.0.1" and c.PORT == 8088
    assert c.API_TOKEN == ""


def test_env_overrides(monkeypatch):
    c = _reload(monkeypatch, JANUS_API_TOKEN="s3cret", JANUS_PORT="9000",
                JANUS_PENDING_TTL_S="60", JANUS_MAX_CONCURRENCY="4")
    assert c.API_TOKEN == "s3cret"
    assert c.PORT == 9000
    assert c.PENDING_TTL_S == 60.0
    assert c.MAX_CONCURRENCY == 4
