from gatekeeper.prompts import SYSTEM_PROMPT


def test_system_prompt_has_anti_fabrication_rule():
    # 安全相关规则:明确指令缺必填值时让模型留空而非编造(剪裁的唯一着力点),防误删。
    # 用本规则独有的措辞断言,避免与既有"不要编造/留空"字样巧合命中。
    assert "没说出该操作必填参数的具体值" in SYSTEM_PROMPT
    assert "系统会反问" in SYSTEM_PROMPT
