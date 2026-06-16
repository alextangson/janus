from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException

from .deadline import DeadlineExceeded, DeadlineHAClient
from .dto import outcome_to_dto
from .engine_factory import build_fresh_controller
from .sessions import ConversationStore


def create_app(*, ha_client, llm_client, backend: str, model: str, tau: float,
               api_token: str, request_timeout: float = 30.0,
               max_concurrency: int = 8, store: ConversationStore | None = None) -> FastAPI:
    if not api_token:
        raise RuntimeError("JANUS_API_TOKEN 未设置:拒绝在无认证下启动")
    app = FastAPI(title="Janus", version="1")
    store = store or ConversationStore()
    sem = asyncio.Semaphore(max_concurrency)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {api_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="unauthorized")

    def _fresh_controller(deadline: float | None = None):
        ha = DeadlineHAClient(ha_client, deadline) if deadline is not None else ha_client
        return build_fresh_controller(ha, llm_client, backend, model, tau)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/devices", dependencies=[Depends(require_auth)])
    async def devices() -> dict:
        async with sem:
            try:
                ctrl = await asyncio.to_thread(_fresh_controller)
            except Exception as exc:                       # fail-closed
                raise HTTPException(status_code=502, detail=f"registry build failed: {exc}")
        reg = ctrl.engine.registry
        return {"devices": [{"id": did, "name": reg.get(did).name, "area": reg.get(did).area}
                            for did in reg.device_ids()]}

    # Task 7/8 在本函数内继续追加 /v1/turn、/v1/pending/{id}/reply 路由(闭包共享
    # store / sem / require_auth / _fresh_controller),无需 app.state。
    return app
