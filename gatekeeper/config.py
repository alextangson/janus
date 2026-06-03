from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEVICES_PATH = DATA / "devices.json"
TESTSET_PATH = DATA / "testset.jsonl"

# 置信度阈值;Phase 1a 在调参集上调定后写回这里
TAU = 0.7

# 云端强模型;验证"方法成立"用,可换 claude-opus-4-8
MODEL = "claude-sonnet-4-6"

# claude | local —— Phase 1b 切到 local 只改这一处
BACKEND = "claude"

# Phase 1b 本地模型(Ollama,OpenAI 兼容)
LOCAL_MODEL = "qwen2.5:7b"
LOCAL_BASE_URL = "http://localhost:11434/v1"
