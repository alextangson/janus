from __future__ import annotations

from .models import ParseResult
from .registry import Registry

TOOL_NAME = "emit_parse"
TOOL_DESC = "输出对用户指令的结构化解析结果。"

SYSTEM_PROMPT = """你是一个智能家居指令解析器。你唯一的职责:把用户的自然语言指令,映射到给定设备清单里的一个具体操作,并输出结构化结果。

规则:
- 只能使用清单里真实存在的 device_id 和 operation,不要编造。
- 若指令无法对应到某个真实设备的某个【已列出操作】,令 recognized=false——这包括两种情况:设备根本不存在;以及设备认得、但它没有你要的那个操作(例如让插座"设温度"、让窗帘"调颜色")。
- 不要判断操作是否危险、参数是否越界——照实抽取用户意图即可,合法性由系统另行检查。
- confidence 表示你对"这就是用户意图"的把握(0~1):指令清晰直接→高;含糊、可能指代多个设备、信息不全→低。
- 若指令含糊地匹配多个设备(同名/同区域/同类型),不要硬猜:令 recognized=true,把全部可能的 device_id 列入 candidates,device_id 留空;operation 与 params 照常填。明确无歧义时 candidates 必须为空。
- 必须通过调用 emit_parse 工具来输出结果。"""


def parse_schema() -> dict:
    """解析结果的 JSON schema,单一来源(pydantic 生成)。"""
    return ParseResult.model_json_schema()


def anthropic_tool() -> dict:
    return {"name": TOOL_NAME, "description": TOOL_DESC, "input_schema": parse_schema()}


def build_user_prompt(registry: Registry, instruction: str) -> str:
    return (
        "可用设备清单(只能从中选择 device_id 与 operation):\n"
        f"{registry.as_prompt_catalog()}\n\n"
        f"用户指令:{instruction}\n\n"
        "请调用 emit_parse 输出解析结果。"
    )
