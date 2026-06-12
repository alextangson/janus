"""只读状态查询的答案渲染:device_id + states → 一句中文状态。

纯函数,无 IO,无 HA 依赖;不调模型(查询不赌模型编造状态)。
"""
from __future__ import annotations

from .registry import Registry

_HVAC_ZH = {
    "cool": "制冷", "heat": "制热", "fan_only": "送风", "auto": "自动",
    "dry": "除湿", "heat_cool": "自动", "off": "关",
}


def answer_query(device_id: str | None, candidates: list[str],
                 states: list, registry: Registry) -> str:
    by_id = {s["entity_id"]: s for s in states
             if isinstance(s, dict) and s.get("entity_id")}
    targets = [device_id] if device_id else list(candidates)
    if not targets:
        return "没听清要查哪个设备"
    return "\n".join(_render_one(t, by_id, registry) for t in targets)


def _render_one(device_id: str, by_id: dict, registry: Registry) -> str:
    device = registry.get(device_id)
    st = by_id.get(device_id)
    if device is None or st is None:
        return f"没查到「{device_id}」"
    name = device.name
    state = st.get("state", "")
    attrs = st.get("attributes") or {}
    domain = device.type

    if domain == "climate":
        if state == "off":
            return f"{name}:关"
        parts = [_HVAC_ZH.get(state, state)]
        if attrs.get("current_temperature") is not None:
            parts.append(f"当前 {attrs['current_temperature']}°C")
        if attrs.get("temperature") is not None:
            parts.append(f"设定 {attrs['temperature']}°C")
        return f"{name}:" + ",".join(parts)
    if domain in ("light", "switch"):
        return f"{name}:{'开' if state == 'on' else '关'}"
    if domain == "fan":
        s = "开" if state == "on" else "关"
        pct = attrs.get("percentage")
        return f"{name}:{s}" + (f",{pct}%" if s == "开" and pct is not None else "")
    if domain == "cover":
        s = "关" if state == "closed" else "开"
        pos = attrs.get("current_position")
        return f"{name}:{s}" + (f",{pos}%" if s == "开" and pos is not None else "")
    if domain == "lock":
        return f"{name}:{'已锁' if state == 'locked' else '已开'}"
    return f"{name}:{state}"
