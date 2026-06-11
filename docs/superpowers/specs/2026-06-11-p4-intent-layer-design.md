# P4.1+P4.2 — 意图层:上下文注入 + 推断意图(设计)

- **日期**:2026-06-11
- **状态**:设计已获批,待写实现计划
- **上游**:方向文档 §5.6(P4 章程)。核心原则:**模型提议,关卡把关,推断默认 confirm**。
- **真机事实(塑造边界)**:本家无室温信号(无温度传感器,空调 `current_temperature=None`);有天气实体(`weather.forecast_jia`,室外温/天况/湿度);设备运行状态在已抓取的 states 里,零新增 IO。⇒ 上下文**按家庭优雅降级**:有什么注什么,缺的绝不编造。

## 1. 目标

「我感觉有点冷」从 `🚫 缺少必填参数` 变成:

> 💡 室外 14°C 偏凉,建议把空调调到 26°C 制热。确认执行「set_temperature → climate.…」({'temperature': 26})吗?

回"好"才执行。明确指令(「打开空调」)行为零变化。

## 2. 上下文注入(P4.1)

### `gatekeeper/context.py`(新,纯函数)

`build_context(states: list, registry: Registry) -> str`,渲染"当前状态"块:

- **设备状态行**:只渲染 curated 目录内的设备(`registry.device_ids()`,排序)。每行:
  `- {device_id}: {state}`;climate 追加 `,目标 {temperature}°;室温 {current_temperature}°`(`current_temperature` 为 None 则省略室温段)。
- **环境行**:遍历原始 states 里的 `weather.*`:`- 室外({entity_id}): {state},{temperature}{temperature_unit},湿度 {humidity}%`;
  `sensor.*` 中 `device_class∈{temperature, humidity}` 的逐行渲染(本家现为 0 个,留好通道)。
- **降级**:无天气/传感器则省略对应行;状态块整体永远存在(设备总在)。畸形条目跳过不崩(同 ha_mapping 姿态)。

### 管道:`context_provider` 可调用

- `build_user_prompt(registry, instruction, context: str | None = None)`:context 非空时,在设备清单与用户指令之间插入"当前状态(供推断参考):\n{context}"。
- `ClaudeParser` / `LocalParser` 构造器新增 `context_provider: Callable[[], str] | None = None`;`parse()` 内调用 provider 取 context。**provider 抛异常 → 记 warning、当作无上下文继续**(上下文是增强,不是依赖;指令解析不因状态拉取失败而死)。
- **接线**:CLI `main()` → `context_provider=lambda: build_context(client.fetch()[0], reg)`(每轮重拉,保证新鲜);Janus `build_controller` → `lambda: build_context(shapes["states"], reg)`(shapes 本就每轮重建)。Engine/Registry/Controller 零改动。

## 3. 推断意图(P4.2)

### 契约(`models.py`)

- `ParseResult.inferred: bool = False`——**显式字段,不赌模型置信度校准**。
- `Stage` 新增 `"inferred"`。

### 提示词(`prompts.py`)

SYSTEM_PROMPT 新规则:"若指令是模糊的舒适度/感受表达(冷、热、闷、暗等)而非明确命令:照常填 device_id/operation/params(结合当前状态推断合理参数),令 `inferred=true`,并在 notes 用一句中文说明推断理由(如『室外 14°C 偏凉,建议调高空调』)。明确指令时 inferred 必须为 false。"

### 引擎关卡(`engine.py`)

`decide()` 在 feasibility 之后、τ 之前:

```
if parse.inferred:
    return Decision(verdict="confirm", stage="inferred",
                    reason=parse.notes or "已根据环境推断,请确认", **base)
```

- **推断永远到不了 allow**(红线);τ 关卡保留兜底(模型忘标 inferred 时,模糊输入的低置信仍会拦)。
- 推断 + 危险操作:同一次 confirm 即为用户对该具体操作的明确授权,不再二次确认。
- 推断 + 多候选:歧义关卡在前(先问哪一个);`choose` 后走 `decide_resolved`(用户已点名设备并见过提议,不再重复 💡 confirm)。

### 话术(`controller.py`)

`_prompt` 新分支:`stage == "inferred"` →
`💡 {reason}。确认执行「{operation} → {device_id}」({params})吗?`

## 4. 错误处理

- context provider 失败 → warning + 无上下文解析(见 §2);
- 推断出的参数仍过 feasibility(范围/类型校验在 inferred 关卡之前,越界推断照样拒);
- 模型在明确指令上误标 inferred=true → 多一次 confirm,烦但安全(宁多问,不误执行)。

## 5. 测试(两层)

- **纯单元**:`build_context`(climate 目标/室温渲染与 None 降级、weather 行、sensor 行、畸形跳过、只含 curated 设备);`build_user_prompt` 插入位置;parser 注入 fake provider(含 provider 抛异常→照常解析);引擎 inferred 关卡(confirm/inferred、reason 取 notes、feasibility 先行拦越界推断、τ 兜底不受影响);话术 💡 分支。
- **真机验收**(需起一个模型,云/本地皆可):①「我感觉有点冷」→ confirm/inferred,话术含 💡 与理由 → 回"好"→ 真执行(完毕恢复);②「打开空调」→ allow 零回归;③ harness 打印实际注入的 context 供人工核验(含室外温度、空调状态)。

## 6. 范围外

缺参数反问"开到几度?"(P4.2b)、主动建议/事件驱动(P4.3)、float 温度参数与英制无损(P4.0 余项)、室温传感器接入建议(用户硬件问题)。
