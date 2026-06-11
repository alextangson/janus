from __future__ import annotations

from .controller import Outcome

_YES = {"y", "yes", "是", "好"}
_NO = {"n", "no", "否", "取消"}


class Repl:
    """纯逻辑 REPL 核心:feed(一行输入) → 一段回复。pending 在这里,Controller 保持无状态。"""

    def __init__(self, controller):
        self.controller = controller
        self.pending: Outcome | None = None

    def feed(self, line: str) -> str:
        line = line.strip()
        if self.pending is not None:
            return self._feed_pending(line)
        if not line:
            return ""
        return self._render(self.controller.handle(line))

    def _feed_pending(self, line: str) -> str:
        pending = self.pending
        if pending.choices:  # 歧义:等序号
            if line.lower() in _NO:
                self.pending = None
                return "已取消"
            if line.isdigit() and 1 <= int(line) <= len(pending.choices):
                self.pending = None
                chosen = pending.choices[int(line) - 1]
                return self._render(self.controller.choose(pending.decision, chosen))
            return pending.prompt or ""  # 没听懂 → 重示
        if line.lower() in _YES:  # 是/否确认
            self.pending = None
            return self._render(self.controller.confirm(pending.decision, approved=True))
        if line.lower() in _NO:
            self.pending = None
            return "已取消"
        return pending.prompt or ""

    def _render(self, outcome: Outcome) -> str:
        if outcome.executed:
            d = outcome.decision
            return f"✅ 已执行:{d.device_id}.{d.operation}"
        if outcome.error:
            return f"❌ 失败:{outcome.error}"
        if outcome.needs_confirmation:  # 含 choose 后链式危险确认
            self.pending = outcome
            return outcome.prompt or ""
        return f"🚫 {outcome.decision.reason or '已取消'}"
