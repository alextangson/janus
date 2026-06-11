from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEVICES_PATH = DATA / "devices.json"
TESTSET_PATH = DATA / "testset.jsonl"


def load_env(path: str | Path | None = None) -> None:
    """读 .env(默认仓库根),setdefault 注入环境;不存在则静默(shell 可能已提供)。"""
    env = Path(path) if path is not None else ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# 置信度阈值;可用 GATEKEEPER_TAU 覆盖以便扫阈值
TAU = float(os.environ.get("GATEKEEPER_TAU", "0.7"))

# 云端强模型;验证"方法成立"用,可换 claude-opus-4-8
MODEL = "claude-sonnet-4-6"

# claude | local —— 可用 GATEKEEPER_BACKEND 覆盖(Phase 1b 切 local)
BACKEND = os.environ.get("GATEKEEPER_BACKEND", "claude")

# Phase 1b 本地模型(Ollama,OpenAI 兼容);可用 GATEKEEPER_LOCAL_MODEL 覆盖
LOCAL_MODEL = os.environ.get("GATEKEEPER_LOCAL_MODEL", "gemma4")
LOCAL_BASE_URL = "http://localhost:11434/v1"

# Phase 2 / P2.1 — Home Assistant 连接(可用环境变量覆盖)
HA_BASE_URL = os.environ.get("GATEKEEPER_HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("GATEKEEPER_HA_TOKEN", "")
HA_OVERRIDES_PATH = DATA / "ha_overrides.json"
