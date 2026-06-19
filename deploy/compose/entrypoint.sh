#!/usr/bin/env bash
# Janus 服务入口:① JANUS_API_TOKEN 自配 ② HA-token 闸(诚实边界) ③ HA 就绪等待 → 起服务。
set -euo pipefail
cd /app

DATA_DIR=/app/data
TOKEN_FILE="$DATA_DIR/janus_api_token"
mkdir -p "$DATA_DIR"

# ── ① JANUS_API_TOKEN 自配(持久化,重启稳定)──────────────────────────────
if [ -z "${JANUS_API_TOKEN:-}" ]; then
  if [ -f "$TOKEN_FILE" ]; then
    JANUS_API_TOKEN="$(cat "$TOKEN_FILE")"
    echo "[janus] 复用已保存的 API token($TOKEN_FILE)"
  else
    JANUS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    printf '%s' "$JANUS_API_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    cat <<EOF

============================================================
[janus] 已生成 API token / API token generated:

    $JANUS_API_TOKEN

  打开 app / open the app:   http://localhost:8080
  API 地址 / API address:    http://localhost:8088
  粘贴上面的 token 登录。Paste the token above to connect.
  (此 token 等同 app 访问权,妥善保管;已存于 $TOKEN_FILE)
============================================================

EOF
  fi
  export JANUS_API_TOKEN
fi

# ── ② HA-token 闸 ────────────────────────────────────────────────────────
# HA 的 Long-Lived Token 只能在 onboarding(建账号)之后人工创建,无法首启自动生成。
# 缺 token 时打印引导并 exit 0:restart:on-failure 不重启 exit 0,故无 crash-loop 刷屏。
if [ -z "${GATEKEEPER_HA_TOKEN:-}" ]; then
  cat <<'EOF'

============================================================
[janus] 等待 Home Assistant 设置 / waiting for HA setup

  Janus 还不能连 Home Assistant —— 缺 GATEKEEPER_HA_TOKEN。
  Janus can't reach Home Assistant yet (no HA token).

  请按以下步骤 / Please:
   1. 打开 http://localhost:8123 完成 HA 首次设置
      (建账号 + 为你的设备添加集成)。
      Open :8123, create your account, add device integrations.
   2. HA → 头像 → 安全 → 长期访问令牌 → 创建。
      HA → profile → Security → Long-Lived Access Tokens → Create.
   3. 把令牌填进 deploy/compose/.env 的 GATEKEEPER_HA_TOKEN。
      Put it into deploy/compose/.env as GATEKEEPER_HA_TOKEN.
   4. 重启本服务 / restart this service:
        docker compose up -d janus
============================================================

EOF
  exit 0
fi

# ── ③ HA 就绪等待(有 token 但 HA 可能还在启动;resolve_tz 启动时会调 HA)─────
echo "[janus] 等待 Home Assistant 就绪:${GATEKEEPER_HA_URL:-http://homeassistant:8123} ..."
for i in $(seq 1 30); do
  if python - "${GATEKEEPER_HA_URL:-http://homeassistant:8123}" <<'PY' 2>/dev/null
import socket, sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
socket.create_connection((u.hostname, u.port or 8123), 3).close()
PY
  then
    echo "[janus] HA 端口已通,启动服务。"
    break
  fi
  echo "[janus] HA 未就绪($i/30),2s 后重试..."
  sleep 2
done

# resolve_tz 在 HA 取不到 tz 时已兜底默认(不崩),故即便超时也安全启动:每请求 fail-closed。
exec python -m service
