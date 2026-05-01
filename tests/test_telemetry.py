"""Tests for telemetry.py — opt-out, payload safety, session deduplication."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _reset_fired(session_id: str | None = None) -> None:
    from turnzero import telemetry
    telemetry._session_start_fired.discard(session_id or "__no_session__")


def test_telemetry_disabled_by_env_fires_nothing(tmp_path: Path) -> None:
    with (
        patch("os.environ", {**__import__("os").environ, "TURNZERO_TELEMETRY": "0"}),
        patch("turnzero.telemetry._post") as mock_post,
    ):
        from turnzero.telemetry import track_event
        track_event("setup_completed", {"embedding_backend": "ollama"})

    mock_post.assert_not_called()


def test_telemetry_disabled_by_config_fires_nothing(tmp_path: Path) -> None:
    with (
        patch("turnzero.telemetry._is_enabled", return_value=False),
        patch("turnzero.telemetry._post") as mock_post,
        patch("turnzero.telemetry._POSTHOG_API_KEY", "phc_real_key"),
    ):
        from turnzero.telemetry import track_event
        track_event("setup_completed", {})

    mock_post.assert_not_called()


def test_track_event_payload_never_contains_prompt_text() -> None:
    import asyncio

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=MagicMock())
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("turnzero.telemetry._is_enabled", return_value=True),
        patch("turnzero.telemetry._anonymous_id", return_value="test-uuid"),
        patch("turnzero.telemetry._POSTHOG_API_KEY", "phc_real_key"),
        patch("httpx.AsyncClient", return_value=mock_ctx),
    ):
        from turnzero.telemetry import _post
        asyncio.run(_post("session_start", {
            "blocks_suggested": 3,
            "domains_suggested": ["fastapi", "nextjs"],
            "has_personal_priors": True,
        }))

    assert mock_client.post.called
    payload = mock_client.post.call_args.kwargs.get("json", {})
    props = payload.get("properties", {})

    for key in ("prompt", "constraints", "content", "text", "block_content"):
        assert key not in props, f"Sensitive field '{key}' found in telemetry payload"
    assert "blocks_suggested" in props


def test_track_session_start_fires_only_once_per_session(tmp_path: Path) -> None:
    _reset_fired("test-session-123")
    call_count = 0

    def fake_track(event: str, props: dict | None = None) -> None:
        nonlocal call_count
        if event == "session_start":
            call_count += 1

    with patch("turnzero.telemetry.track_event", side_effect=fake_track):
        from turnzero.telemetry import track_session_start
        track_session_start("test-session-123", 5, ["fastapi"], True)
        track_session_start("test-session-123", 5, ["fastapi"], True)
        track_session_start("test-session-123", 5, ["fastapi"], True)

    assert call_count == 1
    _reset_fired("test-session-123")


def test_track_session_start_fires_for_different_sessions() -> None:
    _reset_fired("sess-a")
    _reset_fired("sess-b")
    events: list[str] = []

    def fake_track(event: str, props: dict | None = None) -> None:
        if event == "session_start":
            events.append(event)

    with patch("turnzero.telemetry.track_event", side_effect=fake_track):
        from turnzero.telemetry import track_session_start
        track_session_start("sess-a", 3, ["fastapi"], True)
        track_session_start("sess-b", 2, ["nextjs"], False)

    assert len(events) == 2
    _reset_fired("sess-a")
    _reset_fired("sess-b")


def test_telemetry_config_default_enabled(tmp_path: Path) -> None:
    from turnzero.config import load_telemetry_config
    cfg = load_telemetry_config(tmp_path)
    assert cfg["enabled"] is True


def test_telemetry_config_opt_out_persists(tmp_path: Path) -> None:
    from turnzero.config import load_telemetry_config, save_telemetry_config
    cfg = load_telemetry_config(tmp_path)
    cfg["enabled"] = False
    save_telemetry_config(tmp_path, cfg)
    reloaded = load_telemetry_config(tmp_path)
    assert reloaded["enabled"] is False


def test_anonymous_id_generated_and_stable(tmp_path: Path) -> None:
    import uuid

    from turnzero.config import load_telemetry_config, save_telemetry_config

    cfg = load_telemetry_config(tmp_path)
    assert not cfg.get("anonymous_id")

    cfg["anonymous_id"] = str(uuid.uuid4())
    save_telemetry_config(tmp_path, cfg)

    reloaded = load_telemetry_config(tmp_path)
    assert reloaded["anonymous_id"] == cfg["anonymous_id"]


def test_track_event_silent_on_network_error() -> None:
    with (
        patch("turnzero.telemetry._is_enabled", return_value=True),
        patch("turnzero.telemetry._POSTHOG_API_KEY", "phc_real_key"),
        patch("turnzero.telemetry._anonymous_id", return_value="uuid"),
        patch("httpx.AsyncClient", side_effect=Exception("network down")),
    ):
        from turnzero.telemetry import track_event
        track_event("setup_completed", {})  # must not raise
