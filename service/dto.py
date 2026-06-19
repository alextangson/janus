from __future__ import annotations

from gatekeeper.phrasing import describe_action


def _status(outcome) -> str:
    if outcome.error:
        return "error"
    if outcome.executed:
        return "executed"
    if outcome.needs_confirmation:
        return "needs_choice" if outcome.choices else "needs_confirmation"
    if outcome.needs_param:
        return "needs_param"
    if outcome.decision.verdict == "answer":
        return "answer"
    if getattr(outcome, "schedule", None) is not None:
        return "scheduled"
    return "rejected"


def _message(outcome, registry) -> str:
    if outcome.executed:
        return f"已执行:{describe_action(outcome.decision, registry)}"
    if outcome.error:
        return f"失败:{outcome.error}"
    if outcome.prompt:
        return outcome.prompt
    return outcome.decision.reason or ""


def _choices(outcome, registry) -> list[dict] | None:
    if not outcome.choices:
        return None
    out = []
    for did in outcome.choices:
        dev = registry.get(did)
        out.append({"id": did, "label": dev.name if dev else did})
    return out


def outcome_to_dto(outcome, *, conversation_id: str, pending_id: str | None,
                   expires_at: float | None, request_id: str, registry,
                   requires_pin: bool = False) -> dict:
    """Outcome → 稳定 JSON DTO。绝不裸返内部结构;choices 带可读 label。
    requires_pin:该 needs_confirmation 是危险操作且服务端配了 PIN → 客户端须收集 PIN。"""
    d = outcome.decision
    return {
        "status": _status(outcome),
        "conversation_id": conversation_id,
        "pending_id": pending_id,
        "expires_at": expires_at,
        "message": _message(outcome, registry),
        "choices": _choices(outcome, registry),
        "device": d.device_id,
        "operation": d.operation,
        "params": dict(d.params),
        "result": {"executed": outcome.executed, "error": outcome.error},
        "request_id": request_id,
        "requires_pin": requires_pin,
    }
