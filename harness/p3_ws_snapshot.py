"""P3.1 真机验证:拉 WS 注册表,证明 entity_category 非 None + 设备集合零回归。

跑法(连本机真 HA):
  NO_PROXY=localhost .venv/bin/python harness/p3_ws_snapshot.py
读 .env 里的 GATEKEEPER_HA_URL / GATEKEEPER_HA_TOKEN。
"""
from __future__ import annotations

import os
from pathlib import Path

from gatekeeper.ha_client import HAClient
from gatekeeper.ha_mapping import build_registry_snapshot, map_ha


def _load_env() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    _load_env()
    url = os.environ["GATEKEEPER_HA_URL"]
    token = os.environ["GATEKEEPER_HA_TOKEN"]
    client = HAClient(url, token=token)

    states, services = client.fetch()
    entities, devices, areas = client.fetch_registries()
    snap = build_registry_snapshot(entities, devices, areas)

    before = map_ha(states, services)
    after = map_ha(states, services, snapshot=snap)

    # 前提:部分实体有 entity_category
    with_cat = [eid for eid, d in after.items() if d.entity_category is not None]
    print(f"设备总数: {len(after)}")
    print(f"entity_category 非 None 的设备: {len(with_cat)}")
    print("  样例:", with_cat[:10])
    cat_counts: dict[str, int] = {}
    for d in after.values():
        cat_counts[str(d.entity_category)] = cat_counts.get(str(d.entity_category), 0) + 1
    print("entity_category 分布:", cat_counts)
    with_area = sum(1 for d in after.values() if d.area)
    print(f"area 非空的设备: {with_area}")

    # 零回归:设备集合不变
    assert set(before) == set(after), "回归!enrichment 改变了设备集合"
    print(f"零回归 OK:设备集合不变({len(after)} 个)")
    assert len(with_cat) > 0, "前提不成立:没有任何 entity_category——检查 WS 注册表是否真的返回"
    print("前提成立 OK:WS 注册表带回了 entity_category")


if __name__ == "__main__":
    main()
