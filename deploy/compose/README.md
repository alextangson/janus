# 一条命令起整套栈(Janus 一体机·软件内核)

`docker compose` 拉起完整软件内核:**Home Assistant + Ollama(本地小模型) + Janus 无头服务 + janus-app(web)**。本地优先,无云 LLM 看家里指令。这是一体机的软件内核;镜像/硬件是其上的打包(后续)。

> **诚实边界**:一体机能消灭"装/配 Janus、LLM、服务"的摩擦(可做到零),但 **HA 首次设置躲不掉**——你必须告诉 HA 家里有哪些设备(建账号 + 装设备集成),并在 HA 里建一个长期访问令牌给 Janus。第一次 `docker compose up` **无法**替你完成这一步。下方流程把它包成"首次设置",而不是假装它不存在。

## 前置

- Docker + Docker Compose
- Node + npm(仅用于本地构建 janus-app 的前端产物)
- `janus-app` 源码(私有仓)在本地。默认找 `../janus-app`(相对仓库根);否则设 `JANUS_APP_DIR` 指向你的副本。

## 起栈(两阶段)

### 阶段一:拉起栈

```bash
cd deploy/compose
cp .env.example .env          # 先留空 GATEKEEPER_HA_TOKEN
./up.sh                       # = 构建 app dist + docker compose up --build
```

`up.sh` 会:① 从 `../janus-app` 构建前端 dist;② 拉起全部服务。首次会拉 HA / Ollama 镜像并 `ollama pull qwen2.5:3b`(约 2GB),耐心等。

此时:
- `http://localhost:8123` —— Home Assistant
- `http://localhost:8080` —— Janus app
- `http://localhost:8088` —— Janus 服务(**暂未启动**:缺 HA token,见下)

Janus 服务会打印一段引导后**干净退出**(不刷屏)——这是预期的,等你做完阶段二。

### 阶段二:HA 首次设置 + 接上 Janus

1. 浏览器开 `http://localhost:8123`,完成 HA 首次设置:**建账号**,然后 **为你的设备添加集成**(Settings → Devices & Services → Add Integration)。Janus 只能看见 HA 已接入的设备。
2. 建长期访问令牌:HA → 右下角头像 → **安全 / Security** → **长期访问令牌 / Long-Lived Access Tokens** → 创建,复制。
3. 把令牌填进 `deploy/compose/.env`:
   ```
   GATEKEEPER_HA_TOKEN=粘贴你的令牌
   ```
4. 重启 Janus 服务:
   ```bash
   docker compose up -d janus
   ```
5. 拿 Janus API token:服务首启时打印过(见 `docker compose logs janus`),或读 `./data/janus/janus_api_token`。
6. 开 app `http://localhost:8080`:**API 地址**填 `http://localhost:8088`,**token** 粘贴上一步的 Janus API token。连上即用。

## 配置(`.env`)

| 变量 | 默认 | 说明 |
|---|---|---|
| `GATEKEEPER_HA_TOKEN` | (空) | HA 长期访问令牌。空 → Janus 打印引导并退出。 |
| `JANUS_LOCAL_MODEL` | `qwen2.5:3b` | Ollama 模型。**必须支持工具调用**(qwen2.5 家族验证可用)。求质量可换 `qwen2.5:7b`。 |
| `JANUS_DANGEROUS_PIN` | (空) | 可选。设了之后,开锁/开门等危险操作的确认需带此 PIN。 |

## 数据与持久化

全部落在 `deploy/compose/data/`(gitignored):

- `data/ha/` —— HA 配置 + 数据库
- `data/ollama/` —— 已拉取的模型
- `data/janus/` —— Janus API token、审计库、定时任务

删 `data/` = 全新开始(含 HA 账号)。

## 常见问题

- **Janus 一直退出/重启?** 多半是 `GATEKEEPER_HA_TOKEN` 没填或填错。看 `docker compose logs janus`。
- **app 连不上?** 确认 API 地址是 `http://localhost:8088`(浏览器侧),且 token 是 Janus API token(不是 HA 令牌)。
- **设备列表空?** 设备来自 HA。先在 HA(`:8123`)里把设备接好,这里会自动出现。
- **想换模型?** 改 `.env` 的 `JANUS_LOCAL_MODEL`,`docker compose up -d ollama-pull janus`。注意必须是支持工具调用的模型。
- **janus-app 不在 `../janus-app`?** 设 `JANUS_APP_DIR=/你的/路径 ./up.sh`。

## 安全提示

- Janus 服务发布在 `0.0.0.0:8088`(同局域网可达)。CORS 默认只放 `localhost:8080`。API token 即访问凭据,妥善保管。
- 仅在可信局域网内使用;暴露到公网需自行加反代 + TLS + 收紧。

## 端到端验收(人工)

栈本身的构建/起停已自动化验证;下面这条链路需要你交互完成(HA onboarding 无法替跑):

- [ ] `./up.sh` 后 `:8123` `:8080` 可达,`docker compose logs janus` 打印了 token + HA 引导并干净退出
- [ ] HA 建账号 + 接入至少一个真实设备(如一盏灯)
- [ ] 建 HA 长期令牌填入 `.env`,`docker compose up -d janus` 后服务常驻(`docker compose ps` 中 janus 为 up)
- [ ] app(`:8080`)填 `http://localhost:8088` + Janus token,连接成功
- [ ] 设备标签里能看到 HA 接入的设备
- [ ] 对话里说"把客厅灯打开"(换成你的设备名),灯实际响应,危险操作(开锁/开门)走确认
