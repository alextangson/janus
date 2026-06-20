#!/usr/bin/env bash
# 从本地 janus-app(私有仓)构建 dist 并拷进 web/dist,供 Dockerfile.web 烤入。
# janus-app 默认在 sibling ../../../janus-app(相对 smarthome 根的 ../janus-app);
# 可用 JANUS_APP_DIR 覆盖。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${JANUS_APP_DIR:-$HERE/../../../janus-app}"

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: 找不到 janus-app 源码:$APP_DIR" >&2
  echo "  janus-app 是私有仓。设 JANUS_APP_DIR 指向你的本地副本,或将其 clone 到该路径。" >&2
  exit 1
fi

echo "[build-app] 构建 janus-app dist ← $APP_DIR"
( cd "$APP_DIR" && npm ci && npm run build )

DEST="$HERE/web/dist"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$APP_DIR/dist/." "$DEST/"
echo "[build-app] dist 已就位:$DEST"
