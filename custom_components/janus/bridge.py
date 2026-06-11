"""hass 形状对象 → 纯逻辑层原始 dict;以及执行适配器。

红线:本模块不 import homeassistant、不 import gatekeeper——鸭子类型,纯转换,
无 HA 环境即可单测。
"""
from __future__ import annotations

import asyncio


def states_from_hass(states) -> list:
    return [{"entity_id": s.entity_id, "state": s.state, "attributes": dict(s.attributes)}
            for s in states]


def services_from_hass(services_by_domain) -> list:
    return [{"domain": domain, "services": {name: {} for name in services}}
            for domain, services in services_by_domain.items()]


def entities_from_registry(entries) -> list:
    out = []
    for e in entries:
        cat = e.entity_category
        out.append({
            "entity_id": e.entity_id,
            "device_id": e.device_id,
            "area_id": e.area_id,
            "entity_category": getattr(cat, "value", cat),
        })
    return out


def devices_from_registry(entries) -> list:
    return [{
        "id": d.id,
        "area_id": d.area_id,
        "identifiers": [list(i) for i in (d.identifiers or [])],
        "config_entries": list(d.config_entries or []),
        "name": d.name_by_user or d.name,
    } for d in entries]


def areas_from_registry(entries) -> list:
    return [{"area_id": a.id, "name": a.name} for a in entries]


def config_from_hass(temperature_unit: str) -> dict:
    return {"unit_system": {"temperature": temperature_unit}}


class HassServiceCaller:
    """Controller 期望的同步 call_service;投递回 HA 事件循环执行。

    只能从 executor 线程调用(repl.feed 整体跑在 executor),
    绝不能在事件循环线程里调用——.result() 会死锁。
    """

    def __init__(self, hass, timeout: float = 10.0):
        self._hass = hass
        self._timeout = timeout

    def call_service(self, domain: str, service: str, entity_id: str,
                     params: dict | None = None):
        future = asyncio.run_coroutine_threadsafe(
            self._hass.services.async_call(
                domain, service, {"entity_id": entity_id, **(params or {})},
                blocking=True),
            self._hass.loop,
        )
        return future.result(self._timeout)
