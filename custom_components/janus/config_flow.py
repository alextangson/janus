"""配置向导:唯一的问题——LLM 从哪来。HA 运行时模块,测试不导入。"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (NumberSelector, NumberSelectorConfig,
                                            NumberSelectorMode)

from .const import DEFAULT_TAU, DOMAIN

_DEFAULT_BASE_URL = "http://host.docker.internal:11434/v1"


class JanusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return JanusOptionsFlow()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            if user_input["backend"] == "claude":
                return await self.async_step_claude()
            return await self.async_step_local()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("backend", default="local"): vol.In(["claude", "local"])}),
        )

    async def async_step_claude(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input["api_key"].strip()
            if key:
                return self.async_create_entry(
                    title="Janus (Claude)", data={"backend": "claude", "api_key": key})
            errors["api_key"] = "invalid_key"
        return self.async_show_form(
            step_id="claude",
            data_schema=vol.Schema({vol.Required("api_key"): str}),
            errors=errors,
        )

    async def async_step_local(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"Janus ({user_input['model']})",
                data={"backend": "local", **user_input})
        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema({
                vol.Required("base_url", default=_DEFAULT_BASE_URL): str,
                vol.Required("model", default="gemma4"): str,
            }),
        )


class JanusOptionsFlow(config_entries.OptionsFlow):
    """运行时可调项:目前只有 τ。config_entry 由 HA 自动注入。"""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get("tau", DEFAULT_TAU)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("tau", default=current): NumberSelector(
                    NumberSelectorConfig(min=0.0, max=1.0, step=0.05,
                                         mode=NumberSelectorMode.SLIDER)),
            }),
        )
