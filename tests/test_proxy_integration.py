"""Integration tests for proxy pipeline — real retrieval stack, no injection mocks.

These tests exercise the full path:
  prompt -> retrieval_svc.list_suggested_blocks -> maybe_inject -> system message

Run with: pytest -m integration
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import turnzero.proxy.server as proxy_server
from turnzero.proxy import session as proxy_session
from turnzero.proxy.injection import maybe_inject
from turnzero.proxy.server import build_app

pytestmark = pytest.mark.integration

SECRET = "integration-secret"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_data_dir(tmp_path: Path) -> None:
    """Copy bundled blocks and build a real index into tmp_path."""
    from turnzero.index import build as build_index

    pkg_blocks = Path(__file__).parent.parent / "turnzero" / "data" / "blocks"
    repo_blocks = Path(__file__).parent.parent / "data" / "blocks"
    src = pkg_blocks if pkg_blocks.exists() else repo_blocks

    dest_blocks = tmp_path / "blocks"
    shutil.copytree(src, dest_blocks)
    build_index(dest_blocks, tmp_path / "index.jsonl", data_dir=tmp_path)


@pytest.fixture()
def seeded_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real blocks + index in an isolated dir with TURNZERO_DATA_DIR set."""
    _seed_data_dir(tmp_path)
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clear_proxy_sessions() -> None:
    proxy_session._sessions.clear()
    yield  # type: ignore[misc]
    proxy_session._sessions.clear()


# ---------------------------------------------------------------------------
# injection.py — full pipeline with real retrieval
# ---------------------------------------------------------------------------


def test_maybe_inject_real_retrieval_modifies_system(seeded_data_dir: Path) -> None:
    """Turn 0 with a FastAPI prompt injects real prior content into system message."""
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)

    messages = [{"role": "user", "content": "building a FastAPI async REST API with Pydantic models"}]
    result = maybe_inject(messages, sid)

    assert result[0]["role"] == "system", "No system message injected"
    assert len(result[0]["content"]) > 50, "System content suspiciously short"
    assert not proxy_session.is_turn_0(sid), "Session not marked injected"


def test_maybe_inject_turn_n_unchanged_with_real_retrieval(seeded_data_dir: Path) -> None:
    """Turn N always returns messages unchanged — real retrieval never called."""
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)
    proxy_session.mark_injected(sid)

    messages = [{"role": "user", "content": "building a FastAPI async REST API"}]
    result = maybe_inject(messages, sid)

    assert result == messages


def test_maybe_inject_system_message_contains_prior_text(seeded_data_dir: Path) -> None:
    """Injected system message contains block constraint text, not just a token."""
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)

    messages = [{"role": "user", "content": "building a FastAPI async REST API with Pydantic models"}]
    result = maybe_inject(messages, sid)

    if result[0]["role"] == "system":
        content = result[0]["content"]
        # Must contain structured prior content, not empty or trivial
        assert any(
            kw in content.lower()
            for kw in ["do not", "constraint", "fastapi", "async", "pydantic", "session_constraints"]
        ), f"System content doesn't look like a real prior: {content[:200]}"


def test_maybe_inject_prepends_to_existing_system(seeded_data_dir: Path) -> None:
    """Prior is prepended before existing system message, not replacing it."""
    sid = proxy_session.new_session_id()
    proxy_session.get_or_create(sid)

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "building a FastAPI async REST API with Pydantic"},
    ]
    result = maybe_inject(messages, sid)

    if result[0]["role"] == "system" and len(result) == 2:
        assert "You are a helpful assistant." in result[0]["content"], (
            "Original system message was dropped"
        )


# ---------------------------------------------------------------------------
# server.py — full HTTP stack with real injection
# ---------------------------------------------------------------------------


def test_server_forwards_injected_system_message(
    seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full HTTP path: request in -> real injection -> forwarded body has system message."""
    forwarded: list[dict] = []

    async def capture_json_response(url: str, body: dict, headers: dict) -> JSONResponse:
        forwarded.append(body)
        return JSONResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(proxy_server, "_json_response", capture_json_response)

    client = TestClient(build_app(secret=SECRET), raise_server_exceptions=True)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "building a FastAPI async REST API with Pydantic models"}],
            "stream": False,
        },
        headers={"X-TurnZero-Secret": SECRET},
    )

    assert resp.status_code == 200
    assert forwarded, "Request was never forwarded to provider"

    fwd_messages = forwarded[0]["messages"]
    assert fwd_messages[0]["role"] == "system", "No system message in forwarded request"
    assert len(fwd_messages[0]["content"]) > 50, "Injected content suspiciously short"


def test_server_turn_n_no_extra_system_injection(
    seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second request on same session is not re-injected."""
    forwarded: list[dict] = []

    async def capture_json_response(url: str, body: dict, headers: dict) -> JSONResponse:
        forwarded.append(body)
        return JSONResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(proxy_server, "_json_response", capture_json_response)

    import uuid
    session_id = str(uuid.uuid4())
    proxy_session.get_or_create(session_id)
    proxy_session.mark_injected(session_id)

    client = TestClient(build_app(secret=SECRET), raise_server_exceptions=True)
    client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "follow up question about FastAPI"}],
            "stream": False,
        },
        headers={"X-TurnZero-Secret": SECRET, "X-TurnZero-Session": session_id},
    )

    assert forwarded, "Request was never forwarded"
    fwd_messages = forwarded[0]["messages"]
    # No system message added on turn N
    assert fwd_messages[0]["role"] == "user", (
        "System message was injected on Turn N — should not happen"
    )
