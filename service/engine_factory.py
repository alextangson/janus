from __future__ import annotations

from gatekeeper.context import build_context
from gatekeeper.controller import Controller
from gatekeeper.engine import Engine
from gatekeeper.ha_client import HAClient
from gatekeeper.ha_mapping import build_registry_snapshot
from gatekeeper.registry import Registry


def build_shared_clients(ha_url: str, ha_token: str, backend: str, model: str,
                         local_base_url: str):
    """进程级共享单例:一个 HAClient + 一个 LLM client(避免每轮重建)。"""
    ha_client = HAClient(ha_url, token=ha_token)
    if backend == "local":
        from openai import OpenAI
        llm_client = OpenAI(base_url=local_base_url, api_key="ollama")
    else:
        from anthropic import Anthropic
        llm_client = Anthropic()
    return ha_client, llm_client


def build_fresh_controller(ha_client, llm_client, backend: str, model: str, tau: float):
    """每轮重建 Registry→Engine→Controller(镜像 conversation.py 的安全不变量)。
    任一 HA 拉取失败 → 异常冒泡(fail-closed),调用方据此返回 error,绝不退回旧注册表。
    ha_client 可为 DeadlineHAClient 包装实例(执行经它,故死线生效)。"""
    states, services = ha_client.fetch()
    snap = build_registry_snapshot(*ha_client.fetch_registries(), config=ha_client.fetch_config())
    reg = Registry.from_ha(states, services, snapshot=snap)

    def context_provider() -> str:
        return build_context(ha_client.fetch()[0], reg)

    if backend == "local":
        from gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, model, client=llm_client, context_provider=context_provider)
    else:
        from gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, model, client=llm_client, context_provider=context_provider)

    engine = Engine(parser, reg, tau, state_provider=lambda: ha_client.fetch()[0])
    return Controller(engine, ha_client)
