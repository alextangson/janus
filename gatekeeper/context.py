"""当前状态渲染:设备运行状态 + 环境信号 → 给模型推断用的文本块。

纯函数;输出按 entity_id 排序(prompt 必须跨进程稳定);缺数据的段落省略,
绝不编造;畸形条目跳过不崩。
"""
from __future__ import annotations

from .registry import Registry


def build_context(states: list, registry: Registry) -> str:
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
            lines.append(line)
        elif eid.startswith("sensor.") and attrs.get("device_class") in ("temperature", "humidity"):
            name = attrs.get("friendly_name", eid)
            unit = attrs.get("unit_of_measurement", "")
            lines.append(f"- {name}: {st.get('state')} {unit}".rstrip())

    return "\n".join(lines)
