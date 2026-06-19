# Janus — Home Assistant 加载项

把 Janus(LLM↔HA 安全闸)+ 它的 app 打成**一个 HAOS 加载项**:装进任何 Home Assistant OS,
一键即用。app 经 **ingress** 嵌进 HA 界面;HA 连接走 **supervisor**(免建长期令牌);**零粘贴**。

> 这是第二增量。第一增量是 `deploy/compose/` 的整套 docker compose 栈(自带 HA)。
> 本加载项面向**已经在跑 Home Assistant OS** 的用户。

## 本地开发/安装(当前形态)

加载项尚未发布为独立仓库,先以 HAOS **本地加载项**方式开发:

1. 构建 app dist 并烤入:
   ```bash
   cd deploy/addon/janus && ./build-addon-app.sh
   ```
   (从本地私有仓 `../janus-app` 跑 `npm run build:ingress`,产物拷进 `app/`。)
2. 把整个 `deploy/addon/janus/` 目录放进你 HAOS 的 `/addons/janus/`(通过 Samba/SSH 加载项)。
3. HA → Settings → Add-ons → Add-on Store → 右上角 ⋮ → **Check for updates**;
   "Local add-ons" 下出现 **Janus** → Install。
4. 在加载项配置页选 LLM 后端(见下),Start;侧栏出现 **Janus** 面板,点开即用。

> 发布为"一键加 URL 安装"的独立 add-on 仓库(repository.yaml at root)/ HACS 上架是后续步骤。

## 配置(加载项选项)

| 选项 | 默认 | 说明 |
|---|---|---|
| `backend` | `local` | `local`(Ollama)或 `claude`(云端)。 |
| `local_base_url` | (空) | local 后端必填:指向你的 **Ollama 加载项**,如 `http://<ollama-addon-slug>:11434/v1`。 |
| `local_model` | `qwen2.5:3b` | 必须支持工具调用(qwen2.5 家族验证可用)。 |
| `tau` | `0.7` | 置信度阈值。 |
| `anthropic_api_key` | (空) | `claude` 后端填。 |
| `dangerous_pin` | (空) | 设了则开锁/开门等危险操作的确认需带此 PIN。 |

本地模型:本加载项**不自带 Ollama**(单职责)。请另装一个 Ollama 加载项并把 `local_base_url`
指向它;或用 `claude` 后端 + `anthropic_api_key`。

详见 [DOCS.md](DOCS.md)(含权限/威胁模型、端到端验收清单)。
