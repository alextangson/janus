# Janus 加载项 — 文档

## 它怎么工作

- **一个容器**跑 Janus FastAPI 服务,服务端同时静态托管 janus-app 并暴露 `/v1` API。
- **ingress**:HA 已鉴权的用户经 ingress 访问加载项;服务端把真 API token + 真 ingress 根
  注入页面(`window.__JANUS__`),app 据此免粘贴直连。`/v1` **仍要 bearer 鉴权**(ingress 不旁路)。
- **源 IP 闸**:ingress 模式下服务只接受来自 supervisor 内网 IP(`172.30.32.2`)的请求,挡同内网
  其他加载项直连 `:8088` 偷 token/调 API。
- **HA 连接**:`homeassistant_api: true` 让加载项经 `http://supervisor/core` + `$SUPERVISOR_TOKEN`
  访问 Core API —— 用户**无需创建长期访问令牌**。

## 权限与威胁模型(请知悉)

- `homeassistant_api: true` 授予本加载项经 supervisor 凭证的**完整 Home Assistant Core API 访问**
  (HA 加载项不提供更细粒度的 Core scope)。这是 Janus 读取设备注册表、读状态、调用服务以控家的前提。
  含义:本加载项能看到并控制你 HA 里所有可控实体。Janus 的安全闸(危险操作确认 + 可选 PIN)
  在此之上限制 LLM 的越权,但加载项进程本身具备全 Core 权限。仅安装你信任的来源。
- 内部 API token 随机生成、持久于 `/data/janus_api_token`(`chmod 600`)、不回显日志、不对用户展示。
- 不发布任何主机端口;仅经 ingress 暴露。

## 数据

加载项的 `/data/`(HA 持久卷)存:`janus_api_token`、`janus_audit.db`(决策审计)、
`schedules.json`/`scheduler.lock`(定时)、`janus_security.json`(PIN 哈希)。卸载加载项即清除。

## 端到端验收(需 HAOS,本机无法替跑)

- [ ] 加载项安装并启动,日志无报错(`backend=... ingress=on`)
- [ ] 侧栏出现 **Janus** 面板,点开**直接是四标签**(无连接页、无需填地址/token)
- [ ] 「设备」标签能看到 HA 里接入的设备(证明 supervisor REST + **WS 注册表拉取**通)
- [ ] 「对话」说"把客厅灯打开"(换成你的设备名),灯响应
- [ ] 危险操作(开锁/开门)走确认;若配了 `dangerous_pin`,确认需带 PIN
- [ ] 隔离:从另一加载项/局域网直连 `http://<本加载项>:8088/` 应被拒(403 或不可达)

## 已知风险点(待真机验证)

- supervisor 对 **WebSocket**(`ws://supervisor/core/api/websocket`,注册表拉取依赖)的代理与
  token 鉴权需在 HAOS 上确认通(REST 路径较有把握,WS 是风险点)。
- s6-overlay v3 服务接线(`/etc/s6-overlay/s6-rc.d/janus`)与 HA base image 版本相关,
  首次安装需看日志确认服务被拉起。
