from __future__ import annotations

from typing import Protocol

from .models import Decision, ParseResult
from .registry import Registry
from .validator import check_feasibility


class Parser(Protocol):
    def parse(self, instruction: str) -> ParseResult: ...


class Engine:
    def __init__(self, parser: Parser, registry: Registry, tau: float):
        self.parser = parser
        self.registry = registry
        self.tau = tau

    def decide(self, instruction: str) -> Decision:
        try:
            parse = self.parser.parse(instruction)
        except Exception:
            # fail closed:任何模型/系统故障都绝不放行
            return Decision(verdict="reject", stage="error", reason="系统暂时无法判断,未执行")

        base = dict(
            device_id=parse.device_id,
            operation=parse.operation,
            params=parse.params,
            confidence=parse.confidence,
        )

        if not parse.recognized:
            return Decision(verdict="reject", stage="parse", reason="没识别出对应的设备或操作", **base)

        problem = check_feasibility(parse, self.registry)
        if problem:
            return Decision(verdict="reject", stage="feasibility", reason=problem, **base)

        if parse.confidence < self.tau:
            return Decision(
                verdict="confirm", stage="confidence",
                reason=f"理解把握不足(置信度 {parse.confidence} < τ {self.tau}),请核对", **base,
            )

        if self.registry.is_dangerous(parse.device_id, parse.operation):
            return Decision(verdict="confirm", stage="safety", reason="该操作敏感/不可逆,执行前需确认", **base)

        return Decision(verdict="allow", stage="passed", reason="正常安全操作", **base)
