from __future__ import annotations

from anthropic import Anthropic

from .models import ParseResult
from .prompts import SYSTEM_PROMPT, TOOL_NAME, anthropic_tool, build_user_prompt
from .registry import Registry


class ClaudeParser:
    """唯一的模型边界。换本地模型只需另写一个同样有 parse() 的类。"""

    def __init__(self, registry: Registry, model: str, client: Anthropic | None = None, max_retries: int = 2):
        self.registry = registry
        self.model = model
        self.client = client if client is not None else Anthropic()
        self.max_retries = max_retries

    def parse(self, instruction: str) -> ParseResult:
        resp = self._create_with_retry(build_user_prompt(self.registry, instruction))
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                return ParseResult.model_validate(block.input)
        raise ValueError("模型未返回 emit_parse 工具调用")

    def _create_with_retry(self, user_content: str):
        # 只对 API 调用重试;解析/校验失败不重试,交给 engine 的 fail-closed。
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                return self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    system=SYSTEM_PROMPT,
                    tools=[anthropic_tool()],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                    messages=[{"role": "user", "content": user_content}],
                )
            except Exception as error:  # 重试任何传输层错误
                last_error = error
        assert last_error is not None
        raise last_error
