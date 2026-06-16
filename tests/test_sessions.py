import pytest

from service.sessions import ConversationStore


def test_new_conversation_gets_unguessable_id():
    store = ConversationStore(now=lambda: 0.0)
    cid = store.new_conversation_id()
    assert isinstance(cid, str) and len(cid) >= 16
    assert cid != store.new_conversation_id()


def test_get_state_creates_and_reuses():
    store = ConversationStore(now=lambda: 0.0)
    s1 = store.get_state("conv-1")
    s2 = store.get_state("conv-1")
    assert s1 is s2
    assert s1.session is not None
    assert s1.pending_id is None


def test_issue_then_take_pending_is_one_time():
    clock = [100.0]
    store = ConversationStore(now=lambda: clock[0], pending_ttl=120.0)
    st = store.get_state("c")
    pid = store.issue_pending(st)
    assert st.pending_id == pid
    assert store.take_pending(st, pid) is True
    assert st.pending_id is None
    assert store.take_pending(st, pid) is False


def test_take_pending_rejects_wrong_or_expired():
    clock = [100.0]
    store = ConversationStore(now=lambda: clock[0], pending_ttl=120.0)
    st = store.get_state("c")
    pid = store.issue_pending(st)
    assert store.take_pending(st, "wrong-id") is False
    assert st.pending_id == pid          # 安全:错误猜测绝不烧掉真 pending(防猜测/replay)
    clock[0] = 100.0 + 121.0
    assert store.take_pending(st, pid) is False


def test_idempotency_cache_roundtrip():
    clock = [0.0]
    store = ConversationStore(now=lambda: clock[0], idempotency_ttl=300.0)
    st = store.get_state("c")
    assert store.idempotent_get(st, "key1") is None
    store.idempotent_put(st, "key1", {"status": "executed"})
    assert store.idempotent_get(st, "key1") == {"status": "executed"}
    clock[0] = 301.0
    assert store.idempotent_get(st, "key1") is None


def test_evict_expired_caps_sessions():
    store = ConversationStore(now=lambda: 0.0, max_sessions=2)
    store.get_state("a"); store.get_state("b"); store.get_state("c")
    assert store.session_count() <= 2
