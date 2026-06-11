# Janus C-lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Home Assistant custom integration (`custom_components/janus/`) — config flow asks one question (LLM source), registers a conversation agent in HA Assist, and routes every utterance through the gatekeeper safety gates.

**Architecture:** In-process integration. `bridge.py` (pure, duck-typed, imports NEITHER homeassistant NOR gatekeeper) converts hass-shaped objects into the raw dicts the existing pure logic already eats; `HassServiceCaller` adapts execution back onto the event loop via `run_coroutine_threadsafe`. The CLI's `Repl` is reused verbatim per `conversation_id`. The `gatekeeper/` package is vendored into the component at deploy time (all-relative imports make it copy-safe); a deploy script `docker cp`s into the HA container.

**Tech Stack:** Python 3.11+, HA 2026.6.0 (Docker, volume `ha_config`), voluptuous (HA built-in), anthropic/openai/pydantic via manifest requirements.

---

## File Structure

- Create: `custom_components/janus/const.py` — `DOMAIN = "janus"` (single source).
- Create: `custom_components/janus/manifest.json`, `strings.json`, `translations/en.json` — integration metadata + form labels.
- Create: `custom_components/janus/bridge.py` — 6 shape converters + `HassServiceCaller`.
- Create: `custom_components/janus/__init__.py` — setup/unload. **RED LINE: module level imports ONLY stdlib + `.const` + `.bridge`** — `homeassistant.*` and `.gatekeeper.*` exist only inside HA at runtime (gatekeeper/ is vendored at deploy, gitignored in repo), so they MUST be imported inside functions or tests importing `custom_components.janus.bridge` will explode.
- Create: `custom_components/janus/config_flow.py`, `conversation.py` — HA-only modules (never imported by tests; top-level HA imports fine).
- Create: `harness/deploy_janus.sh` — vendor + docker cp + restart.
- Create: `tests/test_bridge.py` — converter + caller + end-to-end-shape tests.
- Modify: `.gitignore` — ignore the vendored copy.

---

## Task J1: scaffold (const, manifest, strings, gitignore)

**Files:**
- Create: `custom_components/janus/const.py`, `custom_components/janus/manifest.json`, `custom_components/janus/strings.json`, `custom_components/janus/translations/en.json`
- Modify: `.gitignore`

- [ ] **Step 1: Create `custom_components/janus/const.py`**

```python
DOMAIN = "janus"
```

- [ ] **Step 2: Create `custom_components/janus/manifest.json`**

```json
{
  "domain": "janus",
  "name": "Janus",
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["conversation"],
  "documentation": "https://github.com/alextangson/janus",
  "integration_type": "service",
  "iot_class": "local_polling",
  "requirements": ["anthropic>=0.39", "openai>=1.40", "pydantic>=2.5"],
  "version": "0.1.0"
}
```

- [ ] **Step 3: Create `custom_components/janus/strings.json`** (and an identical copy at `custom_components/janus/translations/en.json`)

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Janus — LLM 来源",
        "data": {"backend": "后端"}
      },
      "claude": {
        "title": "Anthropic API Key",
        "data": {"api_key": "API Key"}
      },
      "local": {
        "title": "本地模型(Ollama,OpenAI 兼容)",
        "data": {"base_url": "Base URL", "model": "模型名"}
      }
    },
    "error": {"invalid_key": "API Key 不能为空"}
  }
}
```

- [ ] **Step 4: Append to `.gitignore`**

```
custom_components/janus/gatekeeper/
```

- [ ] **Step 5: Verify JSON validity**

Run: `python3 -m json.tool custom_components/janus/manifest.json >/dev/null && python3 -m json.tool custom_components/janus/strings.json >/dev/null && python3 -m json.tool custom_components/janus/translations/en.json >/dev/null && echo JSON_OK`
Expected: `JSON_OK`

- [ ] **Step 6: Commit**

```bash
git add custom_components/janus/const.py custom_components/janus/manifest.json custom_components/janus/strings.json custom_components/janus/translations/en.json .gitignore
git commit -m "feat: Janus integration scaffold (manifest, strings, domain const)"
```

---

## Task J2: bridge converters + HassServiceCaller (TDD)

**Files:**
- Create: `custom_components/janus/bridge.py`
- Create: `custom_components/janus/__init__.py` (MINIMAL stub for importability — Task J3 fills it)
- Create: `tests/test_bridge.py`

- [ ] **Step 1: Create the minimal package init** — `custom_components/janus/__init__.py`:

```python
"""Janus — AI 安全网关 conversation agent。完整 setup 见 Task J3。"""
from __future__ import annotations

from .const import DOMAIN  # noqa: F401
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_bridge.py`:

```python
import asyncio
import threading
from enum import Enum
from types import SimpleNamespace

from custom_components.janus.bridge import (
    HassServiceCaller,
    areas_from_registry,
    config_from_hass,
    devices_from_registry,
    entities_from_registry,
    services_from_hass,
    states_from_hass,
)


class _Cat(Enum):  # 模拟 HA 的 EntityCategory 枚举
    CONFIG = "config"


def test_states_from_hass():
    s = SimpleNamespace(entity_id="light.a", attributes={"friendly_name": "主灯"})
    assert states_from_hass([s]) == [{"entity_id": "light.a",
                                      "attributes": {"friendly_name": "主灯"}}]


def test_services_from_hass():
    out = services_from_hass({"light": {"turn_on": object(), "turn_off": object()}})
    assert out == [{"domain": "light", "services": {"turn_on": {}, "turn_off": {}}}]


def test_entities_from_registry_enum_category_to_str():
    e1 = SimpleNamespace(entity_id="light.ind", device_id="d1", area_id=None,
                         entity_category=_Cat.CONFIG)
    e2 = SimpleNamespace(entity_id="light.a", device_id="d1", area_id="a1",
                         entity_category=None)
    out = entities_from_registry([e1, e2])
    assert out[0]["entity_category"] == "config"
    assert out[1] == {"entity_id": "light.a", "device_id": "d1",
                      "area_id": "a1", "entity_category": None}


def test_devices_from_registry_sets_to_lists():
    d = SimpleNamespace(id="d1", area_id="a1",
                        identifiers={("xiaomi_miot", "MAC-CE1")},
                        config_entries={"CE1"},
                        name_by_user=None, name="空调插座")
    out = devices_from_registry([d])
    assert out == [{"id": "d1", "area_id": "a1",
                    "identifiers": [["xiaomi_miot", "MAC-CE1"]],
                    "config_entries": ["CE1"], "name": "空调插座"}]


def test_areas_from_registry():
    a = SimpleNamespace(id="a1", name="卧室")
    assert areas_from_registry([a]) == [{"area_id": "a1", "name": "卧室"}]


def test_config_from_hass():
    assert config_from_hass("°F") == {"unit_system": {"temperature": "°F"}}


def test_converters_feed_existing_pure_logic_end_to_end():
    """组合验证:bridge 输出直接喂 build_registry_snapshot + Registry.from_ha。"""
    from gatekeeper.ha_mapping import build_registry_snapshot
    from gatekeeper.registry import Registry

    states = states_from_hass([
        SimpleNamespace(entity_id="light.a", attributes={"friendly_name": "主灯"}),
        SimpleNamespace(entity_id="switch.cam_wm", attributes={"friendly_name": "水印"}),
    ])
    services = services_from_hass({"light": {"turn_on": 0, "turn_off": 0},
                                   "switch": {"turn_on": 0, "turn_off": 0}})
    entities = entities_from_registry([
        SimpleNamespace(entity_id="light.a", device_id="dl", area_id="a1", entity_category=None),
        SimpleNamespace(entity_id="switch.cam_wm", device_id="dc", area_id=None, entity_category=None),
        SimpleNamespace(entity_id="camera.cam", device_id="dc", area_id=None, entity_category=None),
    ])
    devices = devices_from_registry([
        SimpleNamespace(id="dl", area_id="a1", identifiers={("m", "L")},
                        config_entries=set(), name_by_user=None, name="灯"),
        SimpleNamespace(id="dc", area_id=None, identifiers={("m", "C")},
                        config_entries=set(), name_by_user=None, name="摄像机"),
    ])
    areas = areas_from_registry([SimpleNamespace(id="a1", name="卧室")])
    snap = build_registry_snapshot(entities, devices, areas, config=config_from_hass("°C"))
    reg = Registry.from_ha(states, services, snapshot=snap)
    d = reg.get("light.a")
    assert d is not None and d.area == "卧室"          # area join 生效
    assert reg.get("switch.cam_wm") is None            # 从属开关被策展(camera 主域兄弟)


def test_hass_service_caller_round_trip():
    calls = []

    class FakeServices:
        async def async_call(self, domain, service, data, blocking=True):
            calls.append((domain, service, data, blocking))

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    hass = SimpleNamespace(services=FakeServices(), loop=loop)
    HassServiceCaller(hass).call_service("light", "turn_on", "light.a", {"brightness_pct": 50})
    loop.call_soon_threadsafe(loop.stop)
    assert calls == [("light", "turn_on",
                      {"entity_id": "light.a", "brightness_pct": 50}, True)]
```

- [ ] **Step 3: Run to verify fail**

Run: `.venv/bin/pytest tests/test_bridge.py -v`
Expected: FAIL (`No module named 'custom_components.janus.bridge'`).

- [ ] **Step 4: Create `custom_components/janus/bridge.py`**

```python
"""hass 形状对象 → 纯逻辑层原始 dict;以及执行适配器。

红线:本模块不 import homeassistant、不 import gatekeeper——鸭子类型,纯转换,
无 HA 环境即可单测。
"""
from __future__ import annotations

import asyncio


def states_from_hass(states) -> list:
    return [{"entity_id": s.entity_id, "attributes": dict(s.attributes)} for s in states]


def services_from_hass(services_by_domain) -> list:
    return [{"domain": domain, "services": {name: {} for name in services}}
            for domain, services in services_by_domain.items()]


def entities_from_registry(entries) -> list:
    out = []
    for e in entries:
        cat = e.entity_category
        out.append({
            "entity_id": e.entity_id,
            "device_id": e.device_id,
            "area_id": e.area_id,
            "entity_category": getattr(cat, "value", cat),
        })
    return out


def devices_from_registry(entries) -> list:
    return [{
        "id": d.id,
        "area_id": d.area_id,
        "identifiers": [list(i) for i in (d.identifiers or [])],
        "config_entries": list(d.config_entries or []),
        "name": d.name_by_user or d.name,
    } for d in entries]


def areas_from_registry(entries) -> list:
    return [{"area_id": a.id, "name": a.name} for a in entries]


def config_from_hass(temperature_unit: str) -> dict:
    return {"unit_system": {"temperature": temperature_unit}}


class HassServiceCaller:
    """Controller 期望的同步 call_service;投递回 HA 事件循环执行。

    只能从 executor 线程调用(repl.feed 整体跑在 executor),
    绝不能在事件循环线程里调用——.result() 会死锁。
    """

    def __init__(self, hass, timeout: float = 10.0):
        self._hass = hass
        self._timeout = timeout

    def call_service(self, domain: str, service: str, entity_id: str,
                     params: dict | None = None):
        future = asyncio.run_coroutine_threadsafe(
            self._hass.services.async_call(
                domain, service, {"entity_id": entity_id, **(params or {})},
                blocking=True),
            self._hass.loop,
        )
        return future.result(self._timeout)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_bridge.py -v` → 8 PASS
Run FULL suite: `.venv/bin/pytest -q` → all green.

- [ ] **Step 6: Commit**

```bash
git add custom_components/janus/__init__.py custom_components/janus/bridge.py tests/test_bridge.py
git commit -m "feat: bridge — hass-shape converters + thread-safe service caller"
```

---

## Task J3: integration setup (`__init__.py`) + config flow

**Files:**
- Modify: `custom_components/janus/__init__.py`
- Create: `custom_components/janus/config_flow.py`

No unit tests (HA-runtime modules); verified by import-discipline check + py_compile + the Task J5 real-machine acceptance.

- [ ] **Step 1: Replace `custom_components/janus/__init__.py`**

```python
"""Janus — 给任何 LLM 套上安全门的 HA 对话代理。

红线:模块级只准 import 标准库 / .const / .bridge。
homeassistant.* 与 .gatekeeper.*(部署期注入)只存在于 HA 运行时,必须函数内导入,
否则单测 import custom_components.janus.bridge 会触发本文件而炸。
"""
from __future__ import annotations

from .const import DOMAIN

PLATFORMS = ["conversation"]


async def async_setup_entry(hass, entry) -> bool:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from .bridge import (HassServiceCaller, areas_from_registry, config_from_hass,
                         devices_from_registry, entities_from_registry,
                         services_from_hass, states_from_hass)
    from .gatekeeper.config import MODEL, TAU
    from .gatekeeper.controller import Controller
    from .gatekeeper.engine import Engine
    from .gatekeeper.ha_mapping import build_registry_snapshot
    from .gatekeeper.registry import Registry

    snap = build_registry_snapshot(
        entities_from_registry(er.async_get(hass).entities.values()),
        devices_from_registry(dr.async_get(hass).devices.values()),
        areas_from_registry(ar.async_get(hass).areas.values()),
        config=config_from_hass(hass.config.units.temperature_unit),
    )
    reg = Registry.from_ha(
        states_from_hass(hass.states.async_all()),
        services_from_hass(hass.services.async_services()),
        snapshot=snap,
    )

    data = entry.data
    if data["backend"] == "local":
        from .gatekeeper.local_parser import LocalParser
        parser = LocalParser(reg, data["model"], base_url=data["base_url"])
    else:
        from anthropic import Anthropic

        from .gatekeeper.parser import ClaudeParser
        parser = ClaudeParser(reg, MODEL, client=Anthropic(api_key=data["api_key"]))

    controller = Controller(Engine(parser, reg, TAU), HassServiceCaller(hass))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
```

- [ ] **Step 2: Create `custom_components/janus/config_flow.py`**

```python
"""配置向导:唯一的问题——LLM 从哪来。HA 运行时模块,测试不导入。"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN

_DEFAULT_BASE_URL = "http://host.docker.internal:11434/v1"


class JanusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            if user_input["backend"] == "claude":
                return await self.async_step_claude()
            return await self.async_step_local()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("backend", default="local"): vol.In(["claude", "local"])}),
        )

    async def async_step_claude(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input["api_key"].strip()
            if key:
                return self.async_create_entry(
                    title="Janus (Claude)", data={"backend": "claude", "api_key": key})
            errors["api_key"] = "invalid_key"
        return self.async_show_form(
            step_id="claude",
            data_schema=vol.Schema({vol.Required("api_key"): str}),
            errors=errors,
        )

    async def async_step_local(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"Janus ({user_input['model']})",
                data={"backend": "local", **user_input})
        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema({
                vol.Required("base_url", default=_DEFAULT_BASE_URL): str,
                vol.Required("model", default="gemma4"): str,
            }),
        )
```

- [ ] **Step 3: Verify import discipline + syntax**

Run: `.venv/bin/python -c "import custom_components.janus, custom_components.janus.bridge; print('import ok')"` → `import ok`(证明模块级无 HA 依赖)
Run: `.venv/bin/python -m py_compile custom_components/janus/__init__.py custom_components/janus/config_flow.py && echo COMPILE_OK` → `COMPILE_OK`
Run FULL suite: `.venv/bin/pytest -q` → all green.

- [ ] **Step 4: Commit**

```bash
git add custom_components/janus/__init__.py custom_components/janus/config_flow.py
git commit -m "feat: Janus setup entry (in-process registry + parser wiring) and config flow"
```

---

## Task J4: conversation agent

**Files:**
- Create: `custom_components/janus/conversation.py`

HA-runtime module; verified by py_compile + real-machine acceptance. NOTE for the engineer: the conversation entity API import paths below are per HA 2024.2+ stable surface. If HA 2026.6 moved anything, inspect the real source inside the container with `docker exec homeassistant ls /usr/src/homeassistant/homeassistant/components/conversation/` and adjust imports only — report the deviation.

- [ ] **Step 1: Create `custom_components/janus/conversation.py`**

```python
"""Assist 对话代理:每个 conversation_id 一台 Repl,复用 CLI 的纯逻辑状态机。"""
from __future__ import annotations

from homeassistant.components.conversation import (ConversationEntity,
                                                   ConversationInput,
                                                   ConversationResult)
from homeassistant.const import MATCH_ALL
from homeassistant.helpers import intent

from .const import DOMAIN
from .gatekeeper.cli import Repl

_EMPTY_REPLY = "请说出要执行的指令,例如:打开空调。"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JanusConversationEntity(entry, controller)])


class JanusConversationEntity(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry, controller):
        self._attr_unique_id = entry.entry_id
        self._controller = controller
        self._repls: dict[str, Repl] = {}

    @property
    def supported_languages(self):
        return MATCH_ALL

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        conv_id = user_input.conversation_id or "default"
        repl = self._repls.setdefault(conv_id, Repl(self._controller))
        reply = await self.hass.async_add_executor_job(repl.feed, user_input.text)
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(reply or _EMPTY_REPLY)
        return ConversationResult(response=response, conversation_id=conv_id)
```

- [ ] **Step 2: Verify syntax + import discipline still holds**

Run: `.venv/bin/python -m py_compile custom_components/janus/conversation.py && echo COMPILE_OK` → `COMPILE_OK`
Run: `.venv/bin/python -c "import custom_components.janus.bridge; print('ok')"` → `ok`(conversation.py 不被包 __init__ 引)
Run FULL suite: `.venv/bin/pytest -q` → all green.

- [ ] **Step 3: Commit**

```bash
git add custom_components/janus/conversation.py
git commit -m "feat: Janus conversation entity — Repl per conversation_id over Assist"
```

---

## Task J5: deploy script

**Files:**
- Create: `harness/deploy_janus.sh`

- [ ] **Step 1: Create `harness/deploy_janus.sh`**

```bash
#!/bin/bash
# 部署 Janus 进本机 HA(Docker named volume):vendor gatekeeper → docker cp → 重启。
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf custom_components/janus/gatekeeper
cp -R gatekeeper custom_components/janus/gatekeeper
find custom_components/janus -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

docker exec homeassistant mkdir -p /config/custom_components
docker exec homeassistant rm -rf /config/custom_components/janus
docker cp custom_components/janus homeassistant:/config/custom_components/
docker restart homeassistant
echo "Janus 已部署;HA 重启中(约 30-60s 后可用)。"
```

- [ ] **Step 2: Make executable + sanity-run the vendor half only**

Run: `chmod +x harness/deploy_janus.sh && bash -n harness/deploy_janus.sh && echo SYNTAX_OK` → `SYNTAX_OK`

- [ ] **Step 3: Commit**

```bash
git add harness/deploy_janus.sh
git commit -m "chore: Janus deploy script (vendor gatekeeper, docker cp, restart)"
```

---

## Task J6: real-machine acceptance (controller runs this)

Manual, on this MacBook. This time executions are REAL (catalog is the 4 real devices). All driven via HA REST API from the terminal; the user can replay in the HA App afterwards.

- [ ] **Step 1: Ensure Ollama reachable from the container**

Ollama binds 127.0.0.1 by default — the container can't reach that. Restart it listening on all interfaces, then probe from inside the container:
```bash
pkill ollama 2>/dev/null; sleep 1
OLLAMA_HOST=0.0.0.0 nohup ollama serve >/tmp/ollama.log 2>&1 &
sleep 3
docker exec homeassistant python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).status)"
```
Expected: `200`. If `host.docker.internal` fails under colima, try `http://192.168.5.2:11434` (lima host gateway) and use THAT as base_url in Step 3; record the working value.

- [ ] **Step 2: Deploy**

Run: `bash harness/deploy_janus.sh` then wait for HA: `until NO_PROXY=localhost curl -s -o /dev/null -w '%{http_code}' http://localhost:8123/ | grep -q 200; do sleep 3; done; echo HA_UP`

- [ ] **Step 3: Create the config entry via the config-flow REST API**

```bash
TOKEN=$(grep GATEKEEPER_HA_TOKEN .env | cut -d= -f2)
# 起 flow
FLOW=$(NO_PROXY=localhost curl -s -X POST http://localhost:8123/api/config/config_entries/flow \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"handler": "janus"}')
FLOW_ID=$(echo "$FLOW" | python3 -c "import sys,json; print(json.load(sys.stdin)['flow_id'])")
# 第一步:选 local
NO_PROXY=localhost curl -s -X POST http://localhost:8123/api/config/config_entries/flow/$FLOW_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"backend": "local"}' >/dev/null
# 第二步:base_url + model(用 Step 1 实测可达的 URL)
NO_PROXY=localhost curl -s -X POST http://localhost:8123/api/config/config_entries/flow/$FLOW_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"base_url": "http://host.docker.internal:11434/v1", "model": "gemma4"}'
```
Expected: final response JSON has `"type": "create_entry"`.

- [ ] **Step 4: Find the agent and run the three acceptance conversations**

```bash
# agent 实体 id
NO_PROXY=localhost curl -s http://localhost:8123/api/states -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print([s['entity_id'] for s in json.load(sys.stdin) if s['entity_id'].startswith('conversation.')])"
```
Then for each utterance use `/api/conversation/process` with the janus agent id (replace `conversation.janus` with the actual id):
```bash
say() { NO_PROXY=localhost curl -s -X POST http://localhost:8123/api/conversation/process \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"text\": \"$1\", \"language\": \"zh\", \"agent_id\": \"conversation.janus\", \"conversation_id\": \"accept-1\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['response']['speech']['plain']['speech'])"; }

say "打开空调"            # 期望:✅ 已执行:climate.lumi_….turn_on(真执行)
say "关掉卧室的灯"        # 期望:你是说哪一个?1) … 2) …
say "2"                  # 期望:✅ 已执行:light.yeelink_…(其中一盏,真执行)
say "把空调调到26度"      # 期望:✅(gemma4 换算 °F)或合理 confirm
```
Acceptance: ① AC turn_on executes (verify state: `curl …/api/states/climate.lumi_mcn02_fa3f_air_conditioner` shows non-off);② disambiguation question appears and the numbered reply executes;③ no stack traces in `docker logs homeassistant 2>&1 | grep -i janus`.

- [ ] **Step 5: Restore comfort + record**

Turn the AC/light back to their prior states via two more `say` commands (or HA UI), note the working base_url in the spec's §7 if it differed, and report results.

---

## Final: full regression + tree

- [ ] **Step 1:** `.venv/bin/pytest -q` → all pass (154 existing + 8 new), zero failures.
- [ ] **Step 2:** `git status` → clean (vendored `custom_components/janus/gatekeeper/` must be ignored, not untracked noise).
