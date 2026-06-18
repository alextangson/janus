"""Outcome/Decision → 面向用户的中文动作短语。

纯函数,无 IO。把 (operation, params, device) 渲染成人话(如"把空调调到 28°C"),
绝不把裸 entity_id / 原始操作名 / 参数字典糊给用户。所有面向用户的确认/已执行文案共用。
"""
from __future__ import annotations

from .models import Decision
from .queries import _ENUM_ZH
from .registry import Registry

_PARAM_ZH = {"temperature": "温度", "position": "位置", "percentage": "百分比",
             "hvac_mode": "模式", "mode": "模式", "brightness_pct": "亮度"}


def describe_action(decision: Decision, registry: Registry) -> str:
    device = registry.get(decision.device_id)
    name = device.name if device else "该设备"      # 注册表缺失也绝不漏裸 entity_id
    op = decision.operation or ""
    params = dict(decision.params)

    if op == "turn_on" or op in ("open", "open_cover"):
        return f"打开{name}"
    if op == "turn_off" or op in ("close", "close_cover"):
        return f"关闭{name}"
    if op == "unlock":
        return f"解锁{name}"
    if op == "lock":
        return f"锁上{name}"
    if op == "set_temperature":
        t = params.get("temperature")
        return f"把{name}调到 {t}°C" if t is not None else f"调节{name}温度"
    if op == "set_hvac_mode":
        m = params.get("hvac_mode") or params.get("mode")
        return f"把{name}切到{_ENUM_ZH.get(m, m)}" if m is not None else f"切换{name}模式"
    if op == "set_percentage":
        p = params.get("percentage", params.get("position"))
        return f"把{name}调到 {p}%" if p is not None else f"调节{name}"

    # 兜底:中文化能中文化的键值,绝不出现裸 op 名或 { } 字典
    if params:
        kv = "、".join(f"{_PARAM_ZH.get(k, k)} {_ENUM_ZH.get(v, v)}" for k, v in params.items())
        return f"调节{name}（{kv}）"
    return f"操作{name}"
