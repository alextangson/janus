#!/bin/bash
# 同步引擎进集成 vendored 副本:单一源真相 = root gatekeeper/。
# vendored 树已纳入版本控制(供 git clone / HACS 安装),改了 root 引擎后必须重跑本脚本,
# 否则 tests/test_vendoring.py 会失败。CI/提交前的同步入口,不碰 docker/HA。
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf custom_components/janus/gatekeeper
cp -R gatekeeper custom_components/janus/gatekeeper
find custom_components/janus -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
echo "vendored: custom_components/janus/gatekeeper ← gatekeeper/"
