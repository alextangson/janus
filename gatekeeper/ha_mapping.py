from __future__ import annotations

import json
from pathlib import Path

from .models import Device, OperationSpec, ParamSpec

SUPPORTED_DOMAINS = {
    "light", "switch", "climate", "cover", "lock",
    "alarm_control_panel", "fan", "valve",
}


def _int(value) -> int | None:
    return int(round(value)) if value is not None else None


def _candidate_operations(domain: str, attrs: dict) -> dict[str, dict[str, ParamSpec]]:
    """域 → {operation: {param: ParamSpec}}。参数范围取自实体属性。"""
    if domain == "light":
        modes = attrs.get("supported_color_modes")
        brightness = modes is None or any(m != "onoff" for m in modes)
        turn_on = {"brightness_pct": ParamSpec(type="int", min=0, max=100, required=False)} if brightness else {}
        return {"turn_on": turn_on, "turn_off": {}}
    if domain == "switch":
        return {"turn_on": {}, "turn_off": {}}
    if domain == "climate":
        ops: dict[str, dict[str, ParamSpec]] = {"turn_on": {}, "turn_off": {}}
        ops["set_temperature"] = {"temperature": ParamSpec(
            type="int", min=_int(attrs.get("min_temp")), max=_int(attrs.get("max_temp")),
            unit="°C", required=True)}
        modes = attrs.get("hvac_modes")
        if modes:
            ops["set_hvac_mode"] = {"hvac_mode": ParamSpec(type="enum", enum=list(modes), required=True)}
        return ops
    if domain == "cover":
        return {"open_cover": {}, "close_cover": {},
                "set_cover_position": {"position": ParamSpec(type="int", min=0, max=100, required=True)}}
    if domain == "lock":
        return {"lock": {}, "unlock": {}}
    if domain == "alarm_control_panel":
        return {"alarm_arm_home": {}, "alarm_arm_away": {}, "alarm_disarm": {}}
    if domain == "fan":
        return {"turn_on": {}, "turn_off": {},
                "set_percentage": {"percentage": ParamSpec(type="int", min=0, max=100, required=True)}}
    if domain == "valve":
        return {"open_valve": {}, "close_valve": {},
                "set_valve_position": {"position": ParamSpec(type="int", min=0, max=100, required=True)}}
    return {}


def _default_dangerous(domain: str, device_class: str | None, op: str) -> bool:
    if domain == "lock":
        return op in {"unlock", "open"}
    if domain == "alarm_control_panel":
        return op == "alarm_disarm"
    if domain == "cover":
        return op in {"open_cover", "set_cover_position"} and device_class in {"garage", "gate", "door"}
    if domain == "valve":
        return op in {"open_valve", "close_valve", "set_valve_position"}
    return False


def map_ha(states: list, services: list, overrides: dict | None = None) -> dict[str, Device]:
    """纯函数:HA states+services → {entity_id: Device}。畸形实体跳过不崩。"""
    overrides = overrides or {}
    services_by_domain = {e["domain"]: set((e.get("services") or {}).keys()) for e in services}
    devices: dict[str, Device] = {}

    for st in states:
        try:
            entity_id = st["entity_id"]
            domain = entity_id.split(".")[0]
            if domain not in SUPPORTED_DOMAINS:
                continue
            attrs = st.get("attributes") or {}
            available = services_by_domain.get(domain, set())
            device_class = attrs.get("device_class")
            ent_overrides = overrides.get(entity_id, {})

            operations: dict[str, OperationSpec] = {}
            for op_name, params in _candidate_operations(domain, attrs).items():
                if op_name not in available:
                    continue
                dangerous = _default_dangerous(domain, device_class, op_name)
                if op_name in ent_overrides:
                    dangerous = bool(ent_overrides[op_name])
                operations[op_name] = OperationSpec(params=params, dangerous=dangerous)

            if not operations:
                continue
            devices[entity_id] = Device(
                name=attrs.get("friendly_name", entity_id),
                type=domain, area="", operations=operations,
            )
        except Exception:
            # 单个实体畸形 → 跳过,不影响其余(生产中应记 warning)
            continue

    return devices


def load_overrides(path: str | Path) -> dict:
    """读取可选的 data/ha_overrides.json;不存在则返回空。"""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
