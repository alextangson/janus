from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from gatekeeper.session import Session


@dataclass
class ConversationState:
    session: Session
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_id: str | None = None
    pending_expires_at: float | None = None
    last_seen: float = 0.0
    idempotency: dict[str, tuple[float, dict]] = field(default_factory=dict)


class ConversationStore:
    """内存会话存储:每 conversation 一个 Session + pending_id 生命周期 + 幂等缓存。
    单盒子 v1;换 Redis 是后续。now 可注入以便测试。"""

    def __init__(self, now: Callable[[], float] = time.time,
                 pending_ttl: float = 120.0, idempotency_ttl: float = 300.0,
                 max_sessions: int = 1000):
        # now=time.time(墙钟 epoch 秒):pending_expires_at 要给客户端算倒计时,需墙钟而非
        # monotonic(执行死线另用 time.monotonic,见 app.py)。TTL 比较用墙钟差值,标准做法。
        self._now = now
        self._pending_ttl = pending_ttl
        self._idempotency_ttl = idempotency_ttl
        self._max_sessions = max_sessions
        self._states: dict[str, ConversationState] = {}

    def new_conversation_id(self) -> str:
        return secrets.token_urlsafe(16)

    def get_state(self, conversation_id: str) -> ConversationState:
        st = self._states.get(conversation_id)
        if st is None:
            self._evict_if_needed()
            st = ConversationState(session=Session())
            self._states[conversation_id] = st
        st.last_seen = self._now()
        return st

    def issue_pending(self, st: ConversationState) -> str:
        pid = secrets.token_urlsafe(24)
        st.pending_id = pid
        st.pending_expires_at = self._now() + self._pending_ttl
        return pid

    def take_pending(self, st: ConversationState, pending_id: str) -> bool:
        if st.pending_id is None or st.pending_id != pending_id:
            return False
        if st.pending_expires_at is not None and self._now() > st.pending_expires_at:
            self.clear_pending(st)
            return False
        self.clear_pending(st)
        return True

    def clear_pending(self, st: ConversationState) -> None:
        st.pending_id = None
        st.pending_expires_at = None

    def idempotent_get(self, st: ConversationState, key: str) -> dict | None:
        hit = st.idempotency.get(key)
        if hit is None:
            return None
        issued_at, dto = hit
        if self._now() - issued_at > self._idempotency_ttl:
            del st.idempotency[key]
            return None
        return dto

    def idempotent_put(self, st: ConversationState, key: str, dto: dict) -> None:
        st.idempotency[key] = (self._now(), dto)

    def session_count(self) -> int:
        return len(self._states)

    def _evict_if_needed(self) -> None:
        while len(self._states) >= self._max_sessions:
            oldest = min(self._states, key=lambda k: self._states[k].last_seen)
            del self._states[oldest]
