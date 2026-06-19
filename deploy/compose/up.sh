#!/usr/bin/env bash
# 一条命令起整套栈:① 构建 app dist(私有仓 → web/dist) ② docker compose up --build。
# 透传额外参数,如:./up.sh -d(后台)。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

"$HERE/build-app.sh"

echo "[up] docker compose up --build"
exec docker compose up --build "$@"
