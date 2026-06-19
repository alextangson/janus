# Changelog

## 0.1.0

- 首版:Janus 无头服务 + janus-app 打成单一 HAOS 加载项。
- app 经 ingress 嵌进 HA 界面;HA 连接走 supervisor token(免长期令牌);零粘贴。
- 安全:内部 bearer token(随机/持久/不回显)+ ingress 模式 supervisor 源 IP 闸。
- LLM 后端可配:本地 Ollama 加载项 或 云端 Anthropic。
