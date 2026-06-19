from __future__ import annotations

from typing import Callable, Protocol

from .models import Decision, ParseResult, ScheduleIntent
from .queries import answer_query
from .registry import Registry
from .validator import check_feasibility, missing_required_param


class Parser(Protocol):
    def parse(self, instruction: str) -> ParseResult: ...


def _valid_intent(intent: ScheduleIntent) -> bool:
    """排程描述符是否完整自洽。纯函数,不碰设备/模型。
    三类合法:相对一次性、绝对一次性、周期。任何字段冲突或越界都判废。"""
    if intent.kind == "once":
        if (intent.relative_seconds is not None and intent.relative_seconds > 0
                and intent.hour is None and intent.minute is None
                and intent.recurrence is None):
            return True
        if (intent.hour is not None and 0 <= intent.hour <= 23
                and intent.minute is not None and 0 <= intent.minute <= 59
                and intent.relative_seconds is None and intent.recurrence is None):
            return True
        return False
    if intent.kind == "recurring":
        return (intent.hour is not None and 0 <= intent.hour <= 23
                and intent.minute is not None and 0 <= intent.minute <= 59
                and intent.recurrence in {"daily", "weekday", "weekend"}
                and intent.relative_seconds is None)
    return False


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

        if parse.schedule is not None:
            # 定时自带消歧/校验/过闸:不走普通多轮歧义确认,只放行干净的 allow。
            return self._decide_schedule(parse, base)

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
                            dangerous=self.registry.is_dangerous(parse.device_id, parse.operation),
                            reason=parse.notes or "已根据当前状态推断该操作,请确认", **base)

        if parse.confidence < self.tau:
            return Decision(
                verdict="confirm", stage="confidence",
                dangerous=self.registry.is_dangerous(parse.device_id, parse.operation),
                reason=f"理解把握不足(置信度 {parse.confidence} < τ {self.tau}),请核对", **base,
            )

        if self.registry.is_dangerous(parse.device_id, parse.operation):
            return Decision(verdict="confirm", stage="safety", dangerous=True,
                            reason="该操作敏感/不可逆,执行前需确认", **base)

        return Decision(verdict="allow", stage="passed", reason="正常安全操作", **base)

    def _decide_schedule(self, parse: ParseResult, base: dict) -> Decision:
        """排程关卡:校验描述符 → 消歧(单轮)→ 复用动作闸,只放行干净 allow。
        malformed/危险/缺参/歧义全部 reject,绝不携带 schedule、绝不多轮反问。"""
        if not _valid_intent(parse.schedule):
            return Decision(verdict="reject", stage="feasibility",
                            reason="没听清定时时间,说得具体些", **base)

        if parse.device_id:
            device_id = parse.device_id
        elif parse.candidates:
            valid = [c for c in parse.candidates
                     if (dev := self.registry.get(c)) and parse.operation in dev.operations]
            if len(valid) != 1:
                return Decision(verdict="reject", stage="ambiguous",
                                reason="定时请说清是哪个设备", **{**base, "device_id": None})
            device_id = valid[0]
            base = {**base, "device_id": device_id}
        else:
            return Decision(verdict="reject", stage="parse",
                            reason="没识别出对应的设备或操作", **base)

        d = self.decide_resolved(device_id, parse.operation, parse.params)
        if d.verdict != "allow":
            # 非危险拒绝用固定安全话术,绝不透传 d.reason —— 它可能含原始 entity_id/op。
            reason = ("定时不支持开锁、撤防这类敏感操作" if d.dangerous
                      else "定时需要明确、可执行的设备和参数(比如说清几度、哪个设备)")
            return Decision(verdict="reject", stage=d.stage, reason=reason,
                            device_id=device_id, operation=parse.operation,
                            params=parse.params, confidence=1.0)

        return Decision(verdict="allow", stage="passed", device_id=device_id,
                        operation=parse.operation, params=parse.params,
                        confidence=1.0, reason="已安排定时", schedule=parse.schedule)

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
            return Decision(verdict="confirm", stage="safety", dangerous=True,
                            reason="该操作敏感/不可逆,执行前需确认", **base)
        return Decision(verdict="allow", stage="passed", reason="正常安全操作", **base)
