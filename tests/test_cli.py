from gatekeeper.cli import Repl, coerce_param
from gatekeeper.controller import Controller
from gatekeeper.models import Decision, Device, OperationSpec, ParamSpec
from gatekeeper.registry import Registry


class StubHA:
    def __init__(self, raise_exc=None):
        self.calls = []
        self._raise = raise_exc

    def call_service(self, domain, service, entity_id, params=None):
        self.calls.append((domain, service, entity_id, params))
        if self._raise:
            raise self._raise
        return {"ok": True}


class FakeEngine:
    """decide/decide_resolved 返回预设;registry 供歧义话术渲染。"""

    def __init__(self, decision, resolved=None, registry=None):
        self._d = decision
        self._resolved = resolved
        self.registry = registry

    def decide(self, instruction):
        return self._d

    def decide_resolved(self, device_id: str, operation: str | None,
                        params: dict | None = None) -> Decision:
        return self._resolved


def _registry():
    op = {"turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=op),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=op),
    })


def _mk(decision, resolved=None, raise_exc=None):
    ha = StubHA(raise_exc=raise_exc)
    eng = FakeEngine(decision, resolved=resolved, registry=_registry())
    return Repl(Controller(eng, ha)), ha


def _allow(device="light.a", op="turn_off"):
    return Decision(verdict="allow", stage="passed", device_id=device, operation=op, params={})


def _amb(**kw):
    base = {"verdict": "confirm", "stage": "ambiguous", "operation": "turn_off", "params": {},
            "candidates": ["light.a", "light.b"], "reason": "多台设备匹配"}
    base.update(kw)
    return Decision(**base)


def _danger():
    return Decision(verdict="confirm", stage="safety", device_id="lock.door",
                    operation="unlock", params={}, reason="该操作敏感/不可逆,执行前需确认")


def test_allow_executes_and_renders():
    repl, ha = _mk(_allow())
    assert repl.feed("关灯") == "✅ 已执行:light.a.turn_off"
    assert ha.calls == [("light", "turn_off", "light.a", {})]


def test_reject_renders_reason():
    repl, ha = _mk(Decision(verdict="reject", stage="parse", reason="没识别出对应的设备或操作"))
    assert "没识别出" in repl.feed("乱说一气")
    assert repl.pending is None
    assert ha.calls == []


def test_empty_line_noop():
    repl, ha = _mk(_allow())
    assert repl.feed("   ") == ""
    assert ha.calls == []


def test_execution_error_renders_failure():
    repl, _ = _mk(_allow(), raise_exc=RuntimeError("HA 500"))
    out = repl.feed("关灯")
    assert out.startswith("❌") and "HA 500" in out


def test_ambiguous_then_pick_number_executes():
    repl, ha = _mk(_amb(), resolved=_allow("light.b"))
    prompt = repl.feed("关掉卧室的灯")
    assert "哪一个" in prompt and "氛围灯" in prompt
    assert repl.feed("2") == "✅ 已执行:light.b.turn_off"
    assert ha.calls == [("light", "turn_off", "light.b", {})]
    assert repl.pending is None


def test_invalid_choice_reprompts_and_keeps_pending():
    repl, ha = _mk(_amb(), resolved=_allow("light.b"))
    prompt = repl.feed("关灯")
    assert repl.feed("8") == prompt      # 越界序号
    assert repl.feed("嗯?") == prompt    # 听不懂
    assert repl.pending is not None
    assert ha.calls == []


def test_choice_cancel_clears_pending():
    repl, ha = _mk(_amb())
    repl.feed("关灯")
    assert repl.feed("取消") == "已取消"
    assert repl.pending is None
    assert ha.calls == []


def test_confirm_yes_executes():
    repl, ha = _mk(_danger())
    prompt = repl.feed("开锁")
    assert "确认" in prompt
    assert repl.feed("y") == "✅ 已执行:lock.door.unlock"
    assert ha.calls == [("lock", "unlock", "lock.door", {})]


def test_confirm_no_cancels():
    repl, ha = _mk(_danger())
    repl.feed("开锁")
    assert repl.feed("n") == "已取消"
    assert repl.pending is None
    assert ha.calls == []


def test_confirm_gibberish_reprompts():
    repl, ha = _mk(_danger())
    prompt = repl.feed("开锁")
    assert repl.feed("唔") == prompt
    assert repl.pending is not None
    assert ha.calls == []


def test_ambiguous_choice_chains_to_danger_confirm_then_executes():
    resolved = Decision(verdict="confirm", stage="safety", device_id="lock.a",
                        operation="unlock", params={}, reason="该操作敏感/不可逆,执行前需确认")
    amb = _amb(operation="unlock", candidates=["lock.a", "lock.b"])
    repl, ha = _mk(amb, resolved=resolved)
    repl.feed("开门锁")
    second = repl.feed("1")          # 选择 → 危险操作 → 链式确认
    assert "确认" in second
    assert ha.calls == []
    assert repl.feed("y") == "✅ 已执行:lock.a.unlock"
    assert ha.calls == [("lock", "unlock", "lock.a", {})]


def test_devices_command_lists_catalog_without_llm():
    repl, ha = _mk(_allow())
    out = repl.feed("设备")
    assert "主灯" in out and "氛围灯" in out and "light.a" in out and "@卧室" in out
    assert ha.calls == []          # 不执行
    assert repl.pending is None


def test_devices_command_slash_alias():
    repl, _ = _mk(_allow())
    assert "主灯" in repl.feed("/devices")


def test_answer_verdict_renders_magnifier():
    repl, ha = _mk(Decision(verdict="answer", stage="query",
                            reason="客厅空调:制冷,当前 24°C"))
    assert repl.feed("空调几度") == "🔎 客厅空调:制冷,当前 24°C"
    assert ha.calls == []
    assert repl.pending is None


# ---------------------------------------------------------------------------
# Task 3: coerce_param —— 反问回答 → 值
# ---------------------------------------------------------------------------

def test_coerce_int_extracts_digits():
    spec = ParamSpec(type="int", min=16, max=30, required=True)
    assert coerce_param("26", spec) == 26
    assert coerce_param("调到26度", spec) == 26
    assert coerce_param("大概28吧", spec) == 28


def test_coerce_int_none_when_no_digits():
    spec = ParamSpec(type="int", min=16, max=30, required=True)
    assert coerce_param("一半", spec) is None
    assert coerce_param("随便", spec) is None


def test_coerce_enum_matches_english_and_chinese():
    spec = ParamSpec(type="enum", enum=["cool", "heat", "fan", "auto"], required=True)
    assert coerce_param("heat", spec) == "heat"
    assert coerce_param("制热", spec) == "heat"
    assert coerce_param("调成制冷", spec) == "cool"


def test_coerce_enum_none_when_no_match():
    spec = ParamSpec(type="enum", enum=["cool", "heat"], required=True)
    assert coerce_param("乱七八糟", spec) is None


# ---------------------------------------------------------------------------
# Task 5: 缺参数反问的 pending 分支
# ---------------------------------------------------------------------------

def _climate_reg():
    return Registry({
        "climate.ac": Device(name="客厅空调", type="climate", area="客厅", operations={
            "set_temperature": OperationSpec(
                params={"temperature": ParamSpec(type="int", min=16, max=30, unit="°C", required=True)}),
        }),
    })


def _ask():
    return Decision(verdict="ask", stage="param", device_id="climate.ac",
                    operation="set_temperature", params={}, missing_param="temperature",
                    reason="缺少必填参数,需向用户询问")


def _mk_ask(resolved):
    ha = StubHA()
    eng = FakeEngine(_ask(), resolved=resolved, registry=_climate_reg())
    return Repl(Controller(eng, ha)), ha


def test_ask_then_value_executes():
    resolved = Decision(verdict="allow", stage="passed", device_id="climate.ac",
                        operation="set_temperature", params={"temperature": 26})
    repl, ha = _mk_ask(resolved)
    prompt = repl.feed("调一下空调温度")
    assert "客厅空调" in prompt and "温度" in prompt
    assert repl.pending is not None
    assert repl.feed("26") == "✅ 已执行:climate.ac.set_temperature"
    assert ha.calls == [("climate", "set_temperature", "climate.ac", {"temperature": 26})]
    assert repl.pending is None


def test_ask_unparseable_value_reprompts_keeps_pending():
    repl, ha = _mk_ask(resolved=None)
    prompt = repl.feed("调一下空调温度")
    assert repl.feed("一半") == prompt      # 抽不出数字 → 重示
    assert repl.feed("随便") == prompt
    assert repl.pending is not None
    assert ha.calls == []


def test_ask_cancel_clears_pending():
    repl, ha = _mk_ask(resolved=None)
    repl.feed("调一下空调温度")
    assert repl.feed("取消") == "已取消"
    assert repl.pending is None
    assert ha.calls == []


def test_ask_value_out_of_range_renders_reject():
    resolved = Decision(verdict="reject", stage="feasibility", device_id="climate.ac",
                        operation="set_temperature", params={"temperature": 50},
                        reason="temperature 50°C 超出范围(16–30°C)")
    repl, ha = _mk_ask(resolved)
    repl.feed("调一下空调温度")
    out = repl.feed("50")
    assert out.startswith("🚫") and "超出范围" in out
    assert repl.pending is None
    assert ha.calls == []


# ---------------------------------------------------------------------------
# Task 5: 口语多轮(中文数字 / 口语是否 / 口语选号)
# ---------------------------------------------------------------------------

def test_ask_accepts_spoken_chinese_number():
    resolved = Decision(verdict="allow", stage="passed", device_id="climate.ac",
                        operation="set_temperature", params={"temperature": 26})
    repl, ha = _mk_ask(resolved)
    repl.feed("调一下空调温度")
    assert repl.feed("二十六") == "✅ 已执行:climate.ac.set_temperature"
    assert ha.calls == [("climate", "set_temperature", "climate.ac", {"temperature": 26})]


def test_confirm_accepts_spoken_affirmation():
    repl, ha = _mk(_danger())
    repl.feed("开锁")
    assert repl.feed("好的") == "✅ 已执行:lock.door.unlock"
    assert ha.calls == [("lock", "unlock", "lock.door", {})]


def test_confirm_spoken_negative_cancels():
    repl, ha = _mk(_danger())
    repl.feed("开锁")
    assert repl.feed("不用了") == "已取消"
    assert repl.pending is None
    assert ha.calls == []


def test_ambiguous_accepts_spoken_ordinal():
    repl, ha = _mk(_amb(), resolved=_allow("light.b"))
    repl.feed("关掉卧室的灯")
    assert repl.feed("第二个") == "✅ 已执行:light.b.turn_off"
    assert ha.calls == [("light", "turn_off", "light.b", {})]
