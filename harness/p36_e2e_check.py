"""P3.6 真机验收:歧义指令应产出 ambiguous + 双候选;唯一目标仍直接放行。

跑法:NO_PROXY=localhost .venv/bin/python harness/p36_e2e_check.py
需要:HA(localhost:8123)+ Ollama(gemma4)在跑。只 decide,不执行。
"""
from __future__ import annotations

import os
from pathlib import Path

from gatekeeper.config import LOCAL_MODEL, TAU
from gatekeeper.engine import Engine
from gatekeeper.ha_client import HAClient
from gatekeeper.ha_mapping import build_registry_snapshot
from gatekeeper.local_parser import LocalParser
from gatekeeper.registry import Registry


def _load_env() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        raise SystemExit("缺少 .env:请设置 GATEKEEPER_HA_URL 和 GATEKEEPER_HA_TOKEN")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    _load_env()
    client = HAClient(os.environ["GATEKEEPER_HA_URL"], token=os.environ["GATEKEEPER_HA_TOKEN"])
    states, services = client.fetch()
    snap = build_registry_snapshot(*client.fetch_registries(), config=client.fetch_config())
    reg = Registry.from_ha(states, services, snapshot=snap)
    engine = Engine(LocalParser(reg, LOCAL_MODEL), reg, tau=TAU)

    d = engine.decide("关掉卧室的灯")
    print(f"「关掉卧室的灯」→ {d.verdict}/{d.stage} 候选={d.candidates}")
    assert d.stage == "ambiguous", f"期望 ambiguous,得到 {d.stage}"
    yeelink = [c for c in d.candidates if c.startswith("light.yeelink_")]
    assert len(yeelink) == 2, f"期望两盏 Yeelight 进候选,得到 {d.candidates}"
    print("验收1 OK:歧义指令产出双候选")

    d2 = engine.decide("打开空调")
    print(f"「打开空调」→ {d2.verdict}/{d2.stage} {d2.device_id}")
    assert d2.verdict == "allow" and not d2.candidates, "唯一目标不应进歧义分支"
    print("验收2 OK:唯一目标仍直接放行,无回归")


if __name__ == "__main__":
    main()
