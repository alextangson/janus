#!/usr/bin/env bash
# 从本地 janus-app(私有仓)构建 ingress dist 并拷进 add-on 的 app/,供 Dockerfile 烤入。
# 默认找 sibling ../janus-app(相对仓库根的 ../janus-app);可用 JANUS_APP_DIR 覆盖。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${JANUS_APP_DIR:-$HERE/../../../../janus-app}"

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: 找不到 janus-app 源码:$APP_DIR" >&2
  echo "  janus-app 是私有仓。设 JANUS_APP_DIR 指向本地副本,或 clone 到该路径。" >&2
  exit 1
fi

echo "[build-addon-app] 构建 janus-app ingress dist ← $APP_DIR"
( cd "$APP_DIR" && npm ci && npm run build:ingress )

DEST="$HERE/app"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$APP_DIR/dist/." "$DEST/"
echo "[build-addon-app] dist 已就位:$DEST"
