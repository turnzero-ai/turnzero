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

        asyncio.run(
            _post(
                "session_start",
                {
                    "blocks_suggested": 3,
                    "domains_suggested": ["fastapi", "nextjs"],
                    "has_personal_priors": True,
                },
            )
        )

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


def test_track_event_canonical_payload_structure() -> None:
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

        asyncio.run(_post("test_event", {"extra": "prop"}))

    assert mock_client.post.called
    payload = mock_client.post.call_args.kwargs.get("json", {})
    props = payload.get("properties", {})

    assert payload["distinct_id"] == "test-uuid"
    assert props["lib"] == "turnzero"
    assert props["extra"] == "prop"
    assert "$process_person_profile" not in props


def test_track_event_silent_on_network_error() -> None:
    with (
        patch("turnzero.telemetry._is_enabled", return_value=True),
        patch("turnzero.telemetry._POSTHOG_API_KEY", "phc_real_key"),
        patch("turnzero.telemetry._anonymous_id", return_value="uuid"),
        patch("httpx.AsyncClient", side_effect=Exception("network down")),
    ):
        from turnzero.telemetry import track_event

        track_event("setup_completed", {})  # must not raise


def test_telemetry_disabled_when_test_embeddings_set() -> None:
    """TURNZERO_TEST_EMBEDDINGS=1 must suppress telemetry — prevents eval runs from
    polluting PostHog cohorts with synthetic UUIDs."""
    with patch(
        "os.environ",
        {
            **__import__("os").environ,
            "TURNZERO_TEST_EMBEDDINGS": "1",
            "TURNZERO_TELEMETRY": "1",  # explicitly enabled — must still be suppressed
        },
    ):
        from turnzero.telemetry import _is_enabled

        assert _is_enabled() is False


def test_telemetry_not_suppressed_without_test_embeddings(tmp_path: Path) -> None:
    """Without TURNZERO_TEST_EMBEDDINGS, telemetry follows config normally."""
    clean_env = {
        k: v
        for k, v in __import__("os").environ.items()
        if k not in ("TURNZERO_TEST_EMBEDDINGS", "TURNZERO_TELEMETRY")
    }
    with (
        patch("os.environ", clean_env),
        patch("turnzero.config.load_telemetry_config", return_value={"enabled": True}),
        patch("turnzero.config.get_telemetry_dir", return_value=tmp_path),
    ):
        from turnzero.telemetry import _is_enabled

        assert _is_enabled() is True


def test_telemetry_dir_ignores_data_dir_override(tmp_path: Path) -> None:
    """get_telemetry_dir() always returns ~/.turnzero even when TURNZERO_DATA_DIR is set.

    Prevents dev data-dir overrides from splitting telemetry across multiple
    anonymous_ids in PostHog.
    """
    import os

    from turnzero.config import get_telemetry_dir

    override = str(tmp_path / "dev_data")
    with patch.dict(os.environ, {"TURNZERO_DATA_DIR": override}):
        tel_dir = get_telemetry_dir()

    from pathlib import Path

    assert tel_dir == Path.home() / ".turnzero"
    assert str(override) not in str(tel_dir)


def test_post_debug_logging(capsys: object) -> None:
    """TURNZERO_DEBUG=1 prints send/receive lines to stderr without leaking event content."""
    import asyncio
    import os
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("turnzero.telemetry._anonymous_id", return_value="aaaa-bbbb-cccc-dddd-eeee"),
        patch("turnzero.telemetry._base_props", return_value={}),
        patch("httpx.AsyncClient", return_value=mock_ctx),
        patch.dict(os.environ, {"TURNZERO_DEBUG": "1"}),
    ):
        from turnzero.telemetry import _post

        asyncio.run(_post("test_event", {}))

    captured = capsys.readouterr()
    assert "[telemetry]" in captured.err
    assert "test_event" in captured.err
    assert "200" in captured.err
    # Full UUID must not appear — only truncated prefix
    assert "aaaa-bbbb-cccc-dddd-eeee" not in captured.err
