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


def _suffix_count(entity_ids: list[str]) -> int:
    return sum(1 for eid in entity_ids if _SUFFIX_RE.search(eid))


def _dedup(devices: dict[str, Device], snapshot: RegistrySnapshot) -> dict[str, Device]:
    """同硬件键的设备只留一个代表(实体 id 带 _N 后缀最少者;平手取 device id 字典序最小)。"""
    by_dev: dict[str, list[str]] = {}
    for eid, d in devices.items():
        if d.device_id:
            by_dev.setdefault(d.device_id, []).append(eid)

    groups: dict[tuple[tuple[str, str], ...], list[str]] = {}
    for dev_id in by_dev:
        entry = snapshot.by_device.get(dev_id)
        if not entry:
            continue
        keys = _hardware_keys(entry)
        if not keys:
            continue
        groups.setdefault(tuple(sorted(keys)), []).append(dev_id)

    dropped: set[str] = set()
    for dev_ids in groups.values():
        if len(dev_ids) < 2:
            continue
        rep = min(dev_ids, key=lambda d: (_suffix_count(by_dev[d]), d))
        dropped.update(d for d in dev_ids if d != rep)

    return {eid: d for eid, d in devices.items() if d.device_id not in dropped}


def _prune(devices: dict[str, Device], snapshot: RegistrySnapshot) -> dict[str, Device]:
    """丢 config/diagnostic;设备有主域实体 → 其 switch 全为从属开关,隐藏。"""
    # 物理设备 → 注册表里全部非 config/diagnostic 实体的域
    domains_by_dev: dict[str, set[str]] = {}
    for eid, ent in snapshot.by_entity.items():
        dev = ent.get("device_id")
        if not dev or ent.get("entity_category"):
            continue
        domains_by_dev.setdefault(dev, set()).add(eid.split(".")[0])

    out: dict[str, Device] = {}
    for eid, d in devices.items():
        if d.entity_category in {"config", "diagnostic"}:
            continue
        if d.type == "switch" and d.device_id:
            if domains_by_dev.get(d.device_id, set()) & PRIMARY_DOMAINS:
                continue
        out[eid] = d
    return out


def curate(devices: dict[str, Device], snapshot: RegistrySnapshot) -> dict[str, Device]:
    """纯函数:先去重(设备粒度)后策展(实体粒度)。宁可少删,不可误删。"""
    return _prune(_dedup(devices, snapshot), snapshot)
