"""决策审计的纯数据层:每轮交互 → 一条结构化记录;脱敏摘要供日志。
无 IO、无 HA、无时间戳(时间由落盘的 HA sink 盖),保持可测、确定性。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionRecord:
    utterance: str
    verdict: str
    stage: str
    device_id: str | None
    operation: str | None
    params: dict
    confidence: float
    candidates: list
    missing_param: str | None
    reason: str
    executed: bool
    error: str | None
    pending_after: bool


def build_record(utterance: str, outcome, pending_after: bool) -> DecisionRecord:
    """从 Repl 这一轮的 utterance + Controller 产出的 Outcome 组装记录。鸭子读属性。"""
    d = outcome.decision
    return DecisionRecord(
        utterance=utterance, verdict=d.verdict, stage=d.stage,
        device_id=d.device_id, operation=d.operation, params=dict(d.params),
        confidence=d.confidence, candidates=list(d.candidates),
        missing_param=d.missing_param, reason=d.reason,
        executed=outcome.executed, error=outcome.error, pending_after=pending_after,
    )


def summary(rec: DecisionRecord) -> str:
    """脱敏单行(进 _LOGGER INFO):只露 device_id + verdict/stage + 执行标记 + reason 截断,
    绝不含 raw utterance / params 值(它们泄露作息/房间,只压到 DEBUG 的完整记录)。"""
    tail = "✓" if rec.executed else ("✗" if rec.error else "·")
    dev = rec.device_id or "—"
    op = rec.operation or ""
    return f"[janus] {rec.verdict}/{rec.stage} {dev} {op} {tail} {rec.reason[:40]}".rstrip()
