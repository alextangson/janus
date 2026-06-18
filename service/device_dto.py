from __future__ import annotations


def device_state(domain: str, state: str, attrs: dict) -> dict:
    """HA 实体 state+attributes → 结构化当前状态(字段对齐能力参数名,供前端控制积木绑定)。
    纯函数,缺属性优雅降级(不塞 None 键)。"""
    if domain == "light":
        out: dict = {"on": state == "on"}
        b = attrs.get("brightness")
        if b is not None:
            out["brightness_pct"] = round(b / 255 * 100)
        return out
    if domain == "switch":
        return {"on": state == "on"}
    if domain == "climate":
        out = {"on": state != "off", "hvac_mode": state}
        if attrs.get("current_temperature") is not None:
            out["current_temperature"] = attrs["current_temperature"]
        if attrs.get("temperature") is not None:
            out["target_temperature"] = attrs["temperature"]
        for key in ("fan_mode", "swing_mode", "swing_horizontal_mode", "preset_mode"):
            if attrs.get(key) is not None:
                out[key] = attrs[key]
        return out
    if domain in ("cover", "valve"):
        # open 指"非 closed"(含 opening/closing/stopped 过渡态),与 queries.py 一致;
        # 前端需要精确过渡态时另读原始 state。
        out = {"open": state != "closed"}
        if attrs.get("current_position") is not None:
            out["position"] = attrs["current_position"]
        return out
    if domain == "fan":
        out = {"on": state == "on"}
        if attrs.get("percentage") is not None:
            out["percentage"] = attrs["percentage"]
        return out
    if domain == "lock":
        return {"locked": state == "locked"}
    return {"state": state}


def capabilities_to_dto(device) -> dict:
    """Device.operations → 稳定能力 DTO。显式列字段(绝不裸 model_dump,防内部结构漂移)。
    每个参数字段恒在(无值为 null),前端绑定固定结构。"""
    return {
        op_name: {
            "dangerous": op.dangerous,
            "params": {
                pname: {"type": p.type, "min": p.min, "max": p.max,
                        "enum": p.enum, "unit": p.unit, "required": p.required}
                for pname, p in op.params.items()
            },
        }
        for op_name, op in device.operations.items()
    }


def device_to_dto(device_id: str, device, state: dict) -> dict:
    """单设备稳定 DTO:友好名 + 区域 + 域 + 物理 device_id(app 据此分组多路设备)+ 能力 + 状态。
    device_id 为消费层主键(entity_id);device.device_id 是 HA 物理设备 id(可 None)。"""
    return {
        "id": device_id,
        "name": device.name,
        "area": device.area,
        "type": device.type,
        "device_id": device.device_id,
        "capabilities": capabilities_to_dto(device),
        "state": state,
    }
