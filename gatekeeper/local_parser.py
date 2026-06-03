from __future__ import annotations

import json

from openai import OpenAI

from .models import ParseResult
from .prompts import SYSTEM_PROMPT, TOOL_DESC, TOOL_NAME, build_user_prompt, parse_schema
from .registry import Registry


class LocalParser:
    """OpenAI 兼容接口(如 Ollama)的解析器。prompt 与工具 schema 与 ClaudeParser 共用。"""

    def __init__(self, registry: Registry, model: str,
                 base_url: str = "http://localhost:11434/v1", client: OpenAI | None = None):
        self.registry = registry
        self.model = model
        self.client = client if client is not None else OpenAI(base_url=base_url, api_key="ollama")

    def parse(self, instruction: str) -> ParseResult:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,  # 安全关卡必须确定性解码,不能靠采样赌
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(self.registry, instruction)},
            ],
            tools=[{"type": "function", "function": {
                "name": TOOL_NAME, "description": TOOL_DESC, "parameters": parse_schema()}}],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        )
        message = resp.choices[0].message
        if not getattr(message, "tool_calls", None):
            raise ValueError("本地模型未返回工具调用(可能不支持 tool calling)")
        call = message.tool_calls[0]
        return ParseResult.model_validate(json.loads(call.function.arguments))
