from __future__ import annotations

from dataclasses import dataclass

from .models import Decision


@dataclass
class Outcome:
    decision: Decision
    executed: bool
    error: str | None = None


class Controller:
    """编排:decide → 仅当 allow 时经 ha_client 执行。confirm/reject 不动 HA。"""

    def __init__(self, engine, ha_client):
        self.engine = engine
        self.ha_client = ha_client

    def handle(self, instruction: str) -> Outcome:
        decision = self.engine.decide(instruction)
        if decision.verdict != "allow":
            return Outcome(decision=decision, executed=False)
        try:
            domain = (decision.device_id or "").split(".")[0]
            self.ha_client.call_service(domain, decision.operation, decision.device_id, dict(decision.params))
            return Outcome(decision=decision, executed=True)
        except Exception as exc:  # 执行失败如实记录,绝不谎报成功
            return Outcome(decision=decision, executed=False, error=str(exc))
