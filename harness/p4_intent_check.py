"""P4 真机验收:模糊舒适度表达 → confirm/inferred + 💡 理由;明确指令零回归。

跑法(本地模型,注意 BACKEND 默认是 claude,必须显式指定):
  NO_PROXY=localhost GATEKEEPER_BACKEND=local .venv/bin/python harness/p4_intent_check.py
需要:HA + 一个模型(本地 Ollama 或云端 key)。只 decide,不执行。
"""
from __future__ import annotations

import os

from gatekeeper.config import BACKEND, LOCAL_MODEL, MODEL, TAU, load_env
from gatekeeper.context import build_context
from gatekeeper.engine import Engine
from gatekeeper.ha_client import HAClient
from gatekeeper.ha_mapping import build_registry_snapshot
from gatekeeper.registry import Registry


def main() -> None:
    load_env()
    client = HAClient(os.environ["GATEKEEPER_HA_URL"], token=os.environ["GATEKEEPER_HA_TOKEN"])
    states, services = client.fetch()
    snap = build_registry_snapshot(*client.fetch_registries(), config=client.fetch_config())
    reg = Registry.from_ha(states, services, snapshot=snap)

    def provider() -> str:
        return build_context(client.fetch()[0], reg)

    print("== 注入的上下文 ==")
    print(provider())

    if BACKEND == "local":
        from gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, LOCAL_MODEL, context_provider=provider)
    else:
        from gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, MODEL, context_provider=provider)
    engine = Engine(parser, reg, tau=TAU)

    d = engine.decide("我感觉有点冷")
    print(f"\n「我感觉有点冷」→ {d.verdict}/{d.stage}")
    print(f"   {d.device_id} . {d.operation} {dict(d.params)}")
    print(f"   理由: {d.reason}")
    assert (d.verdict, d.stage) == ("confirm", "inferred"), f"期望 confirm/inferred,得到 {d.verdict}/{d.stage}"
    assert d.device_id and d.device_id.startswith("climate."), "应指向空调"
    print("验收1 OK:模糊表达 → 推断提议,落 confirm")

    d2 = engine.decide("打开空调")
    print(f"\n「打开空调」→ {d2.verdict}/{d2.stage} {d2.device_id}")
    assert d2.verdict == "allow" and d2.stage == "passed", "明确指令必须零回归"
    print("验收2 OK:明确指令直接放行")


if __name__ == "__main__":
    main()
