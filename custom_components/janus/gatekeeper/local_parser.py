from __future__ import annotations

import json

from openai import OpenAI

from .models import ParseResult
from .parser import _safe_context, coerce_parse
from .prompts import SYSTEM_PROMPT, TOOL_DESC, TOOL_NAME, build_user_prompt, parse_schema
from .registry import Registry


class LocalParser:
    """OpenAI 兼容接口(如 Ollama)的解析器。prompt 与工具 schema 与 ClaudeParser 共用。"""

    def __init__(self, registry: Registry, model: str,
                 base_url: str = "http://localhost:11434/v1", client: OpenAI | None = None,
                 timeout: float = 120.0, context_provider=None):
        self.registry = registry
        self.model = model
        self.context_provider = context_provider
        # 有限超时:本地模型卡死时引擎 fail-closed(拒绝),绝不无限挂起。
        # 默认留足冷加载余量(9.6GB 模型首次载入可达 1-2 分钟)。
        self.client = client if client is not None else OpenAI(
            base_url=base_url, api_key="ollama", timeout=timeout)

    def parse(self, instruction: str) -> ParseResult:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,  # 安全关卡必须确定性解码,不能靠采样赌
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(
                    self.registry, instruction, _safe_context(self.context_provider))},
            ],
            tools=[{"type": "function", "function": {
                "name": TOOL_NAME, "description": TOOL_DESC, "parameters": parse_schema()}}],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        )
        message = resp.choices[0].message
        if not getattr(message, "tool_calls", None):
            raise ValueError("本地模型未返回工具调用(可能不支持 tool calling)")
        call = message.tool_calls[0]
        return coerce_parse(json.loads(call.function.arguments))
