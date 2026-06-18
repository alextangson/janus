from __future__ import annotations

from dataclasses import dataclass

from .models import Decision
from .phrasing import _PARAM_ZH, describe_action
from .queries import _ENUM_ZH


@dataclass
class Outcome:
    decision: Decision
    executed: bool
    error: str | None = None
    needs_confirmation: bool = False
    prompt: str | None = None
    choices: list[str] | None = None
    needs_param: bool = False


class Controller:
    """编排:decide → allow 直接执行;confirm 给话术待确认;reject 不动。
    无持久状态:pending 由调用方持有,确认后调 confirm()。执行只经 ha_client。"""

    def __init__(self, engine, ha_client):
        self.engine = engine
        self.ha_client = ha_client

    def handle(self, instruction: str) -> Outcome:
        return self._dispatch(self.engine.decide(instruction))

    def _dispatch(self, decision: Decision) -> Outcome:
        """决定 → Outcome 的唯一映射:allow 执行 / confirm 待确认 / ask 待补参 / 其余不动。"""
        if decision.verdict == "allow":
            return self._execute(decision)
        if decision.verdict == "confirm":
            return Outcome(decision=decision, executed=False, needs_confirmation=True,
                           prompt=self._prompt(decision), choices=decision.candidates or None)
        if decision.verdict == "ask":
            return Outcome(decision=decision, executed=False, needs_param=True,
                           prompt=self._prompt(decision))
        return Outcome(decision=decision, executed=False)  # reject / answer

    def confirm(self, decision: Decision, approved: bool) -> Outcome:
        # 只有真正待确认的 verdict 能被确认执行;answer/reject 等绝不经此放行(纵深防御)。
        if decision.verdict != "confirm":
            return Outcome(decision=decision, executed=False,
                           error=f"该决定无需确认执行(verdict={decision.verdict})")
        if decision.stage == "ambiguous":
            return Outcome(decision=decision, executed=False,
                           error="歧义未消解,请先通过 choose() 选择设备")
        if approved:
            return self._execute(decision)
        return Outcome(decision=decision, executed=False)  # 用户否决

    def choose(self, decision: Decision, device_id: str) -> Outcome:
        """歧义确认后的选择:校验在候选内 → 无 LLM 复审 → 执行/再确认/补参。"""
        if device_id not in decision.candidates:
            return Outcome(decision=decision, executed=False,
                           error=f"所选设备不在候选内:{device_id}")
        resolved = self.engine.decide_resolved(device_id, decision.operation,
                                               dict(decision.params))
        return self._dispatch(resolved)

    def provide_param(self, decision: Decision, value) -> Outcome:
        """反问后接住用户给的值:并入 params → 无 LLM 复审(同 validator 复查范围/危险)→ 执行/再确认。"""
        if decision.verdict != "ask":
            return Outcome(decision=decision, executed=False,
                           error=f"该决定无需补参数(verdict={decision.verdict})")
        params = {**dict(decision.params), decision.missing_param: value}
        resolved = self.engine.decide_resolved(decision.device_id, decision.operation, params)
        return self._dispatch(resolved)

    def control(self, device_id: str, operation: str, params: dict | None = None) -> Outcome:
        """结构化控制(设备页滑块/开关):无 LLM 复审(decide_resolved → 过 validator + 危险闸)→ dispatch。
        allow 直接执行;dangerous → 待确认(随后走 confirm());非法值 → reject;缺必填 → 待补参。"""
        resolved = self.engine.decide_resolved(device_id, operation, params or {})
        return self._dispatch(resolved)

    def _execute(self, decision: Decision) -> Outcome:
        try:
            domain = (decision.device_id or "").split(".")[0]
            self.ha_client.call_service(domain, decision.operation, decision.device_id, dict(decision.params))
            return Outcome(decision=decision, executed=True)
        except Exception as exc:  # 执行失败如实记录,绝不谎报成功
            return Outcome(decision=decision, executed=False, error=str(exc))

    def _prompt(self, decision: Decision) -> str:
        if decision.stage == "ambiguous":
            lines = []
            for i, did in enumerate(decision.candidates, 1):
                device = self.engine.registry.get(did)
                name = device.name if device else did
                area = f"{device.area} " if device and device.area else ""
                lines.append(f"{i}) {area}{name}")
            return "你是说哪一个?" + " ".join(lines)
        if decision.stage == "inferred":
            # 全程代码生成中文动作短语,不把模型自由文本/裸 id/参数字典糊给用户
            return f"💡 要帮你{describe_action(decision, self.engine.registry)}吗?"
        if decision.stage == "param":
            device = self.engine.registry.get(decision.device_id)
            if device is None:
                return f"请提供参数「{decision.missing_param}」的值"
            spec = device.operations[decision.operation].params[decision.missing_param]
            label = _PARAM_ZH.get(decision.missing_param, decision.missing_param)
            if spec.type == "enum":
                opts = "/".join(_ENUM_ZH.get(v, v) for v in (spec.enum or []))
                return f"要把「{device.name}」的{label}设成哪种?({opts})"
            if spec.min is not None and spec.max is not None:
                return f"要把「{device.name}」的{label}设成多少?({spec.min}–{spec.max}{spec.unit or ''})"
            return f"要把「{device.name}」的{label}设成多少?"
        # safety/confidence 等:reason 为代码设定文案(非模型自由文本),可安全展示
        return f"确认{describe_action(decision, self.engine.registry)}?{decision.reason}"
