from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .models import Device, OperationSpec, ParamSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrySnapshot:
    by_entity: dict[str, dict]
    by_device: dict[str, dict]
    by_area: dict[str, str]
    temperature_unit: str = "°C"


def build_registry_snapshot(entities: list, devices: list, areas: list,
                            config: dict | None = None) -> RegistrySnapshot:
    """纯函数:三张 HA 注册表原始列表(+可选 /api/config)→ 带查找字典的快照。畸形项跳过。"""
    by_entity = {e["entity_id"]: e for e in entities
                 if isinstance(e, dict) and e.get("entity_id")}
    by_device = {d["id"]: d for d in devices
                 if isinstance(d, dict) and d.get("id")}
    by_area = {a["area_id"]: a.get("name", "") for a in areas
               if isinstance(a, dict) and a.get("area_id")}
    unit = "°C"
    if isinstance(config, dict):
        unit = (config.get("unit_system") or {}).get("temperature") or "°C"
    return RegistrySnapshot(by_entity, by_device, by_area, unit)


SUPPORTED_DOMAINS = {
    "light", "switch", "climate", "cover", "lock",
    "alarm_control_panel", "fan", "valve",
}


def _int(value) -> int | None:
    return int(round(value)) if value is not None else None


# HA EntityFeature 位(经真机核对):仅当实体 supported_features 含对应位时,才提供这些"能力型"操作;
# 否则 HA 会拒绝调用(500)。非能力型操作(开关/锁/arm 等)不在此表,一律视为支持。
_FEATURE_BIT = {
    "set_temperature": 1,      # ClimateEntityFeature.TARGET_TEMPERATURE
    "set_fan_mode": 8,                 # ClimateEntityFeature.FAN_MODE
    "set_preset_mode": 16,             # ClimateEntityFeature.PRESET_MODE
    "set_swing_mode": 32,              # ClimateEntityFeature.SWING_MODE
    "set_swing_horizontal_mode": 512,  # ClimateEntityFeature.SWING_HORIZONTAL_MODE
    "set_cover_position": 4,   # CoverEntityFeature.SET_POSITION
    "open": 1,                 # LockEntityFeature.OPEN(开闩)
    "set_percentage": 1,       # FanEntityFeature.SET_SPEED
    "set_valve_position": 4,   # ValveEntityFeature.SET_POSITION
}


def _supports(attrs: dict, op: str) -> bool:
    bit = _FEATURE_BIT.get(op)
    if bit is None:
        return True
    return bool((attrs.get("supported_features") or 0) & bit)


def _candidate_operations(domain: str, attrs: dict,
                          temp_unit: str = "°C") -> dict[str, dict[str, ParamSpec]]:
    """域 → {operation: {param: ParamSpec}}。参数范围取自实体属性,温度单位跟随 HA 配置。"""
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
            unit=temp_unit, required=True)}
        modes = attrs.get("hvac_modes")
        if modes:
            ops["set_hvac_mode"] = {"hvac_mode": ParamSpec(type="enum", enum=list(modes), required=True)}
        for op_name, attr_key, param in (
            ("set_fan_mode", "fan_modes", "fan_mode"),
            ("set_swing_mode", "swing_modes", "swing_mode"),
            ("set_swing_horizontal_mode", "swing_horizontal_modes", "swing_horizontal_mode"),
            ("set_preset_mode", "preset_modes", "preset_mode"),
        ):
            values = attrs.get(attr_key)
            if values:
                ops[op_name] = {param: ParamSpec(type="enum", enum=list(values), required=True)}
        return ops
    if domain == "cover":
        return {"open_cover": {}, "close_cover": {},
                "set_cover_position": {"position": ParamSpec(type="int", min=0, max=100, required=True)}}
    if domain == "lock":
        return {"lock": {}, "unlock": {}, "open": {}}
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


def _enrich(snapshot: RegistrySnapshot | None, entity_id: str) -> tuple[str | None, str | None, str]:
    """→ (entity_category, device_id, area_name)。无快照/无注册表项 → 默认值。"""
    if snapshot is None:
        return None, None, ""
    ent = snapshot.by_entity.get(entity_id)
    if not ent:
        return None, None, ""
    device_id = ent.get("device_id")
    area_id = ent.get("area_id")
    if not area_id and device_id:
        dev = snapshot.by_device.get(device_id)
        if dev:
            area_id = dev.get("area_id")
    area = snapshot.by_area.get(area_id, "") if area_id else ""
    return ent.get("entity_category"), device_id, area


def map_ha(states: list, services: list, overrides: dict | None = None,
           snapshot: "RegistrySnapshot | None" = None) -> dict[str, Device]:
    """纯函数:HA states+services → {entity_id: Device}。畸形实体跳过不崩。"""
    overrides = overrides or {}
    services_by_domain = {e["domain"]: set((e.get("services") or {}).keys()) for e in services}
    temp_unit = snapshot.temperature_unit if snapshot else "°C"
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
            for op_name, params in _candidate_operations(domain, attrs, temp_unit).items():
                if op_name not in available:
                    continue
                if not _supports(attrs, op_name):  # 按 supported_features 过滤能力型操作
                    continue
                dangerous = _default_dangerous(domain, device_class, op_name)
                if op_name in ent_overrides:
                    dangerous = bool(ent_overrides[op_name])
                operations[op_name] = OperationSpec(params=params, dangerous=dangerous)

            if not operations:
                continue
            entity_category, device_id, area = _enrich(snapshot, entity_id)
            devices[entity_id] = Device(
                name=attrs.get("friendly_name", entity_id),
                type=domain, area=area,
                entity_category=entity_category, device_id=device_id,
                operations=operations,
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            # 数据畸形(含 pydantic 校验错)→ 跳过 + 记 warning;代码级错误(如 NameError)仍会抛出暴露
            entity = st.get("entity_id", st) if isinstance(st, dict) else st
            logger.warning("跳过畸形 HA 实体 %r: %s", entity, exc)
            continue

    return devices


def load_overrides(path: str | Path) -> dict:
    """读取可选的 data/ha_overrides.json;不存在则返回空。"""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
