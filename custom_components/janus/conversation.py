"""Assist 对话代理:每个 conversation_id 一台 Repl,复用 CLI 的纯逻辑状态机。

注册表每轮重建(见包 __init__ 的设计说明):pending 状态留在 Repl 里跨轮存活,
controller 每轮换新——确认/选择因此总是对照**当前**设备世界复审。
"""
from __future__ import annotations

from homeassistant.components.conversation import (ConversationEntity,
                                                   ConversationInput,
                                                   ConversationResult)
from homeassistant.const import MATCH_ALL
from homeassistant.helpers import intent

from . import build_controller, collect_shapes
from .const import DOMAIN
from .gatekeeper.cli import Repl

_EMPTY_REPLY = "请说出要执行的指令,例如:打开空调。"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JanusConversationEntity(entry, data)])


class JanusConversationEntity(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry, data: dict):
        self._attr_unique_id = entry.entry_id
        self._data = data
        self._repls: dict[str, Repl] = {}

    @property
    def supported_languages(self):
        return MATCH_ALL

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        conv_id = user_input.conversation_id or "default"
        repl = self._repls.setdefault(conv_id, Repl(controller=None))
        shapes = collect_shapes(self.hass)  # 必须在事件循环线程读

        def _work() -> str:
            repl.controller = build_controller(self.hass, shapes, self._data)
            return repl.feed(user_input.text)

        reply = await self.hass.async_add_executor_job(_work)
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(reply or _EMPTY_REPLY)
        return ConversationResult(response=response, conversation_id=conv_id)
