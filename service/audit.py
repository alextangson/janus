from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Callable

from gatekeeper.audit import build_record, display_status

_LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  request_id TEXT,
  conversation_id TEXT,
  caller TEXT,
  event TEXT NOT NULL,
  phase TEXT,
  utterance TEXT,
  verdict TEXT,
  stage TEXT,
  device_id TEXT,
  operation TEXT,
  params TEXT,
  confidence REAL,
  reason TEXT,
  executed INTEGER,
  error TEXT,
  pending_after INTEGER
);
"""

_COLS = ["ts", "request_id", "conversation_id", "caller", "event", "phase", "utterance",
         "verdict", "stage", "device_id", "operation", "params", "confidence", "reason",
         "executed", "error", "pending_after"]

_EVENT_RENAME = {"pending": "proposed"}


class AuditSink:
    """SQLite append-only 决策审计。复用纯层 build_record/display_status。
    审计失败 fail-open:record_* 内部异常被吞,绝不冒泡进 handler。"""

    def __init__(self, db_path: str, now: Callable[[], float] = time.time):
        self._now = now
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def record_decision(self, *, request_id: str, conversation_id: str, caller: str,
                        phase: str, utterance: str, outcome, pending_after: bool) -> None:
        try:
            rec = build_record(utterance, outcome, pending_after)
            d = asdict(rec)
            status = display_status(d)
            event = _EVENT_RENAME.get(status, status)
            self._insert({
                "event": event, "phase": phase, "utterance": rec.utterance,
                "verdict": rec.verdict, "stage": rec.stage, "device_id": rec.device_id,
                "operation": rec.operation, "params": json.dumps(rec.params, ensure_ascii=False),
                "confidence": rec.confidence, "reason": rec.reason,
                "executed": int(rec.executed), "error": rec.error,
                "pending_after": int(rec.pending_after),
            }, request_id, conversation_id, caller)
        except Exception:
            _LOGGER.exception("audit record_decision failed")

    def record_lifecycle(self, *, event: str, request_id: str, conversation_id: str,
                         caller: str, device_id: str | None, operation: str | None) -> None:
        try:
            self._insert({"event": event, "phase": "lifecycle", "device_id": device_id,
                          "operation": operation}, request_id, conversation_id, caller)
        except Exception:
            _LOGGER.exception("audit record_lifecycle failed")

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _insert(self, fields: dict, request_id: str, conversation_id: str, caller: str) -> None:
        row = {c: None for c in _COLS}
        row.update(fields)
        row["ts"] = self._now()
        row["request_id"] = request_id
        row["conversation_id"] = conversation_id
        row["caller"] = caller
        with self._lock:
            self._conn.execute(
                f"INSERT INTO audit ({','.join(_COLS)}) VALUES ({','.join('?' for _ in _COLS)})",
                [row[c] for c in _COLS])
            self._conn.commit()
