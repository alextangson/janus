"""Janus — 给任何 LLM 套上安全门的 HA 对话代理。

红线:模块级只准 import 标准库 / .const / .bridge。
homeassistant.* 与 .gatekeeper.*(部署期注入)只存在于 HA 运行时,必须函数内导入,
否则单测 import custom_components.janus.bridge 会触发本文件而炸。
"""
from __future__ import annotations

from .const import DOMAIN

PLATFORMS = ["conversation"]


async def async_setup_entry(hass, entry) -> bool:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from .bridge import (HassServiceCaller, areas_from_registry, config_from_hass,
                         devices_from_registry, entities_from_registry,
                         services_from_hass, states_from_hass)
    from .gatekeeper.config import MODEL, TAU
    from .gatekeeper.controller import Controller
    from .gatekeeper.engine import Engine
    from .gatekeeper.ha_mapping import build_registry_snapshot
    from .gatekeeper.registry import Registry

    snap = build_registry_snapshot(
        entities_from_registry(er.async_get(hass).entities.values()),
        devices_from_registry(dr.async_get(hass).devices.values()),
        areas_from_registry(ar.async_get(hass).areas.values()),
        config=config_from_hass(hass.config.units.temperature_unit),
    )
    reg = Registry.from_ha(
        states_from_hass(hass.states.async_all()),
        services_from_hass(hass.services.async_services()),
        snapshot=snap,
    )

    data = entry.data
    if data["backend"] == "local":
        from .gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, data["model"], base_url=data["base_url"])
    else:
        from anthropic import Anthropic

        from .gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, MODEL, client=Anthropic(api_key=data["api_key"]))

    controller = Controller(Engine(parser, reg, TAU), HassServiceCaller(hass))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
