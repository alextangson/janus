from __future__ import annotations

import re

from .controller import Outcome
from .models import ParamSpec
from .queries import _HVAC_ZH

_YES = {"y", "yes", "是", "好"}
_NO = {"n", "no", "否", "取消"}
_DEVICES = {"设备", "/devices"}


def coerce_param(reply: str, spec: ParamSpec) -> int | str | None:
    """把用户对反问的回答确定性转成参数值;转不出 → None(由调用方重问)。不调模型。"""
    if spec.type == "int":
        m = re.search(r"-?\d+", reply)
        return int(m.group()) if m else None
    if spec.type == "enum":
        for v in (spec.enum or []):
            if v in reply or _HVAC_ZH.get(v, "\0") in reply:
                return v
    return None


class Repl:
    """纯逻辑 REPL 核心:feed(一行输入) → 一段回复。pending 在这里,Controller 保持无状态。"""

    def __init__(self, controller):
        self.controller = controller
        self.pending: Outcome | None = None

    def feed(self, line: str) -> str:
        line = line.strip()
        if self.pending is not None:
            return self._feed_pending(line)
        if not line:
            return ""
        if line.lower() in _DEVICES:  # 本地命令:不走 LLM
            return self._render_devices()
        return self._render(self.controller.handle(line))

    def _render_devices(self) -> str:
        reg = self.controller.engine.registry
        lines = []
        for did in reg.device_ids():
            d = reg.get(did)
            area = f" @{d.area}" if d.area else ""
            lines.append(f"- {d.name}{area} ({did})")
        return f"共 {len(lines)} 个设备:\n" + "\n".join(lines)

    def _feed_pending(self, line: str) -> str:
        pending = self.pending
        if pending.choices:  # 歧义:等序号
            if line.lower() in _NO:
                self.pending = None
                return "已取消"
            if line.isdigit() and 1 <= int(line) <= len(pending.choices):
                self.pending = None
                chosen = pending.choices[int(line) - 1]
                return self._render(self.controller.choose(pending.decision, chosen))
            return pending.prompt or ""  # 没听懂 → 重示
        if pending.needs_param:  # 缺参数:等一个值
            if line.lower() in _NO:
                self.pending = None
                return "已取消"
            dec = pending.decision
            device = self.controller.engine.registry.get(dec.device_id)
            spec = device.operations[dec.operation].params[dec.missing_param]
            value = coerce_param(line, spec)
            if value is None:
                return pending.prompt or ""  # 没听懂 → 重示
            self.pending = None
            return self._render(self.controller.provide_param(dec, value))
        if line.lower() in _YES:  # 是/否确认
            self.pending = None
            return self._render(self.controller.confirm(pending.decision, approved=True))
        if line.lower() in _NO:
            self.pending = None
            return "已取消"
        return pending.prompt or ""

    def _render(self, outcome: Outcome) -> str:
        if outcome.executed:
            d = outcome.decision
            return f"✅ 已执行:{d.device_id}.{d.operation}"
        if outcome.error:
            return f"❌ 失败:{outcome.error}"
        if outcome.needs_confirmation or outcome.needs_param:  # 含链式危险确认 / 缺参数反问
            self.pending = outcome
            return outcome.prompt or ""
        if outcome.decision.verdict == "answer":
            return f"🔎 {outcome.decision.reason}"
        return f"🚫 {outcome.decision.reason or '已取消'}"


_EXIT = {"exit", "quit", "q"}


def main() -> None:
    import os

    from .config import BACKEND, LOCAL_MODEL, MODEL, TAU, load_env
    from .context import build_context
    from .controller import Controller
    from .engine import Engine
    from .ha_client import HAClient
    from .ha_mapping import build_registry_snapshot
    from .registry import Registry

    load_env()
    url = os.environ.get("GATEKEEPER_HA_URL")
    token = os.environ.get("GATEKEEPER_HA_TOKEN")
    if not url or not token:
        raise SystemExit("缺少 GATEKEEPER_HA_URL / GATEKEEPER_HA_TOKEN(.env 或环境变量)")

    client = HAClient(url, token=token)
    states, services = client.fetch()
    snap = build_registry_snapshot(*client.fetch_registries(), config=client.fetch_config())
    reg = Registry.from_ha(states, services, snapshot=snap)

    def context_provider() -> str:
        return build_context(client.fetch()[0], reg)  # 每轮重拉,状态保持新鲜

    if BACKEND == "local":
        from .local_parser import LocalParser
        parser, model_desc = (LocalParser(reg, LOCAL_MODEL, context_provider=context_provider),
                              f"local/{LOCAL_MODEL}")
    else:
        from .parser import ClaudeParser
        parser, model_desc = (ClaudeParser(reg, MODEL, context_provider=context_provider),
                              f"claude/{MODEL}")

    repl = Repl(Controller(Engine(parser, reg, TAU,
                                  state_provider=lambda: client.fetch()[0]), client))
    print(f"gatekeeper REPL — {len(reg.device_ids())} 设备 | {model_desc} | τ={TAU} | 温度单位 {snap.temperature_unit}")
    print("输入指令开始;「设备」看清单,exit 退出。")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        line_l = line.strip().lower()
        if line_l in _EXIT:
            return
        if line.strip() and repl.pending is None and line_l not in _DEVICES:
            print("(模型解析中…按 Ctrl-C 取消本条)", flush=True)
        try:
            reply = repl.feed(line)
        except KeyboardInterrupt:
            repl.pending = None  # 丢弃半截状态,确定性回到空闲
            print("(已取消本条指令)")
            continue
        if reply:
            print(reply)


if __name__ == "__main__":
    main()
