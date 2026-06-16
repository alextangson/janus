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


# 只有 reason 为代码生成的静态模板的关卡,才把 reason 放进 INFO 摘要(默认拒)。
# query 的 reason 是渲染出的实时设备状态(名字/开关/温度),inferred 的 reason 是模型自由
# 文本(notes)——二者都会泄露作息/房间/安防,绝不进 INFO,只留在 DEBUG 完整行 / 持久化里。
_SAFE_REASON_STAGES = frozenset({
    "parse", "ambiguous", "feasibility", "confidence", "safety", "passed", "error", "param",
})


def summary(rec: DecisionRecord) -> str:
    """脱敏单行(进 _LOGGER INFO):露 device_id + verdict/stage + 执行标记 + 静态 reason 截断,
    绝不含 raw utterance / params 值 / 实时状态 / 模型自由文本。"""
    tail = "✓" if rec.executed else ("✗" if rec.error else "·")
    dev = rec.device_id or "—"
    op = rec.operation or ""
    reason = rec.reason[:40] if rec.stage in _SAFE_REASON_STAGES else ""
    return f"[janus] {rec.verdict}/{rec.stage} {dev} {op} {tail} {reason}".rstrip()


def display_status(row: dict) -> str:
    """决策行 → 展示状态(前端据此映射图标/颜色/中文)。纯函数。
    row 是 DecisionRecord 落盘后的 dict(asdict + ts)。"""
    if row.get("error"):
        return "failed"
    if row.get("executed"):
        return "executed"
    verdict = row.get("verdict")
    if verdict == "reject":
        return "rejected"
    if verdict == "answer":
        return "answered"
    if row.get("pending_after"):
        return "pending"
    return "cancelled"
