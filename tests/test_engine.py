import math

import pytest

from gatekeeper.engine import Engine, _valid_intent
from gatekeeper.models import Device, OperationSpec, ParamSpec, ParseResult, ScheduleIntent
from gatekeeper.registry import Registry

from tests._helpers import FakeParser, RaisingParser, ValidatingParser


def _engine(registry, result, tau=0.7):
    return Engine(FakeParser(result), registry, tau=tau)


def _pr(**kw):
    base = {"recognized": True, "confidence": 1.0}
    base.update(kw)
    return ParseResult.model_validate(base)


def test_unrecognized_is_rejected(registry):
    eng = _engine(registry, _pr(recognized=False, confidence=0.0))
    d = eng.decide("把那个东西弄一下")
    assert d.verdict == "reject"
    assert d.stage == "parse"


def test_safe_feasible_confident_is_allowed(registry):
    eng = _engine(registry, _pr(device_id="light.living_room", operation="turn_on"))
    d = eng.decide("开客厅灯")
    assert d.verdict == "allow"
    assert d.stage == "passed"
    assert d.device_id == "light.living_room"


def test_out_of_range_is_rejected_at_feasibility(registry):
    eng = _engine(registry, _pr(device_id="climate.living_room", operation="set_temperature", params={"temperature": 50}))
    d = eng.decide("空调开到50度")
    assert d.verdict == "reject"
    assert d.stage == "feasibility"
    assert "超出范围" in d.reason


def test_low_confidence_is_confirmed(registry):
    eng = _engine(registry, _pr(device_id="light.living_room", operation="turn_on", confidence=0.4))
    d = eng.decide("把灯弄一下")
    assert d.verdict == "confirm"
    assert d.stage == "confidence"


def test_dangerous_operation_is_confirmed(registry):
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.95))
    d = eng.decide("开大门锁")
    assert d.verdict == "confirm"
    assert d.stage == "safety"


def test_confidence_gate_precedes_safety_gate(registry):
    # 危险操作但置信度低 -> 先在置信度关被拦
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.4))
    d = eng.decide("好像要开门?")
    assert d.verdict == "confirm"
    assert d.stage == "confidence"


def test_dangerous_decision_carries_dangerous_flag(registry):
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.95))
    d = eng.decide("开大门锁")
    assert d.stage == "safety"
    assert d.dangerous is True


def test_non_dangerous_decision_dangerous_false(registry):
    # 普通允许 + 低置信非危险确认都不应标 dangerous
    assert _engine(registry, _pr(device_id="light.living_room", operation="turn_on")).decide("开灯").dangerous is False
    assert _engine(registry, _pr(device_id="light.living_room", operation="turn_on", confidence=0.4)).decide("把灯弄一下").dangerous is False


def test_dangerous_low_confidence_confirm_still_dangerous(registry):
    # 危险操作但低置信 -> stage=confidence(非 safety),仍须标 dangerous(否则 PIN 门按 stage 会漏)
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.4))
    d = eng.decide("好像要开门?")
    assert d.stage == "confidence"
    assert d.dangerous is True


def test_dangerous_inferred_confirm_still_dangerous(registry):
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", confidence=0.95, inferred=True))
    d = eng.decide("我出门了")
    assert d.stage == "inferred"
    assert d.dangerous is True


def test_feasibility_precedes_safety(registry):
    # 危险设备 + 不可行(未知参数) -> 先在可行性关被拒
    eng = _engine(registry, _pr(device_id="lock.front_door", operation="unlock", params={"speed": 9}, confidence=0.95))
    d = eng.decide("开锁快点")
    assert d.verdict == "reject"
    assert d.stage == "feasibility"


def test_parser_error_fails_closed(registry):
    eng = Engine(RaisingParser(), registry, tau=0.7)
    d = eng.decide("开客厅灯")
    assert d.verdict != "allow"
    assert d.stage == "error"


@pytest.mark.parametrize("bad_conf", [math.nan, math.inf, 1.5])
def test_invalid_confidence_payload_fails_closed(registry, bad_conf):
    payload = {"recognized": True, "device_id": "light.living_room",
               "operation": "turn_on", "confidence": bad_conf}
    eng = Engine(ValidatingParser(payload), registry, tau=0.7)
    d = eng.decide("开客厅灯")
    assert d.verdict != "allow"
    assert d.stage == "error"


def test_recognized_but_missing_device_or_operation_fails_closed(registry):
    eng_no_device = _engine(registry, _pr(device_id=None, operation="turn_on"))
    assert eng_no_device.decide("x").verdict != "allow"
    eng_no_op = _engine(registry, _pr(device_id="light.living_room", operation=None))
    assert eng_no_op.decide("x").verdict != "allow"


def _amb_registry():
    def on_off():
        return {"turn_on": OperationSpec(), "turn_off": OperationSpec()}
    return Registry({
        "light.a": Device(name="主灯", type="light", area="卧室", operations=on_off()),
        "light.b": Device(name="氛围灯", type="light", area="卧室", operations=on_off()),
        "lock.door": Device(name="门锁", type="lock", area="门厅",
                            operations={"unlock": OperationSpec(dangerous=True),
                                        "lock": OperationSpec()}),
    })


def test_two_valid_candidates_ask_which_one():
    eng = Engine(FakeParser(_pr(operation="turn_off",
                                candidates=["light.a", "light.b"], confidence=0.6)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关掉卧室的灯")
    assert (d.verdict, d.stage) == ("confirm", "ambiguous")  # 置信度0.6<τ 也不落 confidence:歧义优先
    assert d.candidates == ["light.a", "light.b"]


def test_hallucinated_candidates_filtered_then_single_downgrades():
    eng = Engine(FakeParser(_pr(operation="turn_off",
                                candidates=["light.ghost", "light.a", "lock.door"])),
                 _amb_registry(), tau=0.7)
    # ghost 不存在、lock.door 不支持 turn_off → 只剩 light.a → 降级普通解析
    d = eng.decide("关灯")
    assert (d.verdict, d.stage, d.device_id) == ("allow", "passed", "light.a")


def test_single_candidate_still_passes_safety_gate():
    eng = Engine(FakeParser(_pr(operation="unlock", candidates=["lock.door"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("开锁")
    assert (d.verdict, d.stage, d.device_id) == ("confirm", "safety", "lock.door")


def test_single_candidate_still_passes_tau_gate():
    eng = Engine(FakeParser(_pr(operation="turn_off", candidates=["light.a"], confidence=0.4)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert (d.verdict, d.stage) == ("confirm", "confidence")


def test_all_candidates_invalid_rejects_at_parse():
    eng = Engine(FakeParser(_pr(operation="turn_off", candidates=["light.ghost"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert (d.verdict, d.stage) == ("reject", "parse")


def test_ambiguity_wins_over_filled_device_id():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_off",
                                candidates=["light.a", "light.b"])),
                 _amb_registry(), tau=0.7)
    assert eng.decide("关灯").stage == "ambiguous"


def _resolved_engine():
    return Engine(FakeParser(_pr()), _amb_registry(), tau=0.7)


def test_decide_resolved_allows_safe_op():
    d = _resolved_engine().decide_resolved("light.a", "turn_off", {})
    assert (d.verdict, d.stage, d.device_id) == ("allow", "passed", "light.a")


def test_decide_resolved_keeps_safety_gate():
    d = _resolved_engine().decide_resolved("lock.door", "unlock", {})
    assert (d.verdict, d.stage) == ("confirm", "safety")


def test_decide_resolved_rejects_infeasible():
    d = _resolved_engine().decide_resolved("light.a", "set_temperature", {"temperature": 24})
    assert (d.verdict, d.stage) == ("reject", "feasibility")


def test_ambiguous_decision_has_no_device_id():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_off",
                                candidates=["light.a", "light.b"])),
                 _amb_registry(), tau=0.7)
    d = eng.decide("关灯")
    assert d.stage == "ambiguous"
    assert d.device_id is None  # 歧义未消解,不得携带模型偏好的 device_id


def test_decide_resolved_skips_tau_gate():
    # τ 高到 decide() 必拦,decide_resolved 仍放行:用户的明确选择即满置信
    eng = Engine(FakeParser(_pr()), _amb_registry(), tau=0.999)
    d = eng.decide_resolved("light.a", "turn_off", {})
    assert (d.verdict, d.stage) == ("allow", "passed")


def test_inferred_always_confirms_with_notes_reason():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on",
                                inferred=True, confidence=0.95,
                                notes="室外偏凉,建议开灯取暖?不,开灯照明")),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点暗")
    assert (d.verdict, d.stage) == ("confirm", "inferred")
    assert "建议" in d.reason


def test_inferred_default_reason_when_notes_empty():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on", inferred=True)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点暗")
    assert d.stage == "inferred" and d.reason  # 兜底话术非空


def test_inferred_params_still_pass_feasibility_first():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="set_temperature",
                                params={"temperature": 26}, inferred=True)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点冷")
    assert (d.verdict, d.stage) == ("reject", "feasibility")  # 灯不支持设温度 → 先拒


def test_explicit_command_unaffected():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on")), _amb_registry(), tau=0.7)
    assert eng.decide("开灯").stage == "passed"


def test_query_returns_answer_from_state_provider():
    states = [{"entity_id": "light.a", "state": "on", "attributes": {}}]
    eng = Engine(FakeParser(_pr(device_id="light.a", query=True)),
                 _amb_registry(), tau=0.7, state_provider=lambda: states)
    d = eng.decide("卧室灯开着吗")
    assert (d.verdict, d.stage) == ("answer", "query")
    assert "主灯:开" in d.reason


def test_query_without_state_provider_degrades():
    eng = Engine(FakeParser(_pr(device_id="light.a", query=True)), _amb_registry(), tau=0.7)
    d = eng.decide("灯开着吗")
    assert (d.verdict, d.stage) == ("answer", "query")
    assert "没查到" in d.reason


def test_query_state_provider_exception_degrades():
    def boom():
        raise OSError("HA down")
    eng = Engine(FakeParser(_pr(device_id="light.a", query=True)),
                 _amb_registry(), tau=0.7, state_provider=boom)
    d = eng.decide("灯开着吗")
    assert d.verdict == "answer" and "没查到" in d.reason


def test_query_never_executes_dangerous():
    states = [{"entity_id": "lock.door", "state": "locked", "attributes": {}}]
    eng = Engine(FakeParser(_pr(device_id="lock.door", operation="unlock", query=True)),
                 _amb_registry(), tau=0.7, state_provider=lambda: states)
    d = eng.decide("门锁着吗")
    assert d.verdict == "answer"


def test_non_query_unaffected():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on")),
                 _amb_registry(), tau=0.7, state_provider=lambda: [])
    assert eng.decide("开灯").stage == "passed"


def test_missing_required_int_asks(registry):
    eng = _engine(registry, _pr(device_id="climate.living_room", operation="set_temperature"))
    d = eng.decide("调一下空调温度")
    assert (d.verdict, d.stage) == ("ask", "param")
    assert d.missing_param == "temperature"
    assert d.device_id == "climate.living_room"


def test_missing_required_enum_asks(registry):
    eng = _engine(registry, _pr(device_id="climate.living_room", operation="set_mode"))
    d = eng.decide("把空调换个模式")
    assert (d.verdict, d.stage, d.missing_param) == ("ask", "param", "mode")


def test_missing_required_position_asks(registry):
    eng = _engine(registry, _pr(device_id="cover.living_room_curtain", operation="set_position"))
    d = eng.decide("窗帘调一下")
    assert (d.verdict, d.stage, d.missing_param) == ("ask", "param", "position")


def test_invalid_op_with_missing_param_still_rejects(registry):
    # 灯不支持 set_temperature → 是真不可行,而非缺参数 → 仍 reject
    eng = _engine(registry, _pr(device_id="light.living_room", operation="set_temperature"))
    d = eng.decide("灯调到几度")
    assert (d.verdict, d.stage) == ("reject", "feasibility")
    assert d.missing_param is None


def test_present_required_param_unaffected(registry):
    eng = _engine(registry, _pr(device_id="climate.living_room", operation="set_temperature",
                                params={"temperature": 24}))
    d = eng.decide("空调24度")
    assert (d.verdict, d.stage) == ("allow", "passed")


def test_decide_resolved_missing_required_asks(registry):
    # 消歧后链式缺参:choose → decide_resolved 也应反问
    d = _engine(registry, _pr()).decide_resolved("climate.living_room", "set_temperature", {})
    assert (d.verdict, d.stage, d.missing_param) == ("ask", "param", "temperature")


def test_decide_resolved_rejects_out_of_range():
    reg = Registry({"light.a": Device(name="灯", type="light", area="厅",
        operations={"turn_on": OperationSpec(params={
            "brightness_pct": ParamSpec(type="int", min=0, max=100)})})})
    eng = Engine(parser=object(), registry=reg, tau=0.7)
    d = eng.decide_resolved("light.a", "turn_on", {"brightness_pct": 200})
    assert d.verdict == "reject" and d.stage == "feasibility"


def test_decide_resolved_dangerous_confirms():
    reg = Registry({"lock.door": Device(name="门锁", type="lock", area="门",
        operations={"unlock": OperationSpec(dangerous=True)})})
    eng = Engine(parser=object(), registry=reg, tau=0.7)
    d = eng.decide_resolved("lock.door", "unlock", {})
    assert d.verdict == "confirm" and d.stage == "safety"


# ── 定时(NL scheduling)关卡 ──────────────────────────────────────────────
# 设计铁律:定时只放行干净的 allow,malformed/危险/缺参/歧义一律 reject,
# 绝不携带 schedule、绝不走多轮 ask/confirm —— 排程不能因解析噪声触发执行。


def _sched_registry():
    return Registry({
        "climate.living": Device(name="客厅空调", type="climate", area="客厅",
            operations={
                "turn_off": OperationSpec(),
                "set_temperature": OperationSpec(params={
                    "temperature": ParamSpec(type="int", min=16, max=30, required=True)}),
            }),
        "climate.bedroom": Device(name="卧室空调", type="climate", area="卧室",
            operations={"turn_off": OperationSpec()}),
        "lock.door": Device(name="门锁", type="lock", area="门厅",
            operations={"unlock": OperationSpec(dangerous=True)}),
    })


def _sched_engine(result, tau=0.7):
    return Engine(FakeParser(result), _sched_registry(), tau=tau)


def test_valid_intent_pure_helper():
    # relative-once / absolute-once / recurring 都合法
    assert _valid_intent(ScheduleIntent(kind="once", relative_seconds=1200))
    assert _valid_intent(ScheduleIntent(kind="once", hour=8, minute=30))
    assert _valid_intent(ScheduleIntent(kind="recurring", hour=22, minute=0, recurrence="daily"))
    # malformed:越界 / 字段互斥冲突 / 缺要素
    assert not _valid_intent(ScheduleIntent(kind="once", hour=99, minute=0))
    assert not _valid_intent(ScheduleIntent(kind="once", relative_seconds=0))
    assert not _valid_intent(ScheduleIntent(kind="once", relative_seconds=600, recurrence="daily"))
    assert not _valid_intent(ScheduleIntent(kind="recurring", hour=22, minute=0))  # 无 recurrence
    assert not _valid_intent(ScheduleIntent(kind="recurring", hour=8, minute=0,
                                            recurrence="daily", relative_seconds=60))


def test_schedule_valid_recurring_allows_and_carries_descriptor():
    sched = ScheduleIntent(kind="recurring", hour=22, minute=30, recurrence="daily")
    eng = _sched_engine(_pr(device_id="climate.living", operation="turn_off", schedule=sched))
    d = eng.decide("每天晚上十点半关空调")
    assert (d.verdict, d.stage) == ("allow", "passed")
    assert d.device_id == "climate.living" and d.operation == "turn_off"
    assert d.schedule is not None and d.schedule == sched


def test_schedule_on_dangerous_op_rejects_without_descriptor():
    sched = ScheduleIntent(kind="recurring", hour=8, minute=0, recurrence="daily")
    eng = _sched_engine(_pr(device_id="lock.door", operation="unlock", schedule=sched))
    d = eng.decide("每天早上八点开门锁")
    assert d.verdict == "reject"
    assert d.schedule is None
    assert "敏感" in d.reason or "不支持" in d.reason


def test_schedule_malformed_descriptor_rejects_not_executes():
    bad = ScheduleIntent(kind="once", hour=99, minute=0)  # 越界小时
    eng = _sched_engine(_pr(device_id="climate.living", operation="turn_off", schedule=bad))
    d = eng.decide("某个时刻关空调")
    assert d.verdict == "reject" and d.stage == "feasibility"
    assert d.schedule is None


def test_schedule_malformed_relative_plus_recurrence_rejects():
    bad = ScheduleIntent(kind="once", relative_seconds=600, recurrence="daily")  # 互斥冲突
    eng = _sched_engine(_pr(device_id="climate.living", operation="turn_off", schedule=bad))
    d = eng.decide("过会儿每天关空调")
    assert d.verdict == "reject"
    assert d.schedule is None


def test_schedule_missing_required_param_rejects_not_asks():
    # set_temperature 缺 temperature:普通路径会 ask,定时路径必须 reject(无多轮反问)
    sched = ScheduleIntent(kind="recurring", hour=22, minute=0, recurrence="daily")
    eng = _sched_engine(_pr(device_id="climate.living", operation="set_temperature",
                            params={}, schedule=sched))
    d = eng.decide("每天晚上调空调温度")
    assert d.verdict == "reject"
    assert d.verdict != "ask"
    assert d.schedule is None


def test_schedule_ambiguous_candidates_rejects_no_multiturn():
    # 两个有效候选 + device_id None:普通路径会 confirm 选择,定时路径必须 reject
    sched = ScheduleIntent(kind="recurring", hour=23, minute=0, recurrence="daily")
    eng = _sched_engine(_pr(operation="turn_off",
                            candidates=["climate.living", "climate.bedroom"], schedule=sched))
    d = eng.decide("每天晚上关空调")
    assert d.verdict == "reject"
    assert d.verdict not in ("confirm", "ask")
    assert "哪个设备" in d.reason
    assert d.schedule is None


def test_schedule_single_valid_candidate_resolves_and_allows():
    # 候选过滤后只剩一个有效设备:消歧→放行(不反问)
    sched = ScheduleIntent(kind="recurring", hour=7, minute=0, recurrence="weekday")
    eng = _sched_engine(_pr(operation="turn_off",
                            candidates=["climate.living", "lock.door"], schedule=sched))
    d = eng.decide("工作日早上七点关空调")
    assert (d.verdict, d.stage, d.device_id) == ("allow", "passed", "climate.living")
    assert d.schedule == sched


def test_schedule_no_device_no_candidates_rejects_at_parse():
    sched = ScheduleIntent(kind="once", relative_seconds=600)
    eng = _sched_engine(_pr(operation="turn_off", schedule=sched))
    d = eng.decide("过会儿关一下")
    assert (d.verdict, d.stage) == ("reject", "parse")
    assert d.schedule is None


def test_no_schedule_branch_skipped_regression():
    # schedule=None 的普通指令完全走原路径(分支被跳过)
    eng = _sched_engine(_pr(device_id="climate.living", operation="turn_off"))
    d = eng.decide("关空调")
    assert (d.verdict, d.stage) == ("allow", "passed")
    assert d.schedule is None


def test_schedule_reject_reason_never_leaks_entity_id():
    # 鬼设备:check_feasibility 会回 "设备不存在:climate.ghost"(含原始 entity_id)。
    # 定时拒绝面绝不透传该字符串 —— 与 423f911「停止泄漏 entity_id/op」一致。
    sched = ScheduleIntent(kind="recurring", hour=22, minute=0, recurrence="daily")
    eng = _sched_engine(_pr(device_id="climate.ghost", operation="turn_off", schedule=sched))
    d = eng.decide("每天晚上关那个空调")
    assert d.verdict == "reject"
    assert d.schedule is None
    assert "climate.ghost" not in d.reason
    assert "ghost" not in d.reason


def test_schedule_reject_reason_never_leaks_operation_name():
    # 卧室空调不支持 set_temperature:check_feasibility 会回
    # "设备「卧室空调」不支持操作:set_temperature"(含原始 op token)。定时拒绝面须用固定话术。
    sched = ScheduleIntent(kind="recurring", hour=22, minute=0, recurrence="daily")
    eng = _sched_engine(_pr(device_id="climate.bedroom", operation="set_temperature",
                            params={"temperature": 24}, schedule=sched))
    d = eng.decide("每天晚上把卧室空调调到几度")
    assert d.verdict == "reject"
    assert d.schedule is None
    assert "set_temperature" not in d.reason
