from __future__ import annotations

from dataclasses import dataclass

from .models import Decision


@dataclass
class Outcome:
    decision: Decision
    executed: bool
    error: str | None = None
    needs_confirmation: bool = False
    prompt: str | None = None
    choices: list[str] | None = None


class Controller:
    """编排:decide → allow 直接执行;confirm 给话术待确认;reject 不动。
    无持久状态:pending 由调用方持有,确认后调 confirm()。执行只经 ha_client。"""

    def __init__(self, engine, ha_client):
        self.engine = engine
        self.ha_client = ha_client

    def handle(self, instruction: str) -> Outcome:
        decision = self.engine.decide(instruction)
        if decision.verdict == "allow":
            return self._execute(decision)
        if decision.verdict == "confirm":
            return Outcome(decision=decision, executed=False,
                           needs_confirmation=True, prompt=self._prompt(decision),
                           choices=decision.candidates or None)
        return Outcome(decision=decision, executed=False)  # reject

    def confirm(self, decision: Decision, approved: bool) -> Outcome:
        if decision.stage == "ambiguous":
            return Outcome(decision=decision, executed=False,
                           error="歧义未消解,请先通过 choose() 选择设备")
        if approved:
            return self._execute(decision)
        return Outcome(decision=decision, executed=False)  # 用户否决

    def choose(self, decision: Decision, device_id: str) -> Outcome:
        """歧义确认后的选择:校验在候选内 → 无 LLM 复审 → 执行/再确认。"""
        if device_id not in decision.candidates:
            return Outcome(decision=decision, executed=False,
                           error=f"所选设备不在候选内:{device_id}")
        resolved = self.engine.decide_resolved(device_id, decision.operation,
                                               dict(decision.params))
        if resolved.verdict == "allow":
            return self._execute(resolved)
        if resolved.verdict == "confirm":
            return Outcome(decision=resolved, executed=False,
                           needs_confirmation=True, prompt=self._prompt(resolved))
        return Outcome(decision=resolved, executed=False)

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
            return (f"💡 {decision.reason.rstrip('。')}。确认执行"
                    f"「{decision.operation} → {decision.device_id}」({dict(decision.params)})吗?")
        return f"确认执行「{decision.operation} → {decision.device_id}」?{decision.reason}"
