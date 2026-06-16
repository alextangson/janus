from __future__ import annotations

import logging

from anthropic import Anthropic

from .models import ParseResult
from .prompts import SYSTEM_PROMPT, TOOL_NAME, anthropic_tool, build_user_prompt
from .registry import Registry

logger = logging.getLogger(__name__)


def coerce_parse(payload: dict) -> ParseResult:
    """容错校验:小模型偶尔漏填必填的 recognized——有 device_id+operation(或候选集)
    即视为识别成功,证据全缺则保守置 False。显式给出的值绝不覆盖。"""
    if isinstance(payload, dict) and "recognized" not in payload:
        evidence = (payload.get("device_id") or payload.get("candidates")) and payload.get("operation")
        payload = {**payload, "recognized": bool(evidence)}
    return ParseResult.model_validate(payload)


def _safe_context(provider) -> str | None:
    """上下文是增强不是依赖:provider 失败 → 记 warning,无上下文继续。"""
    if provider is None:
        return None
    try:
        return provider()
    except Exception:
        logger.warning("context provider 失败,本轮无上下文解析", exc_info=True)
        return None


class ClaudeParser:
    """唯一的模型边界。换本地模型只需另写一个同样有 parse() 的类。"""

    def __init__(self, registry: Registry, model: str, client: Anthropic | None = None,
                 max_retries: int = 2, context_provider=None):
        self.registry = registry
        self.model = model
        self.client = client if client is not None else Anthropic()
        self.max_retries = max_retries
        self.context_provider = context_provider

    def parse(self, instruction: str) -> ParseResult:
        prompt = build_user_prompt(self.registry, instruction, _safe_context(self.context_provider))
        resp = self._create_with_retry(prompt)
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                return coerce_parse(block.input)
        raise ValueError("模型未返回 emit_parse 工具调用")

    def _create_with_retry(self, user_content: str):
        # 只对 API 调用重试;解析/校验失败不重试,交给 engine 的 fail-closed。
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                return self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    temperature=0,  # 安全关卡必须确定性解码,不能靠采样赌
                    system=SYSTEM_PROMPT,
                    tools=[anthropic_tool()],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                    messages=[{"role": "user", "content": user_content}],
                )
            except Exception as error:  # 重试任何传输层错误
                last_error = error
        assert last_error is not None
        raise last_error
