from gatekeeper.prompts import SYSTEM_PROMPT, build_user_prompt, current_season, parse_schema
from gatekeeper.registry import Registry


def test_system_prompt_has_anti_fabrication_rule():
    # 安全相关规则:明确指令缺必填值时让模型留空而非编造(剪裁的唯一着力点),防误删。
    # 用本规则独有的措辞断言,避免与既有"不要编造/留空"字样巧合命中。
    assert "没说出该操作必填参数的具体值" in SYSTEM_PROMPT
    assert "系统会反问" in SYSTEM_PROMPT


def test_current_season_by_month():
    assert current_season(7) == "夏季"
    assert current_season(1) == "冬季"
    assert current_season(4) == "春季"
    assert current_season(10) == "秋季"


def test_build_user_prompt_injects_season():
    p = build_user_prompt(Registry({}), "有点冷", context="空调 cool", season="夏季")
    assert "夏季" in p


def test_build_user_prompt_without_season_omits_it():
    p = build_user_prompt(Registry({}), "开灯")
    assert "季节" not in p


def test_system_prompt_has_comfort_discipline():
    # 取舍纪律:同向优先调温、绝不反向切 hvac、给出夏天反例(防 prompt 漂移回退)
    assert "同向" in SYSTEM_PROMPT
    assert "set_temperature" in SYSTEM_PROMPT
    assert "hvac_mode" in SYSTEM_PROMPT
    assert "制热" in SYSTEM_PROMPT


def test_parse_schema_exposes_schedule():
    # schedule 字段加在 ParseResult 上即应自动流入 emit_parse 工具 schema(单一来源)
    assert "schedule" in parse_schema()["properties"]


def test_system_prompt_has_scheduling_rule():
    # 定时/延时规则:防 prompt 漂移回退
    assert "定时" in SYSTEM_PROMPT
    assert "schedule" in SYSTEM_PROMPT
