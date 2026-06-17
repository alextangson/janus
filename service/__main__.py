from __future__ import annotations


def main() -> None:
    import os

    import uvicorn

    from gatekeeper.config import load_env

    load_env()  # 必须先加载 .env:gatekeeper.config 的 env 派生常量在 import 时已冻结,
    # 故 HA url/token/backend/tau 在此直接从 os.environ 读,避免读到冻结的空值。

    from gatekeeper.config import LOCAL_BASE_URL, MODEL

    from . import config as svc
    from .app import create_app
    from .audit import AuditSink
    from .engine_factory import build_shared_clients
    from .sessions import ConversationStore

    ha_url = os.environ.get("GATEKEEPER_HA_URL", "http://homeassistant.local:8123")
    ha_token = os.environ.get("GATEKEEPER_HA_TOKEN", "")
    backend = os.environ.get("GATEKEEPER_BACKEND", "claude")
    tau = float(os.environ.get("GATEKEEPER_TAU", "0.7"))

    if not ha_token:
        raise SystemExit("缺少 GATEKEEPER_HA_TOKEN")
    if not svc.API_TOKEN:
        raise SystemExit("缺少 JANUS_API_TOKEN(拒绝无认证启动)")

    ha_client, llm_client = build_shared_clients(ha_url, ha_token, backend, MODEL, LOCAL_BASE_URL)
    store = ConversationStore(pending_ttl=svc.PENDING_TTL_S, idempotency_ttl=svc.IDEMPOTENCY_TTL_S,
                              max_sessions=svc.MAX_SESSIONS)
    audit = AuditSink(svc.AUDIT_DB)
    app = create_app(ha_client=ha_client, llm_client=llm_client, backend=backend, model=MODEL,
                     tau=tau, api_token=svc.API_TOKEN, request_timeout=svc.REQUEST_TIMEOUT_S,
                     max_concurrency=svc.MAX_CONCURRENCY, store=store, audit=audit,
                     cors_origins=svc.CORS_ORIGINS)
    uvicorn.run(app, host=svc.HOST, port=svc.PORT)


if __name__ == "__main__":
    main()
