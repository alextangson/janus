"""Janus — 给任何 LLM 套上安全门的 HA 对话代理。

红线:模块级只准 import 标准库 / .const / .bridge。
homeassistant.* 与 .gatekeeper.*(部署期注入)只存在于 HA 运行时,必须函数内导入,
否则单测 import custom_components.janus.bridge 会触发本文件而炸。

设计:注册表**每轮对话重建**(纯函数,毫秒级)。真机证实 setup 时建快照会与
集成加载顺序赛跑——启动早期目录可能为空,模型对空清单只会幻觉。
"""
from __future__ import annotations

from .const import DEFAULT_TAU, DOMAIN

PLATFORMS = ["conversation"]
_GLOBAL_REGISTERED = False


async def async_setup_entry(hass, entry) -> bool:
    # setup 只存配置 + 审计器;一切重活推迟到对话时(那时 HA 必然已就绪)。
    from homeassistant.helpers.storage import Store

    from .audit import DecisionAudit

    audit = DecisionAudit(hass, Store(hass, 1, f"janus_audit_{entry.entry_id}"))
    await audit.async_load()
    data = dict(entry.data)
    data["audit"] = audit
    data["tau"] = entry.options.get("tau", DEFAULT_TAU)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    from .observer import ObservationLog, start_observer

    obs_log = ObservationLog(hass, Store(hass, 1, f"janus_observations_{entry.entry_id}"))
    await obs_log.async_load()
    data["observations"] = obs_log
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data
    entry.async_on_unload(start_observer(hass, obs_log))
    await _async_setup_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass, entry) -> None:
    """options 改了 → 重载 entry,新 τ 生效。"""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_setup_panel(hass) -> None:
    """注册侧栏面板:静态资源 + WS 命令(进程级,幂等)+ 面板(每 entry)。
    面板挂了绝不连累控制功能,整体兜底。"""
    global _GLOBAL_REGISTERED
    try:
        from pathlib import Path

        from homeassistant.components import panel_custom, websocket_api
        from homeassistant.components.http import StaticPathConfig

        from .panel import ws_list_decisions

        if not _GLOBAL_REGISTERED:
            await hass.http.async_register_static_paths([
                StaticPathConfig(
                    "/janus_static/janus-panel.js",
                    str(Path(__file__).parent / "www" / "janus-panel.js"),
                    False,
                )])
            websocket_api.async_register_command(hass, ws_list_decisions)
            _GLOBAL_REGISTERED = True
        await panel_custom.async_register_panel(
            hass, webcomponent_name="janus-audit-panel", frontend_url_path="janus",
            module_url="/janus_static/janus-panel.js", sidebar_title="Janus",
            sidebar_icon="mdi:shield-check", require_admin=False)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("janus panel setup failed")


async def async_unload_entry(hass, entry) -> bool:
    import logging

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        from homeassistant.components import frontend
        try:
            frontend.async_remove_panel(hass, "janus")
        except Exception:  # noqa: BLE001
            pass
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        audit = data.get("audit") if data else None
        if audit is not None:
            try:
                await audit.async_flush()  # 重载前即时落盘,别丢去抖窗口内的记录
            except Exception:  # noqa: BLE001 — 一处落盘失败不连累另一处/卸载
                logging.getLogger(__name__).exception("janus audit flush failed")
        obs_log = data.get("observations") if data else None
        if obs_log is not None:
            await obs_log.async_flush()  # 自身已 try 兜底
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
    from .gatekeeper.config import MODEL
    from .gatekeeper.context import build_context
    from .gatekeeper.controller import Controller
    from .gatekeeper.engine import Engine
    from .gatekeeper.ha_mapping import build_registry_snapshot
    from .gatekeeper.registry import Registry

    snap = build_registry_snapshot(shapes["entities"], shapes["devices"],
                                   shapes["areas"], config=shapes["config"])
    reg = Registry.from_ha(shapes["states"], shapes["services"], snapshot=snap)

    def context_provider() -> str:
        return build_context(shapes["states"], reg)  # shapes 每轮重建,本就新鲜

    if data["backend"] == "local":
        from .gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, data["model"], base_url=data["base_url"], context_provider=context_provider)
    else:
        from anthropic import Anthropic

        from .gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, MODEL, client=Anthropic(api_key=data["api_key"]), context_provider=context_provider)
    return Controller(Engine(parser, reg, data.get("tau", DEFAULT_TAU),
                             state_provider=lambda: shapes["states"]), HassServiceCaller(hass))
