import pytest

from gatekeeper.controller import Controller, Outcome
from gatekeeper.models import Decision, Device, OperationSpec
from gatekeeper.registry import Registry
from gatekeeper.session import NoPendingError, Session


class StubHA:
    def __init__(self):
        self.calls = []

    def call_service(self, domain, service, entity_id, params=None):
        self.calls.append((domain, service, entity_id, params))
        return {"ok": True}


class FakeEngine:
    """decide 返回预设 decision;decide_resolved 返回预设 resolved。"""

    def __init__(self, decision=None, resolved=None, registry=None):
        self._d = decision
        self._resolved = resolved
        self.registry = registry

    def decide(self, instruction):
        return self._d

    def decide_resolved(self, device_id, operation, params=None):
        return self._resolved


def _reg():
    op = {"turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=op),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=op),
    })


def _allow(device="light.a", op="turn_off"):
    return Decision(verdict="allow", stage="passed", device_id=device, operation=op, params={})


def _ctrl(decision=None, resolved=None):
    ha = StubHA()
    return Controller(FakeEngine(decision, resolved, _reg()), ha), ha


def test_handle_allow_executes_and_clears_pending():
    ctrl, ha = _ctrl(_allow())
    sess = Session()
    out = sess.handle(ctrl, "关灯")
    assert out.executed is True
    assert ha.calls == [("light", "turn_off", "light.a", {})]
    assert sess.pending is None


def test_handle_confirm_sets_pending():
    danger = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                      operation="unlock", params={}, reason="敏感操作需确认")
    ctrl, ha = _ctrl(danger)
    sess = Session()
    out = sess.handle(ctrl, "开锁")
    assert out.needs_confirmation is True
    assert sess.pending is out
    assert ha.calls == []


def test_reply_confirm_true_executes():
    danger = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                      operation="unlock", params={}, reason="敏感操作需确认")
    ctrl, ha = _ctrl(danger)
    sess = Session()
    sess.handle(ctrl, "开锁")
    out = sess.reply(ctrl, "confirm", True)
    assert out.executed is True
    assert ha.calls == [("lock", "unlock", "lock.door", {})]
    assert sess.pending is None


def test_reply_choice_resolves_against_candidate():
    amb = Decision(verdict="confirm", stage="ambiguous", operation="turn_off", params={},
                   candidates=["light.a", "light.b"], reason="多台匹配")
    ctrl, ha = _ctrl(amb, resolved=_allow("light.b"))
    sess = Session()
    sess.handle(ctrl, "关卧室灯")
    out = sess.reply(ctrl, "choice", "light.b")
    assert out.executed is True
    assert ha.calls == [("light", "turn_off", "light.b", {})]
    assert sess.pending is None


def test_reply_confirm_false_clears_pending():
    # 用户否决待确认(常是危险操作):不执行,且 pending 必须清空(会话重置)
    danger = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                      operation="unlock", params={}, reason="敏感操作需确认")
    ctrl, ha = _ctrl(danger)
    sess = Session()
    sess.handle(ctrl, "开锁")
    out = sess.reply(ctrl, "confirm", False)
    assert out.executed is False
    assert ha.calls == []
    assert sess.pending is None


def test_reply_param_on_missing_device_rejects_not_crash():
    """服务关键不变量:设备 T0→T1 消失时,结构化 param reply 走 decide_resolved
    返回拒绝,绝不解引用注册表而抛异常(对照 cli.py 口语 param 分支的旧 bug)。"""
    ask = Decision(verdict="ask", stage="param", device_id="climate.gone",
                   operation="set_temperature", params={}, missing_param="temperature",
                   reason="缺参数")
    reject = Decision(verdict="reject", stage="feasibility", device_id="climate.gone",
                      operation="set_temperature", params={"temperature": 26},
                      reason="设备不存在")
    ctrl, ha = _ctrl(ask, resolved=reject)
    sess = Session()
    sess.handle(ctrl, "调温度")
    out = sess.reply(ctrl, "param", 26)          # 不得抛
    assert out.executed is False
    assert out.decision.verdict == "reject"
    assert ha.calls == []
    assert sess.pending is None


def test_reply_without_pending_raises():
    ctrl, _ = _ctrl(_allow())
    sess = Session()
    with pytest.raises(NoPendingError):
        sess.reply(ctrl, "confirm", True)


def test_reply_unknown_kind_raises():
    danger = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                      operation="unlock", params={}, reason="敏感")
    ctrl, _ = _ctrl(danger)
    sess = Session()
    sess.handle(ctrl, "开锁")
    with pytest.raises(ValueError):
        sess.reply(ctrl, "bogus", True)


def test_cancel_clears_pending():
    # 取消 / 被新指令覆盖 / 过期:Session 是清 pending 的唯一权威入口
    danger = Decision(verdict="confirm", stage="safety", device_id="lock.door",
                      operation="unlock", params={}, reason="敏感")
    ctrl, _ = _ctrl(danger)
    sess = Session()
    sess.handle(ctrl, "开锁")
    assert sess.pending is not None
    sess.cancel()
    assert sess.pending is None
