from __future__ import annotations


def main() -> None:
    import os

    import uvicorn

    from gatekeeper.config import load_env

    load_env()  # 必须先加载 .env:gatekeeper.config 的 env 派生常量在 import 时已冻结,
    # 故 HA url/token/backend/tau 在此直接从 os.environ 读,避免读到冻结的空值。

    from . import config as svc
    from .app import create_app
    from .audit import AuditSink
    from .engine_factory import build_fresh_controller, build_shared_clients, resolve_runtime
    from .pin_store import PinStore
    from .schedule_store import ScheduleStore
    from .scheduler import Scheduler
    from .scheduler_tz import resolve_tz
    from .sessions import ConversationStore

    ha_url = os.environ.get("GATEKEEPER_HA_URL", "http://homeassistant.local:8123")
    ha_token = os.environ.get("GATEKEEPER_HA_TOKEN", "")
    backend = os.environ.get("GATEKEEPER_BACKEND", "claude")
    tau = float(os.environ.get("GATEKEEPER_TAU", "0.7"))
    schedule_path = os.environ.get("JANUS_SCHEDULE_PATH", "data/schedules.json")
    lock_path = os.environ.get("JANUS_SCHEDULE_LOCK", "data/scheduler.lock")
    env_default_tz = os.environ.get("JANUS_DEFAULT_TZ", "Asia/Shanghai")

    if not ha_token:
        raise SystemExit("缺少 GATEKEEPER_HA_TOKEN")
    if not svc.API_TOKEN:
        raise SystemExit("缺少 JANUS_API_TOKEN(拒绝无认证启动)")

    # 本地后端用 LOCAL_MODEL(发给 Ollama 的模型名)+ 可覆盖 base_url(容器内指向 ollama 主机名);
    # 云端仍用 MODEL。三处(shared clients / scheduler 工厂 / create_app)统一用解析结果。
    model, local_base_url = resolve_runtime(backend)
    ha_client, llm_client = build_shared_clients(ha_url, ha_token, backend, model, local_base_url)
    store = ConversationStore(pending_ttl=svc.PENDING_TTL_S, idempotency_ttl=svc.IDEMPOTENCY_TTL_S,
                              max_sessions=svc.MAX_SESSIONS)
    audit = AuditSink(svc.AUDIT_DB)
    pin_store = PinStore(env_pin=svc.DANGEROUS_PIN, path=svc.SECURITY_FILE)

    # 定时任务:store + 执行器共享同一持久文件;HA 取不到 tz 时 resolve_tz 已兜底默认(不崩)。
    schedule_store = ScheduleStore(path=schedule_path)
    tz = resolve_tz(ha_client, default=env_default_tz)
    scheduler = Scheduler(
        schedule_store,
        controller_factory=lambda: build_fresh_controller(ha_client, llm_client, backend, model, tau),
        tz_name=tz, audit=audit, lock_path=lock_path)

    app = create_app(ha_client=ha_client, llm_client=llm_client, backend=backend, model=model,
                     tau=tau, api_token=svc.API_TOKEN, pin_store=pin_store,
                     request_timeout=svc.REQUEST_TIMEOUT_S,
                     max_concurrency=svc.MAX_CONCURRENCY, store=store, audit=audit,
                     cors_origins=svc.CORS_ORIGINS,
                     schedule_store=schedule_store, default_tz=tz, scheduler=scheduler,
                     static_dir=svc.STATIC_DIR or None, ingress=svc.INGRESS,
                     supervisor_ip=svc.SUPERVISOR_IP)
    uvicorn.run(app, host=svc.HOST, port=svc.PORT)


if __name__ == "__main__":
    main()
