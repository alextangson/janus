"""当前状态渲染:设备运行状态 + 环境信号 → 给模型推断用的文本块。

纯函数;输出按 entity_id 排序(prompt 必须跨进程稳定);缺数据的段落省略,
绝不编造;畸形条目跳过不崩。
"""
from __future__ import annotations

from .registry import Registry

_HA_DEMO_LAT, _HA_DEMO_LON = 47.60621, -122.33207  # HA 默认西雅图 demo 坐标=未配置位置的标志


def _location_suspect(home_coords) -> bool:
    if not home_coords:
        return False
    lat, lon = home_coords
    if lat is None or lon is None:
        return False
    if abs(lat) < 0.5 and abs(lon) < 0.5:               # null-island (0,0)
        return True
    return abs(lat - _HA_DEMO_LAT) < 0.05 and abs(lon - _HA_DEMO_LON) < 0.05


def build_context(states: list, registry: Registry, home_coords=None) -> str:
    by_id: dict[str, dict] = {}
    for st in states:
        if isinstance(st, dict) and st.get("entity_id"):
            by_id[st["entity_id"]] = st

    lines: list[str] = []
    for device_id in sorted(registry.device_ids()):
        st = by_id.get(device_id)
        if not st:
            continue
        attrs = st.get("attributes") or {}
        line = f"- {device_id}: {st.get('state', 'unknown')}"
        if device_id.startswith("climate."):
            if attrs.get("temperature") is not None:
                line += f",目标 {attrs['temperature']}°"
            if attrs.get("current_temperature") is not None:
                line += f",室温 {attrs['current_temperature']}°"
        lines.append(line)

    for eid in sorted(by_id):
        st = by_id[eid]
        attrs = st.get("attributes") or {}
        if eid.startswith("weather."):
            line = f"- 室外({eid}): {st.get('state', '')}"
            if attrs.get("temperature") is not None:
                line += f",{attrs['temperature']}{attrs.get('temperature_unit', '')}"
            if attrs.get("humidity") is not None:
                line += f",湿度 {attrs['humidity']}%"
            # 室外≠室内体感;位置疑未配置时进一步降权,别让错地点的室外值污染舒适度推断
            note = "室外参考,位置疑未配置,仅供参考" if _location_suspect(home_coords) else "室外参考,非室内体感"
            line += f"（{note}）"
            lines.append(line)
        elif eid.startswith("sensor.") and attrs.get("device_class") in ("temperature", "humidity"):
            name = attrs.get("friendly_name", eid)
            unit = attrs.get("unit_of_measurement", "")
            lines.append(f"- {name}: {st.get('state')} {unit}".rstrip())

    return "\n".join(lines)
