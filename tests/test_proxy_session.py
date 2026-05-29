"""Tests for proxy session tracking — uuid4 IDs, TTL rotation, Turn 0 detection."""

from __future__ import annotations

import time
import uuid

import pytest

from turnzero.config import SESSION_TTL_SECONDS
from turnzero.proxy import session as proxy_session


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Isolate each test — clear shared session dict before and after."""
    proxy_session._sessions.clear()
    yield
    proxy_session._sessions.clear()


# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------


def test_new_session_id_is_valid_uuid4():
    sid = proxy_session.new_session_id()
    parsed = uuid.UUID(sid, version=4)
    assert str(parsed) == sid


def test_new_session_id_never_repeated():
    ids = {proxy_session.new_session_id() for _ in range(100)}
    assert len(ids) == 100


# ---------------------------------------------------------------------------
# get_or_create
# ---------------------------------------------------------------------------


def test_get_or_create_initialises_session():
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    assert sid in proxy_session._sessions
    assert proxy_session._sessions[sid]["injected"] is False


def test_get_or_create_returns_same_id():
    sid = proxy_session.new_session_id()
    result = proxy_session.get_or_create(sid)
    assert result == sid


def test_get_or_create_idempotent():
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)
    proxy_session.get_or_create(sid)  # second call must not reset injected
    assert not proxy_session.is_turn_0(sid)


# ---------------------------------------------------------------------------
# is_turn_0 / mark_injected
# ---------------------------------------------------------------------------


def test_is_turn_0_true_before_injection():
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    assert proxy_session.is_turn_0(sid)


def test_is_turn_0_false_after_injection():
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)
    assert not proxy_session.is_turn_0(sid)


def test_is_turn_0_true_for_unknown_session():
    # Missing session treated as Turn 0 — safe default
    assert proxy_session.is_turn_0("nonexistent-session-id")


def test_mark_injected_noop_for_unknown_session():
    proxy_session.mark_injected("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# TTL rotation
# ---------------------------------------------------------------------------


def test_ttl_expired_session_resets_on_get_or_create(monkeypatch):
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)
    assert not proxy_session.is_turn_0(sid)

    # Expire the session
    monkeypatch.setitem(
        proxy_session._sessions[sid],
        "started",
        time.time() - SESSION_TTL_SECONDS - 1,
    )

    proxy_session.get_or_create(sid)
    assert proxy_session.is_turn_0(sid)


def test_non_expired_session_preserved(monkeypatch):
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)

    # Still within TTL
    monkeypatch.setitem(
        proxy_session._sessions[sid],
        "started",
        time.time() - SESSION_TTL_SECONDS + 60,
    )

    proxy_session.get_or_create(sid)
    assert not proxy_session.is_turn_0(sid)  # still injected


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_removes_session():
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)
    proxy_session.clear(sid)
    assert sid not in proxy_session._sessions


def test_clear_noop_for_unknown_session():
    proxy_session.clear("does-not-exist")  # must not raise
