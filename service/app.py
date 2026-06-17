from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gatekeeper.controller import Outcome
from gatekeeper.models import Decision
from gatekeeper.registry import Registry

from .deadline import DeadlineExceeded, DeadlineHAClient
from .device_dto import device_state, device_to_dto
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


class ControlReq(BaseModel):
    device_id: str
    operation: str
    params: dict[str, bool | int | str] = {}
    conversation_id: str | None = None
    idempotency_key: str | None = None


class SettingsReq(BaseModel):
    tau: float = Field(ge=0.0, le=1.0)


def _error_outcome(msg: str) -> Outcome:
    return Outcome(decision=Decision(verdict="reject", stage="error", reason=msg),
                   executed=False, error=msg)


def _empty_registry() -> Registry:
    return Registry({})


def create_app(*, ha_client, llm_client, backend: str, model: str, tau: float,
               api_token: str, request_timeout: float = 30.0,
               max_concurrency: int = 8, store: ConversationStore | None = None,
               controller_factory=None, audit=None,
               cors_origins: list[str] | None = None) -> FastAPI:
    if not api_token:
        raise RuntimeError("JANUS_API_TOKEN 未设置:拒绝在无认证下启动")
    app = FastAPI(title="Janus", version="1")
    # Web app(浏览器)跨域调用需要 CORS。Janus 用 bearer(非 cookie),故 allow_origins=*
    # 对这种 API 安全(攻击页拿不到 token);可用 JANUS_CORS_ORIGINS 收紧到具体源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    store = store or ConversationStore()
    tau_box = {"value": tau}
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
        return build_fresh_controller(ha, llm_client, backend, model, tau_box["value"])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/devices", dependencies=[Depends(require_auth)])
    async def devices() -> dict:
        async with sem:
            try:
                ctrl = await asyncio.to_thread(_fresh_controller)
                # state_provider 再打一次 HA 取实时状态:与 registry 构建分两次调用,
                # 是低频端点上的有意取舍,非 bug。
                state_provider = getattr(ctrl.engine, "state_provider", None)
                ha_states = await asyncio.to_thread(state_provider) if state_provider else []
            except Exception as exc:                       # fail-closed
                raise HTTPException(status_code=502, detail=f"registry build failed: {exc}")
        reg = ctrl.engine.registry
        by_id = {s["entity_id"]: s for s in ha_states
                 if isinstance(s, dict) and s.get("entity_id")}
        out = []
        for did in reg.device_ids():
            dev = reg.get(did)
            raw = by_id.get(did)
            state = device_state(dev.type, raw.get("state", ""), raw.get("attributes") or {}) if raw else {}
            out.append(device_to_dto(did, dev, state))
        return {"devices": out}

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

    @app.post("/v1/control", dependencies=[Depends(require_auth)])
    async def control(req: ControlReq) -> dict:
        cid = req.conversation_id or store.new_conversation_id()
        st = store.get_state(cid)
        descriptor = f"{req.device_id}.{req.operation}"      # 审计 utterance:无 NL,用结构化标识
        async with sem:
            async with st.lock:
                if req.idempotency_key:
                    cached = store.idempotent_get(st, req.idempotency_key)
                    if cached is not None:
                        return cached
                old_pending = st.session.pending          # supersede 检测:在 control 覆盖前捕获
                deadline = time.monotonic() + request_timeout
                request_id = uuid.uuid4().hex
                try:
                    ctrl = await asyncio.to_thread(_fresh_controller, deadline)
                    outcome = await asyncio.wait_for(
                        asyncio.to_thread(st.session.control, ctrl, req.device_id,
                                          req.operation, dict(req.params)),
                        timeout=request_timeout)
                except (asyncio.TimeoutError, DeadlineExceeded):
                    store.clear_pending(st)
                    st.session.cancel()
                    err = _error_outcome("request timed out")
                    _audit_decision("control", request_id, cid, descriptor, err, False)
                    return outcome_to_dto(err, conversation_id=cid, pending_id=None,
                                         expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                except Exception as exc:
                    store.clear_pending(st)
                    st.session.cancel()
                    err = _error_outcome(str(exc))
                    _audit_decision("control", request_id, cid, descriptor, err, False)
                    return outcome_to_dto(err, conversation_id=cid, pending_id=None,
                                         expires_at=None, request_id=request_id,
                                         registry=_empty_registry())
                if old_pending is not None:
                    _audit_lifecycle("superseded", request_id, cid,
                                     old_pending.decision.device_id, old_pending.decision.operation)
                store.clear_pending(st)
                pending_after = outcome.needs_confirmation or outcome.needs_param
                pid = store.issue_pending(st) if pending_after else None
                _audit_decision("control", request_id, cid, descriptor, outcome, pending_after)
                dto = outcome_to_dto(outcome, conversation_id=cid, pending_id=pid,
                                     expires_at=st.pending_expires_at, request_id=request_id,
                                     registry=ctrl.engine.registry)
                if req.idempotency_key:
                    store.idempotent_put(st, req.idempotency_key, dto)
                return dto

    @app.get("/v1/settings", dependencies=[Depends(require_auth)])
    def get_settings() -> dict:
        return {"tau": tau_box["value"]}

    @app.put("/v1/settings", dependencies=[Depends(require_auth)])
    def put_settings(req: SettingsReq) -> dict:
        tau_box["value"] = req.tau
        return {"tau": tau_box["value"]}

    @app.get("/v1/audit", dependencies=[Depends(require_auth)])
    def get_audit(limit: int = 50) -> dict:
        if audit is None:
            return {"records": []}
        return {"records": audit.recent(limit=limit)}

    return app
