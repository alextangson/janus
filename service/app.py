from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from contextlib import asynccontextmanager

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
from .pin_store import PinStore
from .schedule_store import ScheduleEntry, ScheduleLimitExceeded, ScheduleStore
from .schedule_time import compute_next_fire
from .sessions import ConversationStore


class TurnReq(BaseModel):
    utterance: str
    conversation_id: str | None = None
    idempotency_key: str | None = None


class ReplyReq(BaseModel):
    conversation_id: str
    kind: str                # confirm | choice | param
    value: bool | int | str
    pin: str | None = None   # 危险操作第二因子;仅 kind=confirm 且 decision.dangerous 时服务端强制


class ControlReq(BaseModel):
    device_id: str
    operation: str
    params: dict[str, bool | int | str] = {}
    conversation_id: str | None = None
    idempotency_key: str | None = None


class SettingsReq(BaseModel):
    tau: float = Field(ge=0.0, le=1.0)


class SecurityPinReq(BaseModel):
    current_pin: str = ""
    new_pin: str


class ScheduleCreateReq(BaseModel):
    device_id: str
    operation: str
    params: dict[str, bool | int | str] = {}
    kind: str                       # "once" | "recurring"
    at: float | None = None
    minute_of_day: int | None = None
    days: list[int] | None = None


class SchedulePatchReq(BaseModel):
    enabled: bool


def _error_outcome(msg: str) -> Outcome:
    return Outcome(decision=Decision(verdict="reject", stage="error", reason=msg),
                   executed=False, error=msg)


def _empty_registry() -> Registry:
    return Registry({})


def create_app(*, ha_client, llm_client, backend: str, model: str, tau: float,
               api_token: str, dangerous_pin: str = "", pin_store: PinStore | None = None,
               request_timeout: float = 30.0,
               max_concurrency: int = 8, store: ConversationStore | None = None,
               controller_factory=None, audit=None,
               cors_origins: list[str] | None = None,
               schedule_store: ScheduleStore | None = None,
               default_tz: str = "Asia/Shanghai", scheduler=None) -> FastAPI:
    if not api_token:
        raise RuntimeError("JANUS_API_TOKEN 未设置:拒绝在无认证下启动")
    # 向后兼容:仅给 dangerous_pin(块 A)→ 构 env-only 内存 store(无持久路径,管理端点禁用)
    pin_store = pin_store or PinStore(env_pin=dangerous_pin, path=None)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # scheduler is None(默认/现有测试)→ 全程 no-op,绝不起后台循环。
        if scheduler is not None:
            scheduler.start()  # 自门控 owner 锁:只有持锁者真正跑循环
        yield
        if scheduler is not None:
            await scheduler.stop()

    app = FastAPI(title="Janus", version="1", lifespan=_lifespan)
    # Web app(浏览器)跨域调用需要 CORS。Janus 用 bearer(非 cookie),故 allow_origins=*
    # 对这种 API 安全(攻击页拿不到 token);可用 JANUS_CORS_ORIGINS 收紧到具体源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
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

    def _requires_pin(outcome) -> bool:
        # 危险操作 + 配了 PIN 的 needs_confirmation → 客户端须收集 PIN
        return pin_store.is_configured() and outcome.needs_confirmation and outcome.decision.dangerous

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
                                     registry=ctrl.engine.registry, requires_pin=_requires_pin(outcome))
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
                # 危险操作第二因子:对危险 confirm(approve)强制 PIN。bool(req.value) 与 controller
                # approved=bool(value) 一致,堵 "1"/"yes" 绕过;按 decision.dangerous 非 stage,堵
                # 危险且低置信/推断 绕过。pending 已被 take_pending 烧 → 错 PIN 须重发 control(防爆破)。
                needs_pin = (pin_store.is_configured() and expiring is not None
                             and expiring.decision.dangerous
                             and req.kind == "confirm" and bool(req.value))
                if needs_pin and not pin_store.verify(req.pin):
                    store.clear_pending(st)
                    st.session.cancel()      # take_pending 只清 id,这里清 session.pending 防 stale
                    err = _error_outcome("PIN 校验失败")
                    _audit_decision("reply", request_id, req.conversation_id, f"{req.kind}:pin", err, False)
                    raise HTTPException(status_code=403, detail="PIN required or incorrect")
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
                                      registry=ctrl.engine.registry, requires_pin=_requires_pin(outcome))

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
                                     registry=ctrl.engine.registry, requires_pin=_requires_pin(outcome))
                if req.idempotency_key:
                    store.idempotent_put(st, req.idempotency_key, dto)
                return dto

    @app.get("/v1/settings", dependencies=[Depends(require_auth)])
    def get_settings() -> dict:
        return {"tau": tau_box["value"]}

    @app.put("/v1/settings", dependencies=[Depends(require_auth)])
    def put_settings(req: SettingsReq) -> dict:
        tau_box["value"] = req.tau
        return {"tau": req.tau}

    @app.get("/v1/audit", dependencies=[Depends(require_auth)])
    def get_audit(limit: int = 50) -> dict:
        if audit is None:
            return {"records": []}
        return {"records": audit.recent(limit=limit)}

    @app.get("/v1/security/pin", dependencies=[Depends(require_auth)])
    def get_security_pin() -> dict:
        return {"configured": pin_store.is_configured()}

    @app.put("/v1/security/pin", dependencies=[Depends(require_auth)])
    def put_security_pin(req: SecurityPinReq) -> dict:
        # 无持久路径(env-only/向后兼容)→ 管理禁用
        if not pin_store.has_durable_path():
            raise HTTPException(status_code=501, detail="PIN management not available")
        # 无活跃 PIN → 不可从 app 凭空设(消除接管窗口);须先服务端 env 引导
        if not pin_store.is_configured():
            raise HTTPException(status_code=409, detail="no PIN to rotate; bootstrap JANUS_DANGEROUS_PIN first")
        if pin_store.change_locked() > 0:
            raise HTTPException(status_code=429, detail="too many attempts; locked")
        if not pin_store.verify_for_change(req.current_pin):
            err = _error_outcome("PIN 改密旧 PIN 校验失败")
            _audit_decision("security", uuid.uuid4().hex, "", "pin_change", err, False)
            raise HTTPException(status_code=403, detail="current PIN incorrect")
        if len(req.new_pin) < 6:
            raise HTTPException(status_code=400, detail="new PIN must be at least 6 characters")
        pin_store.set(req.new_pin)
        return {"configured": True}

    def _require_schedule_store() -> ScheduleStore:
        if schedule_store is None:
            raise HTTPException(status_code=503, detail="schedules not available")
        return schedule_store

    @app.post("/v1/schedules", status_code=201, dependencies=[Depends(require_auth)])
    async def create_schedule(req: ScheduleCreateReq) -> dict:
        # 形状校验先于 store/gate:无效请求不应触达后端。
        if req.kind not in ("once", "recurring"):
            raise HTTPException(status_code=422, detail="kind must be once or recurring")
        if req.kind == "once":
            if req.at is None:
                raise HTTPException(status_code=422, detail="once 需要 at")
        else:  # recurring
            if req.minute_of_day is None or not (0 <= req.minute_of_day <= 1439):
                raise HTTPException(status_code=422, detail="minute_of_day 须在 0..1439")
            if not req.days or not all(isinstance(d, int) and 0 <= d <= 6 for d in req.days):
                raise HTTPException(status_code=422, detail="days 须为非空的 0..6 列表")
        sched = _require_schedule_store()
        # 建时闸:仅校验不执行(decide_resolved),非 allow → 拒建(危险→confirm、不可行→reject)。
        ctrl = await asyncio.to_thread(_fresh_controller)
        decision = ctrl.engine.decide_resolved(req.device_id, req.operation, dict(req.params))
        if decision.verdict != "allow":
            raise HTTPException(status_code=422, detail=decision.reason)
        next_fire_at = compute_next_fire(kind=req.kind, at=req.at,
                                         minute_of_day=req.minute_of_day, days=req.days,
                                         tz_name=default_tz, after=time.time())
        if next_fire_at is None:
            raise HTTPException(status_code=422, detail="无可触发时刻")
        entry = ScheduleEntry(
            id=uuid.uuid4().hex, device_id=req.device_id, operation=req.operation,
            params=dict(req.params), kind=req.kind, at=req.at,
            minute_of_day=req.minute_of_day, days=req.days, tz=default_tz,
            enabled=True, next_fire_at=next_fire_at, created_at=time.time())
        try:
            sched.add(entry)
        except ScheduleLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        _audit_lifecycle("schedule_created", uuid.uuid4().hex, f"schedule:{entry.id}",
                         entry.device_id, entry.operation)
        return {"id": entry.id, "next_fire_at": entry.next_fire_at}

    @app.get("/v1/schedules", dependencies=[Depends(require_auth)])
    def list_schedules() -> dict:
        sched = _require_schedule_store()
        return {"schedules": [e.to_dict() for e in sched.list()]}

    @app.delete("/v1/schedules/{sid}", dependencies=[Depends(require_auth)])
    def delete_schedule(sid: str) -> dict:
        sched = _require_schedule_store()
        if not sched.remove(sid):
            raise HTTPException(status_code=404, detail="schedule not found")
        return {"ok": True}

    @app.patch("/v1/schedules/{sid}", dependencies=[Depends(require_auth)])
    def patch_schedule(sid: str, req: SchedulePatchReq) -> dict:
        sched = _require_schedule_store()
        entry = sched.get(sid)
        if entry is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        entry.enabled = req.enabled
        # 重新启用一个已无下次触发时刻的 recurring → 重算,避免被禁用期错过后永不触发。
        if req.enabled and entry.kind == "recurring" and entry.next_fire_at is None:
            entry.next_fire_at = compute_next_fire(
                kind=entry.kind, at=entry.at, minute_of_day=entry.minute_of_day,
                days=entry.days, tz_name=entry.tz, after=time.time())
        sched.update(entry)
        return entry.to_dict()

    return app
