# Janus C-lite — HA 集成骨架(设计)

- **日期**:2026-06-11
- **状态**:设计已获批,待写实现计划
- **上游**:P3 方向文档 §5.5(产品形态决策);CLI REPL 设计
- **命名已定**:产品/集成名 **Janus**,domain `janus`(撞名已查:HA 无此 domain,仅有陈旧的 `janus_stream` 摄像头组件,不冲突)。核心 Python 包内部仍叫 `gatekeeper`,对外更名留到 B 阶段。

## 1. 目标

把管家从"开发者终端工具"变成"HA 用户的插件":装(custom integration)→ 配(config flow,唯一问题 = LLM 来源)→ 说(HA Assist 聊天/语音,走我们的安全门:放行/确认/问哪一个)。

用户可见验收:在 HA 手机 App/网页的 Assist 聊天框里,「打开空调」直接执行;「关掉卧室的灯」问"哪一个?"、回序号后执行;危险操作要求确认。

## 2. 接入方式(已选 A)

**进程内集成**:`custom_components/janus/` 跑在 HA 进程里。设备数据直接读 hass 内部对象(states + entity/device/area registry helpers),拼成纯逻辑层已经在吃的**同款原始 dict**;执行走 `hass.services.async_call`。`HAClient`(REST/WS)在集成内不出现——它只服务 standalone/CLI 模式。sync 内核不动,异步边界用 HA 官方推荐的 `async_add_executor_job` 包住。

## 3. 组件结构(monorepo 新增目录)

```
custom_components/janus/
  manifest.json        # domain=janus, config_flow=true, requirements=[anthropic, openai, pydantic]
  __init__.py          # async_setup_entry:建注册表→parser→Engine→Controller,挂 hass.data;转发 conversation 平台
  config_flow.py       # 步骤1选 backend(claude/local);步骤2填 key(claude)或 base_url+model(local)
  conversation.py      # ConversationEntity:接 Assist,按 conversation_id 持 Repl
  bridge.py            # 纯形状转换器 + 执行适配器(见 §4/§5)
  gatekeeper/          # 不入库;部署脚本从仓库根整包拷入(内部全相对导入,vendored 可直接用)
harness/deploy_janus.sh  # rsync gatekeeper/ 进组件目录 → docker cp 进 /config/custom_components/ → 重启容器
```

仓库里 `custom_components/janus/` 不含 `gatekeeper/`(部署期注入);`.gitignore` 加 `custom_components/janus/gatekeeper/`。

## 4. bridge.py — 形状转换(纯函数,鸭子类型)

**红线:bridge.py 不 import homeassistant、不 import gatekeeper**——只做"hass 形状对象 → 原始 dict",参数鸭子类型,无 HA 环境即可单测。

- `states_from_hass(states) -> list`:`[{"entity_id": s.entity_id, "attributes": dict(s.attributes)}]`
- `services_from_hass(services_dict) -> list`:`hass.services.async_services()` 的 `{domain: {name: ...}}` → `[{"domain": d, "services": {name: {}}}]`
- `entities_from_registry(entities) -> list`:`[{"entity_id", "device_id", "area_id", "entity_category": (枚举.value 或 None)}]`
- `devices_from_registry(devices) -> list`:`[{"id", "area_id", "identifiers": [[domain, value]…], "config_entries": [..], "name"}]`(set/tuple → list)
- `areas_from_registry(areas) -> list`:`[{"area_id": a.id, "name": a.name}]`
- `config_from_hass(temperature_unit) -> dict`:`{"unit_system": {"temperature": unit}}`

输出直接喂现有 `build_registry_snapshot` / `map_ha` / `Registry.from_ha`(零改动)。

**执行适配器** `HassServiceCaller`:实现 Controller 期望的 `call_service(domain, service, entity_id, params)` 同步签名;内部 `asyncio.run_coroutine_threadsafe(hass.services.async_call(domain, service, {"entity_id": …, **params}, blocking=True), loop).result(timeout)`。只会从 executor 线程被调(repl.feed 整体跑在 executor),不会在事件循环线程里 `.result()` 死锁。

## 5. 装配(`__init__.py`)

`async_setup_entry`:
1. 事件循环内读 hass 各注册表 → bridge 转换 → `build_registry_snapshot(..., config=...)` → `Registry.from_ha(states, services, snapshot=snap)`(自动策展,纯函数,快,可直接内联);
2. 按 `entry.data["backend"]` 建 parser:`claude` → `ClaudeParser(reg, MODEL, client=Anthropic(api_key=entry.data["api_key"]))`(key 显式注入,不读环境);`local` → `LocalParser(reg, entry.data["model"], base_url=entry.data["base_url"])`;
3. `Engine(parser, reg, TAU)` → `Controller(engine, HassServiceCaller(hass))` → 存 `hass.data["janus"][entry_id]`;
4. `async_forward_entry_setups(entry, ["conversation"])`。

注册表快照在 setup 时构建一次;设备增删后用 HA 的"重新加载集成"刷新(实时订阅范围外)。

## 6. 对话(`conversation.py`)

`JanusConversationEntity(ConversationEntity)`:
- `supported_languages = MATCH_ALL`;
- 持 `self._repls: dict[conversation_id, Repl]`——**原样复用 CLI 的 `Repl`**(string-in/string-out 纯逻辑,歧义/确认链白拿);conversation_id 缺省时用固定键;
- `async_process(user_input)`:`reply = await hass.async_add_executor_job(repl.feed, user_input.text)`(LLM 调用 + 执行都在 executor 线程);回复空串时给固定话术("请说出要执行的指令");包装成 `ConversationResult(IntentResponse(speech=reply))`。

非控制类输入(查询/闲聊)由四关自然 reject,回复即 reject 话术——智能查询回答在范围外。

## 7. config flow

- step `user`:单选 backend ∈ {claude(云端), local(本地 Ollama)};
- step `claude`:必填 `api_key`(仅非空校验,连通性校验范围外);
- step `local`:`base_url`(默认 `http://host.docker.internal:11434/v1`,容器访问宿主;colima 下可能需 `host.lima.internal`,真机验收时确认并把实测值写回文档)、`model`(默认 `gemma4`);
- 产出 entry.data:`{"backend", "api_key"?, "base_url"?, "model"?}`;τ 固定 0.7(options flow 范围外)。

## 8. 错误处理

- setup 阶段无外部连接(注册表读取与 parser 构造都不联网),异常即配置/代码错误,交 HA 默认错误展示;`ConfigEntryNotReady` 不适用(没有可重试的外部依赖);
- 对话阶段 parser/执行异常已被引擎/Controller fail-closed 兜底(reject/error 话术),Repl 不抛;
- 执行适配器超时(`result(timeout=10)`)→ 异常冒给 Controller `_execute` 的 try/except → `❌ 失败:…`。

## 9. 测试(两层)

- **纯单元**(无 HA 依赖):bridge 六个转换器(含 entity_category 枚举→str、identifiers set→list、空值容错)喂假对象;转换器输出直接过 `build_registry_snapshot`+`Registry.from_ha` 的组合测试(拼最小 hass 形状 → 验证 curated 目录正确)。
- **真机验收**(本机 HA 2026.6.0,Docker volume `ha_config`):`deploy_janus.sh` 部署 → HA UI 添加 Janus(local backend)→ Assist 聊天框跑通:①「打开空调」执行;②「关掉卧室的灯」→"哪一个?"→ 回"2"→ 执行;③ 危险操作 → 确认 → y 执行。这次**真执行**(目录已是纯真设备,4 个)。
- 现有 pytest 全套零回归(集成代码不进 `gatekeeper` 包,互不影响)。

## 10. 范围外

HACS 商店上架与 brands 资源、options flow(τ/模型热调)、注册表实时刷新、查询类智能回答、多语言文案、核心包改名 janus、pytest-homeassistant 集成测试框架。
