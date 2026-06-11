"""Assist 对话代理:每个 conversation_id 一台 Repl,复用 CLI 的纯逻辑状态机。"""
from __future__ import annotations

from homeassistant.components.conversation import (ConversationEntity,
                                                   ConversationInput,
                                                   ConversationResult)
from homeassistant.const import MATCH_ALL
from homeassistant.helpers import intent

from .const import DOMAIN
from .gatekeeper.cli import Repl

_EMPTY_REPLY = "请说出要执行的指令,例如:打开空调。"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JanusConversationEntity(entry, controller)])


class JanusConversationEntity(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry, controller):
        self._attr_unique_id = entry.entry_id
        self._controller = controller
        self._repls: dict[str, Repl] = {}

    @property
    def supported_languages(self):
        return MATCH_ALL

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        conv_id = user_input.conversation_id or "default"
        repl = self._repls.setdefault(conv_id, Repl(self._controller))
        reply = await self.hass.async_add_executor_job(repl.feed, user_input.text)
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(reply or _EMPTY_REPLY)
        return ConversationResult(response=response, conversation_id=conv_id)
