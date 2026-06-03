from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEVICES_PATH = DATA / "devices.json"
TESTSET_PATH = DATA / "testset.jsonl"

# 置信度阈值;可用 GATEKEEPER_TAU 覆盖以便扫阈值
TAU = float(os.environ.get("GATEKEEPER_TAU", "0.7"))

# 云端强模型;验证"方法成立"用,可换 claude-opus-4-8
MODEL = "claude-sonnet-4-6"

# claude | local —— 可用 GATEKEEPER_BACKEND 覆盖(Phase 1b 切 local)
BACKEND = os.environ.get("GATEKEEPER_BACKEND", "claude")

# Phase 1b 本地模型(Ollama,OpenAI 兼容);可用 GATEKEEPER_LOCAL_MODEL 覆盖
LOCAL_MODEL = os.environ.get("GATEKEEPER_LOCAL_MODEL", "gemma4")
LOCAL_BASE_URL = "http://localhost:11434/v1"
