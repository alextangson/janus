from __future__ import annotations

import re

from .ha_mapping import RegistrySnapshot
from .models import Device

# 设备的"主域":设备若有这些域的实体,其 switch 实体视为子功能设置(从属开关)
PRIMARY_DOMAINS = {
    "camera", "media_player", "vacuum", "climate", "light", "cover",
    "lock", "fan", "valve", "alarm_control_panel", "water_heater", "humidifier",
}

_SUFFIX_RE = re.compile(r"_\d+$")


def _hardware_keys(entry: dict) -> list[tuple[str, str]]:
    """device registry 条目 → 规范化硬件键(identifier 剥掉本设备 config_entry 后缀)。

    同一物理硬件挂多个配置条目(多个米家"家")时,剥后缀后键相同。畸形项跳过,宁可不去重。
    """
    keys: list[tuple[str, str]] = []
    config_entries = entry.get("config_entries") or []
    for ident in entry.get("identifiers") or []:
        if not (isinstance(ident, (list, tuple)) and len(ident) == 2):
            continue
        domain, value = ident
        if not isinstance(value, str):
            continue
        for ce in config_entries:
            if isinstance(ce, str) and ce and value.endswith(f"-{ce}"):
                value = value[: -(len(ce) + 1)]
                break
        keys.append((domain, value))
    return keys
