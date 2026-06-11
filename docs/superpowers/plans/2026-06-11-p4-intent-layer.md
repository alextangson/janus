# P4.1+P4.2 意图层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 「我感觉有点冷」→ `💡 室外 14°C 偏凉,建议把空调调到 26°C。确认执行…吗?` — context injection (device states + weather into the prompt) plus an explicit inferred-intent contract that always lands on confirm.

**Architecture:** New pure `gatekeeper/context.py` (`build_context(states, registry)` renders a deterministic, gracefully-degrading status block). Parsers gain an optional `context_provider` callable (failure → warning + parse without context). `ParseResult.inferred` is an explicit field; the engine forces `confirm/inferred` after feasibility and before τ; Controller renders the 💡 prompt. CLI and Janus wire fresh-per-turn providers.

**Tech Stack:** Python 3.11+, pydantic v2, pytest. No new dependencies. No model needed until the final real-machine task.

---

## File Structure

- Create: `gatekeeper/context.py` — `build_context` pure renderer.
- Modify: `gatekeeper/models.py` — `ParseResult.inferred`, Stage + `"inferred"`.
- Modify: `gatekeeper/prompts.py` — `build_user_prompt(context=...)` + SYSTEM_PROMPT inferred rule.
- Modify: `gatekeeper/parser.py`, `gatekeeper/local_parser.py` — `context_provider` param.
- Modify: `gatekeeper/engine.py` — inferred gate.
- Modify: `gatekeeper/controller.py` — 💡 prompt branch.
- Modify: `gatekeeper/cli.py`, `custom_components/janus/__init__.py` — provider wiring.
- Create: `harness/p4_intent_check.py` — real-machine check (decide-only asserts + context printout).
- Tests: `tests/test_context.py` (new), plus additions to `tests/test_models.py`, `tests/test_parser.py`, `tests/test_local_parser.py`, `tests/test_engine.py`, `tests/test_controller.py`.

Background: gate order in `Engine.decide` is recognized → ambiguity → feasibility → (NEW: inferred) → τ → danger. `ParseResult.notes: str = ""` already exists. Both parsers call `build_user_prompt(self.registry, instruction)`. Real-machine facts shaping `build_context`: this home has NO room-temperature signal (no temperature sensors; climate `current_temperature=None`) but HAS `weather.forecast_jia` — the renderer must degrade gracefully and must be deterministically ordered (catalog-order drift caused a live hallucination once; never again).

---

## Task N1: models — inferred + stage

**Files:**
- Modify: `gatekeeper/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests** — add to `tests/test_models.py`:

```python
def test_parse_result_inferred_defaults_false():
    from gatekeeper.models import ParseResult
    assert ParseResult(recognized=True).inferred is False


def test_decision_accepts_inferred_stage():
    from gatekeeper.models import Decision
    d = Decision(verdict="confirm", stage="inferred", reason="室外偏凉,建议调高空调")
    assert d.stage == "inferred"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_models.py -k inferred -v`
Expected: FAIL (no field `inferred` / invalid stage literal).

- [ ] **Step 3: Implement** — in `gatekeeper/models.py`:
- In `ParseResult`, add after `candidates`: `inferred: bool = False`
- Change `Stage` to: `Stage = Literal["parse", "ambiguous", "feasibility", "inferred", "confidence", "safety", "passed", "error"]`

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_models.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/models.py tests/test_models.py
git commit -m "feat: ParseResult.inferred contract + inferred stage"
```

---

## Task N2: context.py — build_context

**Files:**
- Create: `gatekeeper/context.py`
- Create: `tests/test_context.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_context.py`:

```python
from gatekeeper.context import build_context
from gatekeeper.models import Device, OperationSpec
from gatekeeper.registry import Registry


def _registry():
    return Registry({
        "climate.ac": Device(name="空调", type="climate", area="卧室",
                             operations={"turn_on": OperationSpec()}),
        "light.a": Device(name="主灯", type="light", area="卧室",
                          operations={"turn_on": OperationSpec()}),
    })


def _states():
    return [
        {"entity_id": "light.a", "state": "on", "attributes": {}},
        {"entity_id": "climate.ac", "state": "off",
         "attributes": {"temperature": 24.0, "current_temperature": None}},
        {"entity_id": "weather.home", "state": "partlycloudy",
         "attributes": {"temperature": 14.0, "temperature_unit": "°C", "humidity": 74}},
        {"entity_id": "sensor.bedroom_temp", "state": "22.5",
         "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                        "friendly_name": "卧室温度"}},
        {"entity_id": "switch.hidden_sub", "state": "on", "attributes": {}},  # 不在目录 → 不渲染
        "garbage",  # 畸形 → 跳过
    ]


def test_renders_curated_devices_only_sorted():
    out = build_context(_states(), _registry())
    assert "- climate.ac: off,目标 24.0°" in out
    assert "- light.a: on" in out
    assert "switch.hidden_sub" not in out
    # 设备行按 id 排序:climate 在 light 前
    assert out.index("climate.ac") < out.index("light.a")


def test_climate_room_temp_omitted_when_none():
    out = build_context(_states(), _registry())
    assert "室温" not in out.split("\n")[0]  # current_temperature=None → 不渲染室温段


def test_weather_and_sensor_lines():
    out = build_context(_states(), _registry())
    assert "- 室外(weather.home): partlycloudy,14.0°C,湿度 74%" in out
    assert "- 卧室温度: 22.5 °C" in out


def test_missing_environment_degrades():
    states = [{"entity_id": "light.a", "state": "off", "attributes": {}}]
    out = build_context(states, _registry())
    assert "室外" not in out and "光" not in out
    assert "- light.a: off" in out


def test_climate_room_temp_rendered_when_present():
    states = [{"entity_id": "climate.ac", "state": "cool",
               "attributes": {"temperature": 26, "current_temperature": 28.5}}]
    out = build_context(states, _registry())
    assert "- climate.ac: cool,目标 26°,室温 28.5°" in out
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_context.py -v`
Expected: FAIL (`No module named 'gatekeeper.context'`).

- [ ] **Step 3: Create `gatekeeper/context.py`**

```python
"""当前状态渲染:设备运行状态 + 环境信号 → 给模型推断用的文本块。

纯函数;输出按 entity_id 排序(prompt 必须跨进程稳定);缺数据的段落省略,
绝不编造;畸形条目跳过不崩。
"""
from __future__ import annotations

from .registry import Registry


def build_context(states: list, registry: Registry) -> str:
    by_id: dict[str, dict] = {}
    for st in states:
        if isinstance(st, dict) and st.get("entity_id"):
            by_id[st["entity_id"]] = st

    lines: list[str] = []
    for device_id in sorted(registry.device_ids()):
        st = by_id.get(device_id)
        if not st:
            continue
        attrs = st.get("attributes") or {}
        line = f"- {device_id}: {st.get('state', 'unknown')}"
        if device_id.startswith("climate."):
            if attrs.get("temperature") is not None:
                line += f",目标 {attrs['temperature']}°"
            if attrs.get("current_temperature") is not None:
                line += f",室温 {attrs['current_temperature']}°"
        lines.append(line)

    for eid in sorted(by_id):
        st = by_id[eid]
        attrs = st.get("attributes") or {}
        if eid.startswith("weather."):
            line = f"- 室外({eid}): {st.get('state', '')}"
            if attrs.get("temperature") is not None:
                line += f",{attrs['temperature']}{attrs.get('temperature_unit', '')}"
            if attrs.get("humidity") is not None:
                line += f",湿度 {attrs['humidity']}%"
            lines.append(line)
        elif eid.startswith("sensor.") and attrs.get("device_class") in ("temperature", "humidity"):
            name = attrs.get("friendly_name", eid)
            unit = attrs.get("unit_of_measurement", "")
            lines.append(f"- {name}: {st.get('state')} {unit}".rstrip())

    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_context.py -v` → 5 PASS

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/context.py tests/test_context.py
git commit -m "feat: build_context — deterministic, degrading status block for inference"
```

---

## Task N3: prompts — context slot + inferred rule

**Files:**
- Modify: `gatekeeper/prompts.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Write the failing tests** — add to `tests/test_parser.py`:

```python
def test_user_prompt_inserts_context_between_catalog_and_instruction():
    from gatekeeper.prompts import build_user_prompt
    from gatekeeper.registry import Registry
    reg = Registry({})
    out = build_user_prompt(reg, "开灯", context="- climate.ac: off")
    assert "当前状态(供推断参考):\n- climate.ac: off" in out
    assert out.index("当前状态") < out.index("用户指令:开灯")
    # 不传 context 时不出现该段
    assert "当前状态" not in build_user_prompt(reg, "开灯")


def test_system_prompt_teaches_inferred():
    from gatekeeper.prompts import SYSTEM_PROMPT
    assert "inferred" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_parser.py -k "context_between or teaches_inferred" -v`
Expected: FAIL (`build_user_prompt() got an unexpected keyword argument 'context'`).

- [ ] **Step 3: Implement** — in `gatekeeper/prompts.py`:

Replace `build_user_prompt` with:

```python
def build_user_prompt(registry: Registry, instruction: str, context: str | None = None) -> str:
    parts = [
        "可用设备清单(只能从中选择 device_id 与 operation):\n"
        f"{registry.as_prompt_catalog()}",
    ]
    if context:
        parts.append(f"当前状态(供推断参考):\n{context}")
    parts.append(f"用户指令:{instruction}\n\n请调用 emit_parse 输出解析结果。")
    return "\n\n".join(parts)
```

In SYSTEM_PROMPT, add ONE rule after the candidates rule (the line ending `…明确无歧义时 candidates 必须为空。`):

```
- 若指令是模糊的舒适度/感受表达(冷、热、闷、暗等)而非明确命令:照常填 device_id/operation/params(结合"当前状态"推断合理参数),令 inferred=true,并在 notes 用一句中文说明推断理由(如"室外 14°C 偏凉,建议把空调调到 26°C")。明确指令时 inferred 必须为 false。
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_parser.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/prompts.py tests/test_parser.py
git commit -m "feat: prompt context slot + inferred-intent rule"
```

---

## Task N4: parsers — context_provider

**Files:**
- Modify: `gatekeeper/parser.py`, `gatekeeper/local_parser.py`
- Test: `tests/test_parser.py`, `tests/test_local_parser.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_parser.py` (the file already has a `_StubClient`-style fake recording `messages.create` kwargs — reuse its pattern; if its fake is named differently, adapt the construction but keep the assertions):

```python
def test_claude_parser_injects_context(monkeypatch):
    from gatekeeper.parser import ClaudeParser
    from gatekeeper.registry import Registry

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop here")  # 只验 prompt,不需要完整响应

    class _FakeClient:
        messages = _FakeMessages()

    p = ClaudeParser(Registry({}), "m", client=_FakeClient(), max_retries=0,
                     context_provider=lambda: "- climate.ac: off")
    try:
        p.parse("有点冷")
    except RuntimeError:
        pass
    assert "- climate.ac: off" in captured["messages"][0]["content"]


def test_claude_parser_context_failure_degrades(monkeypatch):
    from gatekeeper.parser import ClaudeParser
    from gatekeeper.registry import Registry

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop here")

    class _FakeClient:
        messages = _FakeMessages()

    def boom():
        raise OSError("HA down")

    p = ClaudeParser(Registry({}), "m", client=_FakeClient(), max_retries=0,
                     context_provider=boom)
    try:
        p.parse("开灯")
    except RuntimeError:
        pass
    assert "当前状态" not in captured["messages"][0]["content"]  # 降级:无上下文照常解析
```

Add to `tests/test_local_parser.py` (reuse its existing `_Resp` fake chain):

```python
def test_local_parser_injects_context():
    from gatekeeper.registry import Registry

    captured = {}

    class _FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            return _Resp({"recognized": False, "confidence": 0.0})

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    p = LocalParser(Registry({}), "gemma4", client=_FakeClient(),
                    context_provider=lambda: "- light.a: on")
    p.parse("有点暗")
    user_msg = captured["messages"][1]["content"]
    assert "- light.a: on" in user_msg
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_parser.py tests/test_local_parser.py -k context -v`
Expected: FAIL (`unexpected keyword argument 'context_provider'`).

- [ ] **Step 3: Implement**

In `gatekeeper/parser.py`: add `import logging` + `logger = logging.getLogger(__name__)` at top (after imports). Change the class to:

```python
    def __init__(self, registry: Registry, model: str, client: Anthropic | None = None,
                 max_retries: int = 2, context_provider=None):
        self.registry = registry
        self.model = model
        self.client = client if client is not None else Anthropic()
        self.max_retries = max_retries
        self.context_provider = context_provider

    def parse(self, instruction: str) -> ParseResult:
        prompt = build_user_prompt(self.registry, instruction, _safe_context(self.context_provider))
        resp = self._create_with_retry(prompt)
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                return ParseResult.model_validate(block.input)
        raise ValueError("模型未返回 emit_parse 工具调用")
```

(`_create_with_retry` 不动。)

Add a module-level helper in `gatekeeper/parser.py`:

```python
def _safe_context(provider) -> str | None:
    """上下文是增强不是依赖:provider 失败 → 记 warning,无上下文继续。"""
    if provider is None:
        return None
    try:
        return provider()
    except Exception:
        logger.warning("context provider 失败,本轮无上下文解析", exc_info=True)
        return None
```

In `gatekeeper/local_parser.py`: add `from .parser import _safe_context` to imports; `__init__` gains `context_provider=None` (stored as `self.context_provider`); in `parse()`, change the user message line to:

```python
                {"role": "user", "content": build_user_prompt(
                    self.registry, instruction, _safe_context(self.context_provider))},
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_parser.py tests/test_local_parser.py -v` → all PASS
Run FULL suite: `.venv/bin/pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/parser.py gatekeeper/local_parser.py tests/test_parser.py tests/test_local_parser.py
git commit -m "feat: parsers accept context_provider (failure degrades to no-context)"
```

---

## Task N5: engine — inferred gate

**Files:**
- Modify: `gatekeeper/engine.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write the failing tests** — add to `tests/test_engine.py` (helpers `_pr`, `_amb_registry`, `FakeParser`, `Engine` all exist):

```python
def test_inferred_always_confirms_with_notes_reason():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on",
                                inferred=True, confidence=0.95,
                                notes="室外偏凉,建议开灯取暖?不,开灯照明")),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点暗")
    assert (d.verdict, d.stage) == ("confirm", "inferred")
    assert "建议" in d.reason


def test_inferred_default_reason_when_notes_empty():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on", inferred=True)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点暗")
    assert d.stage == "inferred" and d.reason  # 兜底话术非空


def test_inferred_params_still_pass_feasibility_first():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="set_temperature",
                                params={"temperature": 26}, inferred=True)),
                 _amb_registry(), tau=0.7)
    d = eng.decide("有点冷")
    assert (d.verdict, d.stage) == ("reject", "feasibility")  # 灯不支持设温度 → 先拒


def test_explicit_command_unaffected():
    eng = Engine(FakeParser(_pr(device_id="light.a", operation="turn_on")), _amb_registry(), tau=0.7)
    assert eng.decide("开灯").stage == "passed"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_engine.py -k inferred -v`
Expected: FAIL (inferred ignored → stage "passed"/"confidence" instead of "inferred").

- [ ] **Step 3: Implement** — in `gatekeeper/engine.py` `decide()`, insert between the `check_feasibility` block and the τ confidence gate:

```python
        if parse.inferred:
            # 推断的意图永远到不了 allow:模型只有提议权,执行权在用户。
            return Decision(verdict="confirm", stage="inferred",
                            reason=parse.notes or "已根据当前状态推断该操作,请确认", **base)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_engine.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/engine.py tests/test_engine.py
git commit -m "feat: inferred gate — proposals always confirm, never allow"
```

---

## Task N6: controller — 💡 prompt

**Files:**
- Modify: `gatekeeper/controller.py` (`_prompt`)
- Test: `tests/test_controller.py`

- [ ] **Step 1: Write the failing test** — add to `tests/test_controller.py`:

```python
def test_inferred_prompt_shows_proposal_and_params():
    d = _decision("confirm", stage="inferred", device_id="climate.ac",
                  operation="set_temperature", params={"temperature": 26},
                  reason="室外 14°C 偏凉,建议把空调调到 26°C")
    out = Controller(FakeEngine(d), StubHA()).handle("有点冷")
    assert out.needs_confirmation is True
    assert out.prompt.startswith("💡 室外 14°C 偏凉")
    assert "set_temperature → climate.ac" in out.prompt
    assert "'temperature': 26" in out.prompt
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_controller.py -k inferred -v`
Expected: FAIL (falls into generic confirm prompt, no 💡).

- [ ] **Step 3: Implement** — in `gatekeeper/controller.py` `_prompt()`, insert BEFORE the final generic return:

```python
        if decision.stage == "inferred":
            return (f"💡 {decision.reason}。确认执行"
                    f"「{decision.operation} → {decision.device_id}」({dict(decision.params)})吗?")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_controller.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add gatekeeper/controller.py tests/test_controller.py
git commit -m "feat: lightbulb prompt for inferred proposals"
```

---

## Task N7: wiring — CLI + Janus providers

**Files:**
- Modify: `gatekeeper/cli.py` (`main()`)
- Modify: `custom_components/janus/__init__.py` (`build_controller`)

No new unit tests (thin wiring; provider/parse behavior covered by N4). Verified by import smoke + full suite + N8.

- [ ] **Step 1: CLI** — in `gatekeeper/cli.py` `main()`, change the parser construction block to:

```python
    from .context import build_context

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
```

- [ ] **Step 2: Janus** — in `custom_components/janus/__init__.py` `build_controller()`, after `reg = ...` add:

```python
    from .gatekeeper.context import build_context

    def context_provider() -> str:
        return build_context(shapes["states"], reg)  # shapes 每轮重建,本就新鲜
```

and pass `context_provider=context_provider` to BOTH parser constructions (LocalParser and ClaudeParser).

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m py_compile gatekeeper/cli.py custom_components/janus/__init__.py && echo OK`
Run: `.venv/bin/python -c "import custom_components.janus, custom_components.janus.bridge; print('ok')"`
Run FULL suite: `.venv/bin/pytest -q` → all green.

- [ ] **Step 4: Commit**

```bash
git add gatekeeper/cli.py custom_components/janus/__init__.py
git commit -m "feat: wire fresh-per-turn context providers into CLI and Janus"
```

---

## Task N8: real-machine check (controller runs this)

**Files:**
- Create: `harness/p4_intent_check.py`

Needs a model (Ollama gemma4 or cloud key). Decide-only asserts — no execution; the full "好→执行"链路 the controller demos via REPL pipe afterwards and restores device state.

- [ ] **Step 1: Write the script**

```python
"""P4 真机验收:模糊舒适度表达 → confirm/inferred + 💡 理由;明确指令零回归。

跑法:NO_PROXY=localhost .venv/bin/python harness/p4_intent_check.py
需要:HA + 一个模型(默认本地 gemma4;GATEKEEPER_BACKEND=claude 走云)。只 decide,不执行。
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
```

- [ ] **Step 2: Run against live HA + model**

Run: `NO_PROXY=localhost,127.0.0.1 .venv/bin/python harness/p4_intent_check.py`
Expected: context printout shows the AC state line and the 室外 weather line; 验收1 OK + 验收2 OK. If 验收1 fails because gemma4 won't emit `inferred=true`, STOP — iterate the SYSTEM_PROMPT rule wording locally (do not weaken the assert), report what the raw parse returned.

- [ ] **Step 3: Full-chain demo via REPL pipe (controller judgment)**

`printf '我感觉有点冷\n好\nexit\n' | NO_PROXY=localhost,127.0.0.1 GATEKEEPER_BACKEND=local .venv/bin/python -m gatekeeper.cli` — expect 💡 prompt then `✅ 已执行`; restore the device state afterwards via HA API.

- [ ] **Step 4: Commit**

```bash
git add harness/p4_intent_check.py
git commit -m "chore: P4 real-machine intent check (inferred proposal + zero regression)"
```

---

## Final: full regression

- [ ] **Step 1:** `.venv/bin/pytest -q` → all pass (163 existing + ~14 new), zero failures.
- [ ] **Step 2:** `git status` → clean tree (vendored janus/gatekeeper stays ignored).
