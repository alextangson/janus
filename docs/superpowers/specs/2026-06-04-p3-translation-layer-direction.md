# P3 — 设备"翻译层" 方向文档(DIRECTION,非最终 spec)

- **日期**:2026-06-04
- **状态**:方向已定、地基决策已定;**待在全新会话里完成 brainstorm → spec → plan → 实现**
- **怎么接手**:开一个干净的新会话 → 读本文 + `docs/superpowers/specs/` 下 P2.1 设计 + `gatekeeper/ha_mapping.py` → 跑 `/superpowers:brainstorming` 把 **P3.1(注册表升级)** 先定稿,再依次往下。

---

## 0. 当前项目状态(给冷启动的上下文)

- 已建成并**在真 Home Assistant 上端到端验证**:决策内核(解析→四关→放行/确认/拒绝,云端+本地小模型双验证)、`Registry.from_ha`(REST 拉设备 + 危险标注 + 能力位门控)、执行(`ha_client.call_service`)、confirm 闭环(`Controller`)。全在 `main`,~87 测试绿。
- **真机环境(开发/验证 P3 用)**:HA 在这台 MacBook 的 Docker(colima)里跑,`http://localhost:8123`,已接入用户真实小米设备(353 实体)。`.env` 里有 `GATEKEEPER_HA_TOKEN`、`GATEKEEPER_HA_URL`、`ANTHROPIC_API_KEY`。连真 HA 的运行方式见仓库里历史命令(`HAClient(...).fetch()` + 局域网 URL + `NO_PROXY=localhost`)。
- 万星路线里 P3 的定位:**A. 能用**的硬门槛(另有 B. 公开 benchmark+README、C. HACS 打包+config UI、D. 广度、E. 社区)。

## 1. P3 为什么必须做(真实数据暴露的问题)

接入真小米后:353 实体 → `from_ha` 映射出 78 个"可控设备",但**绝大多数是噪声**——子功能开关(摄像机"时间水印"、门铃"ECO模式"、音箱"睡眠模式"、电蚊香、各种"指示灯/推送/侦测")+ 大量同硬件 id 的 `_2` 重复(同一设备挂在多个米家"家庭"被导入两次)。

后果实测:对真机说 **"打开空调""关灯"→ 全部 `reject`(置信度 0.2)**。模型在噪声+重名里**不敢动**(安全的失败,但不可用)。
**结论:可靠大脑没问题,缺的是大脑与乱糟糟真实实体之间的"翻译层"。**

## 2. 拆解(6 块,相关但可分;建议各自 spec→plan→实现)

| 块 | 做什么 | 依赖 |
|---|---|---|
| **P3.1 注册表升级** | 用 WebSocket 拉 entity registry(`entity_category`)、device registry(分组)、area registry | WebSocket |
| **P3.2 策展去噪** | 只留主控件,滤掉 config/diagnostic 子设置 | entity_category |
| **P3.3 去重** | 同 device 的 `_2` 合并成一台 | device 分组 |
| **P3.4 命名/别名** | "空调插座 空调"→"客厅空调" | area+device + 用户覆盖 |
| **P3.5 作用域** | 锁定到一个"家",避免多家歧义 | area / 米家 home |
| **P3.6 消歧** | 多候选 → 确认("哪台?")而非 reject | 决策层 |

## 3. 地基决策(已定)

**升级到 WebSocket 注册表。** 因为干净的策展信号 `entity_category` 在 REST `/api/states` 里**完全拿不到**(已实测:353 个全是 `None`)。WebSocket 注册表一举给到 `entity_category`(策展)+ device 分组(去重)+ area(作用域),撑起 6 块里的 3 块。代价:新增 WebSocket 客户端、异步、注册表协议——**P3 的工程大头在 P3.1**。

架构倾向:**REST + WebSocket 混合**——保留现有 `ha_client` 的 REST(states/services 仍好用),新增一个 WS 注册表抓取(一次性快照即可,实时订阅留后)。`ha_mapping` 从"只吃 states/services"升级为"再吃 registry 元数据"。

## 4. 待定设计点(新会话里逐一定夺)

- **P3.1**:WS 客户端选型(`websockets` 库 / `aiohttp` ws);HA WS 鉴权流程(`auth` 消息带 token);要拉哪些 registry(`config/entity_registry/list`、`config/device_registry/list`、`config/area_registry/list`);一次性快照 vs 订阅。
- **P3.2 策展规则**:保留 `entity_category is None`(主控件)、滤掉 `config`/`diagnostic`?是否再叠加域白名单?**拿真机数据验证**哪些噪声实体确实是 config/diagnostic(本次没验到这一步)。
- **P3.3 去重**:按 device registry id 分组;同一物理设备多实体如何选"代表";同设备挂多家如何处理。
- **P3.4 命名**:自动名(area + device 名)规则 + 用户别名文件(如 `aliases.json`:entity_id/device → 别名)。
- **P3.5 作用域**:HA area 与"米家家庭"的对应关系;配置"当前家/区域";多家 = 多实例还是单实例+选择器。
- **P3.6 消歧**:改决策流——解析返回多候选时,engine 出 `confirm("哪一个?", 候选列表)` 而非 reject。触及 parser 契约(是否返回候选集)+ engine + Controller 的话术。这是决策层的真改动,需单独想清。

## 5. 建议实现顺序

P3.1(注册表升级)先行 → P3.2 策展 + P3.3 去重(一起,都吃 registry)→ P3.4 别名 → P3.5 作用域 → P3.6 消歧(决策层)。每块完成都用**真机**(本台 MacBook 的 HA)验证"78 噪声 → 干净设备清单"、以及"打开空调"从 reject 变 allow/confirm。

## 5.5 产品形态决策(2026-06-10 拍板,约束 P3 全线)

- **入口**:不做自有 App/聊天界面。最终以 **HA conversation agent** 接入 Assist(聊天/语音),产品定位 = "给任何 LLM 套上安全门的对话代理"。
- **打包**:**HACS custom integration**(非 add-on)。跑在 HA 内 → token 摩擦消失,配置走 config flow UI;唯一必要配置是 LLM 来源(云 key / 本地 Ollama)。现在不实现,但 P3 设计不得与之冲突;`HAClient` 终将被 hass 内部 API 替代,**不在其上过度投资**,纯逻辑继续沉淀在 `ha_mapping`/`engine`。
- **红线:零配置默认可用**。P3.2 策展、P3.3 去重、P3.4 命名必须全自动;`ha_overrides.json`/`aliases.json` 之类只能是高级覆盖,不是使用前提。
- **顺序**:P3.2+3.3 → P3.4 → 极薄 CLI REPL(自测/演示)→ C-lite(integration 骨架 + config flow + conversation agent)→ B(用户向 README + benchmark)。
- **真机已证**(P3.1):`entity_category` 只标了 78 个可控设备中的 4 个(indicator light)——策展不能依赖它,噪声大头是 `_2` 同硬件重复,**P3.3 去重是主菜**,P3.2 规则须先用真机数据重测。
- **不做品牌集成**。大牌家电软件烂、无中控(松下冰箱靠小程序/纯蓝牙)是真痛点,但接入是 HA 社区 2800+ 集成 + Matter + BLE proxy 的活;我们的价值 = 生态之上的安全对话中控层,设备越碎我们越值钱。路线图 D(广度)按"骑生态"理解,不是自写集成。

## 6. 成功标准(P3 整体)

- `from_ha`(升级后)在真机上把 78 噪声实体收敛成**几十个有意义的设备**(去噪+去重);
- 给空调/灯等起别名后,**"打开空调""关客厅灯"从 reject 变成正确的 allow/confirm**;
- 多台同名/多家场景下,**触发确认而非误选/拒绝**;
- 现有全套测试零回归;新逻辑有真机+stub 双层测试。
