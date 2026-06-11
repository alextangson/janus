#!/bin/bash
# 部署 Janus 进本机 HA(Docker named volume):vendor gatekeeper → docker cp → 重启。
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf custom_components/janus/gatekeeper
cp -R gatekeeper custom_components/janus/gatekeeper
find custom_components/janus -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

docker exec homeassistant mkdir -p /config/custom_components
docker exec homeassistant rm -rf /config/custom_components/janus
docker cp custom_components/janus homeassistant:/config/custom_components/
docker restart homeassistant
echo "Janus 已部署;HA 重启中(约 30-60s 后可用)。"
