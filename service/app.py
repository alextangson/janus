from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from gatekeeper.controller import Outcome
from gatekeeper.models import Decision
from gatekeeper.registry import Registry

from .deadline import DeadlineExceeded, DeadlineHAClient
from .dto import outcome_to_dto
from .engine_factory import build_fresh_controller
from .sessions import ConversationStore


class TurnReq(BaseModel):
    utterance: str
    conversation_id: str | None = None
    idempotency_key: str | None = None


class ReplyReq(BaseModel):
    conversation_id: str
    kind: str                # confirm | choice | param
    value: bool | int | str


def _error_outcome(msg: str) -> Outcome:
    return Outcome(decision=Decision(verdict="reject", stage="error", reason=msg),
                   executed=False, error=msg)


def _empty_registry() -> Registry:
    return Registry({})


def create_app(*, ha_client, llm_client, backend: str, model: str, tau: float,
               api_token: str, request_timeout: float = 30.0,
               max_concurrency: int = 8, store: ConversationStore | None = None,
               controller_factory=None, audit=None) -> FastAPI:
    if not api_token:
        raise RuntimeError("JANUS_API_TOKEN 未设置:拒绝在无认证下启动")
    app = FastAPI(title="Janus", version="1")
    store = store or ConversationStore()
    sem = asyncio.Semaphore(max_concurrency)
    caller = hashlib.sha256(api_token.encode()).hexdigest()[:12]

    def _audit_decision(phase, request_id, cid, utterance, outcome, pending_after):
        if audit is not None:
            audit.record_decision(request_id=request_id, conversation_id=cid, caller=caller,
                                  phase=phase, utterance=utterance, outcome=outcome,
                                  pending_after=pending_after)

    def _audit_lifecycle(event, request_id, cid, device_id, operation):
        if audit is not None:
            audit.record_lifecycle(event=event, request_id=request_id, conversation_id=cid,
                                   caller=caller, device_id=device_id, operation=operation)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {api_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    def _fresh_controller(deadline: float | None = None):
        if controller_factory is not None:
            return controller_factory(deadline=deadline)
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

    @app.post("/v1/turn", dependencies=[Depends(require_auth)])
    async def turn(req: TurnReq) -> dict:
        cid = req.conversation_id or store.new_conversation_id()
        st = store.get_state(cid)
        async with sem:
            async with st.lock:
                if req.idempotency_key:
                    cached = store.idempotent_get(st, req.idempotency_key)
                    if cached is not None:
                        return cached
                old_pending = st.session.pending          # supersede 检测:在 handle 覆盖前捕获
                deadline = time.monotonic() + request_timeout
                request_id = uuid.uuid4().hex
                try:
                    ctrl = await asyncio.to_thread(_fresh_controller, deadline)
                    outcome = await asyncio.wait_for(
                        asyncio.to_thread(st.session.handle, ctrl, req.utterance),
                        timeout=request_timeout)
                except (asyncio.TimeoutError, DeadlineExceeded):
                    store.clear_pending(st)
                    st.session.cancel()       # 出错确定性清会话态(也给 Plan 3 审计留 cancelled 钩子)
                    err = _error_outcome("request timed out")
                    _audit_decision("turn", request_id, cid, req.utterance, err, False)
                    return outcome_to_dto(err, conversation_id=cid,
                                         pending_id=None, expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                except Exception as exc:
                    store.clear_pending(st)
                    st.session.cancel()       # 出错确定性清会话态(也给 Plan 3 审计留 cancelled 钩子)
                    err = _error_outcome(str(exc))
                    _audit_decision("turn", request_id, cid, req.utterance, err, False)
                    return outcome_to_dto(err, conversation_id=cid,
                                         pending_id=None, expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                if old_pending is not None:
                    _audit_lifecycle("superseded", request_id, cid,
                                     old_pending.decision.device_id, old_pending.decision.operation)
                store.clear_pending(st)
                pending_after = outcome.needs_confirmation or outcome.needs_param
                pid = store.issue_pending(st) if pending_after else None
                _audit_decision("turn", request_id, cid, req.utterance, outcome, pending_after)
                dto = outcome_to_dto(outcome, conversation_id=cid, pending_id=pid,
                                     expires_at=st.pending_expires_at, request_id=request_id,
                                     registry=ctrl.engine.registry)
                if req.idempotency_key:
                    store.idempotent_put(st, req.idempotency_key, dto)
                return dto

    @app.post("/v1/pending/{pending_id}/reply", dependencies=[Depends(require_auth)])
    async def reply(pending_id: str, req: ReplyReq) -> dict:
        st = store.get_state(req.conversation_id)
        async with sem:
            async with st.lock:
                expiring = st.session.pending
                is_expired = (st.pending_id == pending_id and st.pending_expires_at is not None
                              and time.time() > st.pending_expires_at)
                if not store.take_pending(st, pending_id):
                    if is_expired and expiring is not None:
                        _audit_lifecycle("expired", uuid.uuid4().hex, req.conversation_id,
                                         expiring.decision.device_id, expiring.decision.operation)
                    raise HTTPException(status_code=409, detail="invalid or expired pending_id")
                deadline = time.monotonic() + request_timeout
                request_id = uuid.uuid4().hex
                try:
                    ctrl = await asyncio.to_thread(_fresh_controller, deadline)
                    outcome = await asyncio.wait_for(
                        asyncio.to_thread(st.session.reply, ctrl, req.kind, req.value),
                        timeout=request_timeout)
                except (asyncio.TimeoutError, DeadlineExceeded):
                    store.clear_pending(st)
                    st.session.cancel()       # 出错确定性清会话态(也给 Plan 3 审计留 cancelled 钩子)
                    err = _error_outcome("request timed out")
                    _audit_decision("reply", request_id, req.conversation_id,
                                    f"{req.kind}:{req.value}", err, False)
                    return outcome_to_dto(err,
                                         conversation_id=req.conversation_id, pending_id=None,
                                         expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                except ValueError as exc:    # 非法 kind:pending 已被 take_pending 烧,清会话态 + 留痕
                    store.clear_pending(st)
                    st.session.cancel()
                    _audit_decision("reply", request_id, req.conversation_id,
                                    f"{req.kind}:{req.value}", _error_outcome(str(exc)), False)
                    raise HTTPException(status_code=400, detail=str(exc))
                except Exception as exc:
                    store.clear_pending(st)
                    st.session.cancel()       # 出错确定性清会话态(也给 Plan 3 审计留 cancelled 钩子)
                    err = _error_outcome(str(exc))
                    _audit_decision("reply", request_id, req.conversation_id,
                                    f"{req.kind}:{req.value}", err, False)
                    return outcome_to_dto(err,
                                         conversation_id=req.conversation_id, pending_id=None,
                                         expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                pending_after = outcome.needs_confirmation or outcome.needs_param
                pid = store.issue_pending(st) if pending_after else None
                _audit_decision("reply", request_id, req.conversation_id,
                                f"{req.kind}:{req.value}", outcome, pending_after)
                return outcome_to_dto(outcome, conversation_id=req.conversation_id, pending_id=pid,
                                      expires_at=st.pending_expires_at, request_id=request_id,
                                      registry=ctrl.engine.registry)

    @app.get("/v1/audit", dependencies=[Depends(require_auth)])
    def get_audit(limit: int = 50) -> dict:
        if audit is None:
            return {"records": []}
        return {"records": audit.recent(limit=limit)}

    return app
