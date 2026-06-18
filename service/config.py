from __future__ import annotations

import os

from gatekeeper.config import load_env

load_env()  # 复用仓库根 .env(HA url/token、ANTHROPIC_API_KEY、BACKEND 等仍由 gatekeeper.config 提供)

API_TOKEN = os.environ.get("JANUS_API_TOKEN", "")
# 危险操作第二因子 PIN(可选)。设置后,危险操作的 confirm 必须带正确 PIN;空=关闭(token 单因子)。
DANGEROUS_PIN = os.environ.get("JANUS_DANGEROUS_PIN", "")
HOST = os.environ.get("JANUS_HOST", "127.0.0.1")
PORT = int(os.environ.get("JANUS_PORT", "8088"))

PENDING_TTL_S = float(os.environ.get("JANUS_PENDING_TTL_S", "120"))
REQUEST_TIMEOUT_S = float(os.environ.get("JANUS_REQUEST_TIMEOUT_S", "30"))
IDEMPOTENCY_TTL_S = float(os.environ.get("JANUS_IDEMPOTENCY_TTL_S", "300"))
MAX_CONCURRENCY = int(os.environ.get("JANUS_MAX_CONCURRENCY", "8"))
MAX_SESSIONS = int(os.environ.get("JANUS_MAX_SESSIONS", "1000"))
MAX_BODY_BYTES = int(os.environ.get("JANUS_MAX_BODY_BYTES", "16384"))
AUDIT_DB = os.environ.get("JANUS_AUDIT_DB", "data/janus_audit.db")

# 浏览器跨域:逗号分隔的允许源;默认 "*"(bearer API 安全)。收紧示例:
# JANUS_CORS_ORIGINS="http://localhost:5180,http://192.168.3.89:5180"
CORS_ORIGINS = [o.strip() for o in os.environ.get("JANUS_CORS_ORIGINS", "*").split(",") if o.strip()]
