from __future__ import annotations


def main() -> None:
    import uvicorn

    from gatekeeper.config import BACKEND, HA_BASE_URL, HA_TOKEN, LOCAL_BASE_URL, MODEL, TAU

    from . import config as svc
    from .app import create_app
    from .audit import AuditSink
    from .engine_factory import build_shared_clients
    from .sessions import ConversationStore

    if not HA_TOKEN:
        raise SystemExit("缺少 GATEKEEPER_HA_TOKEN")
    if not svc.API_TOKEN:
        raise SystemExit("缺少 JANUS_API_TOKEN(拒绝无认证启动)")

    ha_client, llm_client = build_shared_clients(HA_BASE_URL, HA_TOKEN, BACKEND, MODEL, LOCAL_BASE_URL)
    store = ConversationStore(pending_ttl=svc.PENDING_TTL_S, idempotency_ttl=svc.IDEMPOTENCY_TTL_S,
                              max_sessions=svc.MAX_SESSIONS)
    audit = AuditSink(svc.AUDIT_DB)
    app = create_app(ha_client=ha_client, llm_client=llm_client, backend=BACKEND, model=MODEL,
                     tau=TAU, api_token=svc.API_TOKEN, request_timeout=svc.REQUEST_TIMEOUT_S,
                     max_concurrency=svc.MAX_CONCURRENCY, store=store, audit=audit)
    uvicorn.run(app, host=svc.HOST, port=svc.PORT)


if __name__ == "__main__":
    main()
