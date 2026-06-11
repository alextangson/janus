"""Janus — 给任何 LLM 套上安全门的 HA 对话代理。

红线:模块级只准 import 标准库 / .const / .bridge。
homeassistant.* 与 .gatekeeper.*(部署期注入)只存在于 HA 运行时,必须函数内导入,
否则单测 import custom_components.janus.bridge 会触发本文件而炸。

设计:注册表**每轮对话重建**(纯函数,毫秒级)。真机证实 setup 时建快照会与
集成加载顺序赛跑——启动早期目录可能为空,模型对空清单只会幻觉。
"""
from __future__ import annotations

from .const import DOMAIN

PLATFORMS = ["conversation"]


async def async_setup_entry(hass, entry) -> bool:
    # setup 只存配置;一切重活推迟到对话时(那时 HA 必然已就绪)。
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = dict(entry.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok


def collect_shapes(hass) -> dict:
    """事件循环内读 hass 注册表/状态 → 原始 dict 集合。必须在循环线程调用。"""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from .bridge import (areas_from_registry, config_from_hass,
                         devices_from_registry, entities_from_registry,
                         services_from_hass, states_from_hass)

    return {
        "entities": entities_from_registry(er.async_get(hass).entities.values()),
        "devices": devices_from_registry(dr.async_get(hass).devices.values()),
        "areas": areas_from_registry(ar.async_get(hass).areas.values()),
        "states": states_from_hass(hass.states.async_all()),
        "services": services_from_hass(hass.services.async_services()),
        "config": config_from_hass(hass.config.units.temperature_unit),
    }


def build_controller(hass, shapes: dict, data: dict):
    """shapes + 配置 → 全新 Controller。重活(gatekeeper/SDK 导入、客户端构造、
    SSL 加载)全在这里,必须在 executor 线程调用,不得碰事件循环。"""
    from .bridge import HassServiceCaller
    from .gatekeeper.config import MODEL, TAU
    from .gatekeeper.controller import Controller
    from .gatekeeper.engine import Engine
    from .gatekeeper.ha_mapping import build_registry_snapshot
    from .gatekeeper.registry import Registry

    snap = build_registry_snapshot(shapes["entities"], shapes["devices"],
                                   shapes["areas"], config=shapes["config"])
    reg = Registry.from_ha(shapes["states"], shapes["services"], snapshot=snap)
    if data["backend"] == "local":
        from .gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, data["model"], base_url=data["base_url"])
    else:
        from anthropic import Anthropic

        from .gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, MODEL, client=Anthropic(api_key=data["api_key"]))
    return Controller(Engine(parser, reg, TAU), HassServiceCaller(hass))
