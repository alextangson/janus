"""HAOS add-on(ingress)模式:静态托管 + token 注入 + supervisor 源 IP 闸 + bearer 仍要。"""
import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from tests.test_engine_factory import FakeHA


@pytest.fixture
def static_root(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><head></head><body>janus</body></html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('hi')", encoding="utf-8")
    return str(tmp_path)


def _app(static_root, *, ingress=False, supervisor_ip="172.30.32.2", api_token="s3cret"):
    return create_app(ha_client=FakeHA(), llm_client=object(), backend="claude",
                      model="m", tau=0.7, api_token=api_token, request_timeout=5.0,
                      static_dir=static_root, ingress=ingress, supervisor_ip=supervisor_ip)


# ── 静态托管(无 ingress)────────────────────────────────────────────────
def test_serves_index_without_injection_when_not_ingress(static_root):
    c = TestClient(_app(static_root))
    r = c.get("/")
    assert r.status_code == 200
    assert "janus" in r.text
    assert "__JANUS__" not in r.text  # 非 ingress 不注入 token


def test_serves_asset(static_root):
    r = TestClient(_app(static_root)).get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_missing_asset_is_real_404_not_html(static_root):
    r = TestClient(_app(static_root)).get("/assets/missing.js")
    assert r.status_code == 404
    assert "<html" not in r.text  # 资产缺失返真 404,不回退 HTML(codex #10)


def test_unknown_route_spa_fallback_to_index(static_root):
    r = TestClient(_app(static_root)).get("/some/client/route")
    assert r.status_code == 200 and "janus" in r.text  # 非资产路径 → SPA 回退


def test_static_does_not_swallow_api_routes(static_root):
    c = TestClient(_app(static_root))
    assert c.get("/v1/devices").status_code == 401          # /v1 仍走鉴权,非静态
    assert c.get("/v1/nope").status_code == 404             # 未知 /v1 真 404,不回退 HTML
    assert c.get("/health").status_code == 200


# ── ingress 源 IP 闸 ───────────────────────────────────────────────────
def test_ingress_blocks_non_supervisor_source(static_root):
    c = TestClient(_app(static_root, ingress=True))  # 默认 client host = "testclient"
    assert c.get("/health").status_code == 403       # 非 supervisor 源一律 403


def test_ingress_allows_supervisor_source(static_root):
    c = TestClient(_app(static_root, ingress=True), client=("172.30.32.2", 0))
    assert c.get("/health").status_code == 200


# ── ingress token 注入 + bearer 仍要 ───────────────────────────────────
def test_ingress_injects_token_and_base(static_root):
    c = TestClient(_app(static_root, ingress=True), client=("172.30.32.2", 0))
    r = c.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
    assert r.status_code == 200
    assert "window.__JANUS__" in r.text
    assert "s3cret" in r.text                                   # 真 token 注入
    assert "/api/hassio_ingress/abc123" in r.text               # 真 ingress 根注入(codex #3)


def test_ingress_v1_still_requires_bearer(static_root):
    # 安全核心:ingress 不旁路 bearer(codex #4/#8)。源 IP 闸只是防御纵深。
    c = TestClient(_app(static_root, ingress=True), client=("172.30.32.2", 0))
    assert c.get("/v1/devices").status_code == 401
    assert c.get("/v1/devices", headers={"Authorization": "Bearer s3cret"}).status_code == 200
