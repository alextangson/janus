import importlib

import gatekeeper.config
import service.config as cfg


def _reload(monkeypatch, **env):
    # 隔离真 .env:reload 时 service.config 会 load_env() 读仓库根 .env(可能含 JANUS_* 等),
    # 置为 no-op,测试只看显式设置的 env 与代码默认,不受本机 .env 内容影响。
    monkeypatch.setattr(gatekeeper.config, "load_env", lambda *a, **k: None)
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
    assert c.AUDIT_DB == "data/janus_audit.db"


def test_env_overrides(monkeypatch):
    c = _reload(monkeypatch, JANUS_API_TOKEN="s3cret", JANUS_PORT="9000",
                JANUS_PENDING_TTL_S="60", JANUS_MAX_CONCURRENCY="4",
                JANUS_AUDIT_DB="/tmp/a.db")
    assert c.API_TOKEN == "s3cret"
    assert c.PORT == 9000
    assert c.PENDING_TTL_S == 60.0
    assert c.MAX_CONCURRENCY == 4
    assert c.AUDIT_DB == "/tmp/a.db"
