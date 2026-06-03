from __future__ import annotations

from .models import ParseResult
from .registry import Registry


def check_feasibility(parse: ParseResult, registry: Registry) -> str | None:
    """可行性校验。可行返回 None,否则返回人话原因。纯确定性,不碰模型。"""
    device = registry.get(parse.device_id)
    if device is None:
        return f"设备不存在:{parse.device_id}"

    op = device.operations.get(parse.operation)
    if op is None:
        return f"设备「{device.name}」不支持操作:{parse.operation}"

    for pname, pspec in op.params.items():
        if pspec.required and pname not in parse.params:
            return f"缺少必填参数:{pname}"

    for pname in parse.params:
        if pname not in op.params:
            return f"未知参数:{pname}"

    for pname, value in parse.params.items():
        pspec = op.params[pname]
        if pspec.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                return f"参数 {pname} 类型应为整数"
            unit = pspec.unit or ""
            if pspec.min is not None and value < pspec.min:
                return f"{pname} {value}{unit} 低于下限({pspec.min}–{pspec.max}{unit})"
            if pspec.max is not None and value > pspec.max:
                return f"{pname} {value}{unit} 超出范围({pspec.min}–{pspec.max}{unit})"
        elif pspec.type == "enum":
            if value not in (pspec.enum or []):
                return f"{pname} 取值非法:{value}"

    return None
