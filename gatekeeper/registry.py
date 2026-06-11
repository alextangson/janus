from __future__ import annotations

import json
from pathlib import Path

from .models import Device
from .ha_mapping import map_ha, RegistrySnapshot
from .curation import curate


class Registry:
    def __init__(self, devices: dict[str, Device]):
        self._devices = devices

    @classmethod
    def from_file(cls, path: str | Path) -> "Registry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        devices = {device_id: Device.model_validate(spec) for device_id, spec in raw.items()}
        return cls(devices)

    @classmethod
    def from_ha(cls, states: list, services: list, overrides: dict | None = None,
                snapshot: RegistrySnapshot | None = None) -> "Registry":
        devices = map_ha(states, services, overrides, snapshot)
        if snapshot is not None:
            devices = curate(devices, snapshot)
        return cls(devices)

    def device_ids(self) -> list[str]:
        return list(self._devices.keys())

    def get(self, device_id: str | None) -> Device | None:
        if device_id is None:
            return None
        return self._devices.get(device_id)

    def is_dangerous(self, device_id: str | None, operation: str | None) -> bool:
        device = self.get(device_id)
        if device is None or operation is None:
            return False
        op = device.operations.get(operation)
        return bool(op and op.dangerous)

    def as_prompt_catalog(self) -> str:
        """渲染给 parser 的设备清单。刻意不含 dangerous——模型不判断危险。

        按 device_id 排序:目录顺序必须跨进程/跨重启稳定,否则 temperature=0
        也挡不住 prompt 漂移带来的解析波动(安全关卡不赌采样,也不赌枚举顺序)。
        """
        lines: list[str] = []
        for device_id, device in sorted(self._devices.items()):
            lines.append(f"- {device_id}({device.name},区域:{device.area})")
            for op_name, op in device.operations.items():
                if not op.params:
                    lines.append(f"    · {op_name} 参数:无")
                    continue
                parts: list[str] = []
                for pname, p in op.params.items():
                    req = "必填" if p.required else "选填"
                    if p.type == "int":
                        rng = f"{p.min}-{p.max}" if p.min is not None and p.max is not None else "整数"
                        unit = p.unit or ""
                        parts.append(f"{pname}(int,{rng}{unit},{req})")
                    else:
                        choices = ",".join(p.enum or [])
                        parts.append(f"{pname}(enum[{choices}],{req})")
                lines.append(f"    · {op_name} 参数:{'; '.join(parts)}")
        return "\n".join(lines)
