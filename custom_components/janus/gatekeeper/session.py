from __future__ import annotations

from .controller import Outcome


class NoPendingError(RuntimeError):
    """reply() 被调用时没有待确认决定(调用方应先确认存在 pending)。"""


class Session:
    """纯多轮核:持 pending,把结构化答复 dispatch 到 Controller。
    零渲染、零 HA、零 IO。controller 每轮由调用方传入(支持每轮重建)。
    pending 是唯一会话态;Engine/Controller 仍无状态。
    答复必须结构化(kind+value),绝不从自由文本推断高危批准——
    口语解析(affirmation/choice_index/coerce_param)是调用方(CLI/app)的职责。"""

    def __init__(self) -> None:
        self.pending: Outcome | None = None

    def handle(self, controller, utterance: str) -> Outcome:
        """新指令:转发给 Controller(解析+过闸在那里),并据结果更新 pending。"""
        return self._track(controller.handle(utterance))

    def reply(self, controller, kind: str, value) -> Outcome:
        """结构化答复当前 pending。kind ∈ {confirm, choice, param}。
        confirm: value=bool;choice: value=device_id;param: value=已规范化的参数值。
        无 pending → NoPendingError;未知 kind → ValueError。
        各 Controller 方法自带状态守卫(verdict/候选校验),此处不重复。"""
        if self.pending is None:
            raise NoPendingError("no pending decision to reply to")
        dec = self.pending.decision
        if kind == "confirm":
            out = controller.confirm(dec, approved=bool(value))
        elif kind == "choice":
            out = controller.choose(dec, value)
        elif kind == "param":
            out = controller.provide_param(dec, value)
        else:
            raise ValueError(f"unknown reply kind: {kind!r}")
        return self._track(out)

    def control(self, controller, device_id: str, operation: str, params: dict | None = None) -> Outcome:
        """结构化控制入口(无 LLM)。与 handle 对称:转发 Controller.control 并据结果更新 pending。
        危险操作产生的 pending 由调用方发 pending_id,后续走与 turn 同一条 reply 通道确认。"""
        return self._track(controller.control(device_id, operation, params))

    def cancel(self) -> None:
        """清空 pending(用户取消 / 被新指令覆盖 / 过期)。清 pending 的唯一权威入口。"""
        self.pending = None

    def _track(self, outcome: Outcome) -> Outcome:
        """待确认/待补参的结果留作 pending;其余(执行/拒绝/答询/错误)清空。"""
        self.pending = outcome if (outcome.needs_confirmation or outcome.needs_param) else None
        return outcome
