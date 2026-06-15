from __future__ import annotations

from typing import Callable, Protocol

from .models import Decision, ParseResult
from .queries import answer_query
from .registry import Registry
from .validator import check_feasibility, missing_required_param


class Parser(Protocol):
    def parse(self, instruction: str) -> ParseResult: ...


class Engine:
    def __init__(self, parser: Parser, registry: Registry, tau: float,
                 state_provider: Callable[[], list] | None = None):
        self.parser = parser
        self.registry = registry
        self.tau = tau
        self.state_provider = state_provider

    def _feasibility_decision(self, parse: ParseResult, base: dict) -> Decision | None:
        """可行性关卡:无问题→None;唯一问题是缺必填参数→ask;其余→reject。"""
        problem = check_feasibility(parse, self.registry)
        if not problem:
            return None
        missing = missing_required_param(parse, self.registry)
        if missing is not None:
            return Decision(verdict="ask", stage="param", missing_param=missing,
                            reason="缺少必填参数,需向用户询问", **base)
        return Decision(verdict="reject", stage="feasibility", reason=problem, **base)

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

        if parse.query:
            try:
                states = self.state_provider() if self.state_provider else []
            except Exception:
                states = []  # 查询只读,读不到状态不危险,优雅降级
            return Decision(verdict="answer", stage="query",
                            reason=answer_query(parse.device_id, parse.candidates,
                                                states, self.registry), **base)

        if parse.candidates:
            valid = [c for c in parse.candidates
                     if (dev := self.registry.get(c)) and parse.operation in dev.operations]
            if len(valid) >= 2:
                return Decision(verdict="confirm", stage="ambiguous", candidates=valid,
                                reason="多台设备匹配,需要选择",
                                **{**base, "device_id": None})  # 歧义未消解,不携带模型偏好
            if not valid:
                return Decision(verdict="reject", stage="parse",
                                reason="没识别出对应的设备或操作", **base)
            # 唯一有效候选 → 当作普通解析,继续走 feasibility/τ/safety
            parse = parse.model_copy(update={"device_id": valid[0], "candidates": []})
            base["device_id"] = valid[0]

        fd = self._feasibility_decision(parse, base)
        if fd is not None:
            return fd

        if parse.inferred:
            # 推断的意图永远到不了 allow:模型只有提议权,执行权在用户。
            return Decision(verdict="confirm", stage="inferred",
                            reason=parse.notes or "已根据当前状态推断该操作,请确认", **base)

        if parse.confidence < self.tau:
            return Decision(
                verdict="confirm", stage="confidence",
                reason=f"理解把握不足(置信度 {parse.confidence} < τ {self.tau}),请核对", **base,
            )

        if self.registry.is_dangerous(parse.device_id, parse.operation):
            return Decision(verdict="confirm", stage="safety", reason="该操作敏感/不可逆,执行前需确认", **base)

        return Decision(verdict="allow", stage="passed", reason="正常安全操作", **base)

    def decide_resolved(self, device_id: str, operation: str | None,
                        params: dict | None = None) -> Decision:
        """用户已明确选定设备后的无 LLM 复审:只走可行性 + 危险关卡(跳过解析与 τ)。"""
        parse = ParseResult(recognized=True, device_id=device_id, operation=operation,
                            params=params or {}, confidence=1.0)
        base = dict(device_id=device_id, operation=operation,
                    params=parse.params, confidence=1.0)
        fd = self._feasibility_decision(parse, base)
        if fd is not None:
            return fd
        if self.registry.is_dangerous(device_id, operation):
            return Decision(verdict="confirm", stage="safety",
                            reason="该操作敏感/不可逆,执行前需确认", **base)
        return Decision(verdict="allow", stage="passed", reason="正常安全操作", **base)
