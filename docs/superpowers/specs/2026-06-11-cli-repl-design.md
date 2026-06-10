# CLI REPL — 第一个对话表面(设计)

- **日期**:2026-06-11
- **状态**:设计已获批,待写实现计划
- **上游**:P3 方向文档 §5.5(CTO 排序:P3.6 之后 → 薄 CLI REPL → C-lite)
- **定位**:自测 + 演示表面,不是最终产品入口(那是 HA Assist conversation agent)。但随包分发:`python -m gatekeeper.cli`。

## 1. 目标

把 `Controller.handle → confirm/choose` 闭环包成能在终端对话的 REPL,第一次可以"真的和管家说话"。百行量级,零新依赖。

## 2. 组件

### `gatekeeper/cli.py`

**`Repl` 类(纯逻辑,无 IO,可单测)**:
- 状态:`controller` + `pending: Outcome | None`(等待中的确认/选择;Controller 本身保持无状态)
- 唯一公开方法 `feed(line: str) -> str`:
  1. `pending` 存在且 `pending.choices` 非空(歧义选择):
     - 输入为 1..n 的序号 → `controller.choose(pending.decision, choices[i-1])`
     - `取消`/`n`/`否` → 放弃,清 pending,回"已取消"
     - 其他输入 → 重示原 prompt(pending 保留)
  2. `pending` 存在、无 choices(是/否确认):
     - `y`/`是`/`yes` → `controller.confirm(pending.decision, approved=True)`
     - `n`/`否`/`no`/`取消` → `confirm(..., approved=False)`,回"已取消"
     - 其他输入 → 重示原 prompt
  3. 无 pending:空行 → 空串;否则 `controller.handle(line)`
  - **Outcome 渲染**(三处共用):`executed` → `✅ 已执行:<device_id>.<operation>`;`error` 非空 → `❌ 失败:<error>`;`needs_confirmation` → 存/更新 pending,返回 `outcome.prompt`;其余(reject/否决)→ `🚫 <decision.reason 或 "已取消">`
  - **链式**:`choose` 的结果若仍 `needs_confirmation`(选中危险操作)→ pending 更新为新 Outcome,继续问——天然支持 歧义→选择→危险确认→执行 全链。

**`main()`(薄 IO 壳,不单测)**:
1. `config.load_env()` 读 `.env`
2. `HAClient` 拉 states/services + `fetch_registries()` + `fetch_config()` → snapshot → `Registry.from_ha`(curated)
3. 按 `config.BACKEND` 建 parser:`claude` → `ClaudeParser(reg, MODEL)`;`local` → `LocalParser(reg, LOCAL_MODEL)`
4. `Engine(parser, reg, TAU)` → `Controller(engine, client)` → `Repl`
5. 横幅:设备数、backend/model、温度单位;`> ` 循环 `input()` → `print(repl.feed(line))`;`exit`/`quit`/`q`/EOF(Ctrl-D)退出

### `gatekeeper/config.py`

新增 `load_env() -> None`:读仓库根 `.env`,`os.environ.setdefault` 逐行注入(跳过注释/空行);文件不存在则静默返回(变量可能已由 shell 提供)。**除重**:`harness/p3_ws_snapshot.py` 与 `harness/p36_e2e_check.py` 的同款 `_load_env` 改为调用它。
取值约定(与 harness 现状一致):config.py 的模块级常量在 import 时已从 shell 环境固化,`.env` 注入发生在之后——所以 **HA URL/TOKEN(来自 `.env`)由 `main()` 在 `load_env()` 之后直接读 `os.environ`**;BACKEND/MODEL/TAU 来自 shell 环境变量,直接用 config 常量即可。

## 3. 运行方式

```
# 本地模型(当前推荐,云 key 失效中)
NO_PROXY=localhost GATEKEEPER_BACKEND=local python -m gatekeeper.cli
# 云端
NO_PROXY=localhost python -m gatekeeper.cli
```

## 4. 错误处理

- 执行失败 → `❌ 失败:<error>`(Controller 已兜底,不崩);
- parser/HA 异常在 `handle` 内已 fail-closed(reject/error);
- REPL 自身对任意输入不抛异常:非法序号/无法理解的确认词 → 重示 prompt。

## 5. 测试

- **纯单元**(`tests/test_cli.py`,复用 FakeEngine/StubHA 模式 + FakeResolveEngine 式假引擎):
  allow 直接执行;reject 显示原因;歧义 → 返回带序号 prompt → feed("2") 选中并执行;非法序号 → 重示且 pending 保留;`取消` 清 pending;是/否确认 y 执行、n 取消;歧义选择 → 危险 → 链式确认 y → 执行;执行失败渲染 ❌。
- **真机演示**(controller 执行):脚本化 stdin 跑一遍 `关掉卧室的灯` → 出"哪一个?" → `取消`;`开锁`类危险确认 → `n`——只验证对话链路,**不真动设备**;真执行体验留给用户。

## 6. 范围外

会话历史/多轮上下文、别名、彩色输出/TUI、HA Assist 接入(C-lite)。
