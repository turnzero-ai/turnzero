"""Anonymous usage telemetry via PostHog.

Fire-and-forget, async, never blocks. Opt-out via `turnzero telemetry off`
or TURNZERO_TELEMETRY=0 env var.

What is sent: anonymous_id (UUID), event name, domain names, block counts,
client version, OS type. Never: prompt text, block content, file paths,
API keys, or any user-identifiable data.
"""

from __future__ import annotations

import asyncio
import os
import platform
from typing import Any

from turnzero.types import TelemetryEvent

_POSTHOG_API_KEY = "phc_BWoXqMusHqiX6d3eqooSm4PVtEABkJnYFwurYmqj7oU3"
_POSTHOG_HOST = "https://eu.i.posthog.com"

# In-memory set of session_ids that already fired session_start this process.
_session_start_fired: set[str] = set()

# Track background tasks (MCP/async context) and threads (CLI context) for flush on exit.
_pending_tasks: set[asyncio.Task[None]] = set()
_pending_threads: list[object] = []  # list[threading.Thread] — avoid import at module level


def _is_enabled() -> bool:
    if os.environ.get("TURNZERO_TELEMETRY", "").strip() in ("0", "false", "off"):
        return False
    if os.environ.get("TURNZERO_TEST_EMBEDDINGS", "").strip() in ("1", "true"):
        return False
    from turnzero.config import get_telemetry_dir, load_telemetry_config

    return bool(load_telemetry_config(get_telemetry_dir()).get("enabled", True))


def _anonymous_id() -> str:
    import uuid

    from turnzero.config import (
        get_telemetry_dir,
        load_telemetry_config,
        save_telemetry_config,
    )

    tel_dir = get_telemetry_dir()
    cfg = load_telemetry_config(tel_dir)
    if not cfg.get("anonymous_id"):
        cfg["anonymous_id"] = str(uuid.uuid4())
        save_telemetry_config(tel_dir, cfg)
    return str(cfg["anonymous_id"])


def _client_version() -> str:
    try:
        from importlib.metadata import version

        return version("turnzero")
    except Exception:
        return "unknown"


def _os_type() -> str:
    return platform.system().lower()


def _base_props() -> dict[str, Any]:
    return {
        "lib": "turnzero",
        "client_version": _client_version(),
        "os_type": _os_type(),
    }


async def _post(event: str, props: dict[str, Any]) -> None:
    import contextlib
    import sys

    debug = os.environ.get("TURNZERO_DEBUG")
    with contextlib.suppress(Exception):
        import logging

        import httpx

        logging.getLogger("httpx").setLevel(logging.WARNING)
        anon_id = _anonymous_id()
        payload = {
            "api_key": _POSTHOG_API_KEY,
            "event": event,
            "distinct_id": anon_id,
            "properties": {
                **_base_props(),
                **props,
            },
        }
        if debug:
            print(f"[telemetry] → {event} (id={anon_id[:8]}…)", file=sys.stderr)
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(f"{_POSTHOG_HOST}/capture", json=payload)
            if debug:
                print(f"[telemetry] ← {r.status_code}", file=sys.stderr)


def track_event(event: str, props: dict[str, Any] | None = None) -> None:
    """Fire-and-forget telemetry event. Silent on any error, never blocks caller."""
    if _POSTHOG_API_KEY == "phc_REPLACE_ME":
        return
    if not _is_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
        # Async context (MCP server): schedule as a task, truly non-blocking.
        task = loop.create_task(_post(event, props or {}))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    except RuntimeError:
        # No running event loop (CLI context): background thread, joined at exit via
        # flush_pending_threads(). Not daemon — must complete before process exits.
        import threading

        t = threading.Thread(
            target=lambda: asyncio.run(_post(event, props or {})),
            daemon=False,
        )
        _pending_threads.append(t)
        t.start()
    except Exception:  # noqa: BLE001
        pass


async def flush_telemetry(timeout: float = 2.0) -> None:
    """Wait for all pending MCP/async telemetry tasks to complete."""
    if not _pending_tasks:
        return
    import contextlib

    with contextlib.suppress(Exception):
        await asyncio.wait_for(
            asyncio.gather(*_pending_tasks, return_exceptions=True),
            timeout=timeout,
        )
    _pending_tasks.clear()


def flush_pending_threads(timeout: float = 3.0) -> None:
    """Join all pending CLI telemetry threads. Called from cli_entry() finally block."""
    import contextlib
    import threading
    import time

    deadline = time.monotonic() + timeout
    for t in list(_pending_threads):
        if isinstance(t, threading.Thread):
            remaining = max(0.0, deadline - time.monotonic())
            with contextlib.suppress(Exception):
                t.join(timeout=remaining)
    _pending_threads.clear()


def track_session_start(
    session_id: str | None,
    blocks_suggested: int,
    domains: list[str],
    has_personal_priors: bool,
    personal_block_count: int = 0,
    total_block_count: int = 0,
) -> None:
    """Fire session_start once per session_id per process."""
    key = session_id or "__no_session__"
    if key in _session_start_fired:
        return
    _session_start_fired.add(key)
    track_event(
        TelemetryEvent.SESSION_START,
        {
            "blocks_suggested": blocks_suggested,
            "domains_suggested": domains,
            "has_personal_priors": has_personal_priors,
            "personal_block_count": personal_block_count,
            "total_block_count": total_block_count,
        },
    )


def track_block_injected(domain: str, tier: str) -> None:
    track_event(TelemetryEvent.BLOCK_INJECTED, {"domain": domain, "tier": tier})


def track_candidate_submitted(domain: str, auto_approved: bool, result: str) -> None:
    track_event(
        TelemetryEvent.CANDIDATE_SUBMITTED,
        {
            "domain": domain,
            "auto_approved": auto_approved,
            "result": result,
        },
    )


def track_session_summary(session_id: str | None) -> None:
    """Signal session end. PostHog derives rates from individual events."""
    track_event(TelemetryEvent.SESSION_SUMMARY, {})
    _session_start_fired.discard(session_id or "__no_session__")


def track_setup_completed(
    embedding_backend: str, clients_registered: list[str] | None = None
) -> None:
    track_event(
        TelemetryEvent.SETUP_COMPLETED,
        {
            "embedding_backend": embedding_backend,
            "clients_registered": clients_registered or [],
        },
    )


def track_review_opened(candidate_count: int, low_confidence_count: int) -> None:
    track_event(
        TelemetryEvent.REVIEW_OPENED,
        {
            "candidate_count": candidate_count,
            "low_confidence_count": low_confidence_count,
        },
    )


def track_stats_viewed(sessions_total: int, blocks_total: int) -> None:
    track_event(
        TelemetryEvent.STATS_VIEWED,
        {
            "sessions_total": sessions_total,
            "blocks_total": blocks_total,
        },
    )


def track_list_viewed(
    mode: str,
    blocks_shown: int,
    domain: str | None = None,
) -> None:
    props: dict[str, Any] = {"mode": mode, "blocks_shown": blocks_shown}
    if domain:
        props["domain"] = domain
    track_event(TelemetryEvent.LIST_VIEWED, props)


def track_domain_changed(action: str, domain: str, total_active: int) -> None:
    track_event(
        TelemetryEvent.DOMAIN_CHANGED,
        {"action": action, "domain": domain, "total_active": total_active},
    )


def _is_proxy_telemetry_enabled() -> bool:
    """Proxy telemetry is opt-IN — requires proxy.telemetry_consent: true in config.

    Unlike MCP telemetry (opt-out), proxy processes messages in-memory so explicit
    consent is required before any PostHog events fire.
    """
    if not _is_enabled():
        return False
    try:
        from turnzero.config import get_data_dir, load_config

        return bool(load_config(get_data_dir()).get("proxy", {}).get("telemetry_consent", False))
    except Exception:
        return False


def track_proxy_turn(
    session_id: str,
    reason: str,
    prompt_word_count: int,
    injection_happened: bool,
    blocks_count: int,
    provider: str,
    model: str,
) -> None:
    """Fire proxy_turn event. Suppressed until proxy.telemetry_consent: true in config.

    Args:
        session_id: Proxy session ID — enables cross-correlation with submit_candidate.
        reason: "turn_0" | "skip" (degradation re-injection added in Phase 3).
        prompt_word_count: Word count of the user prompt — no raw text stored.
        injection_happened: True if priors were prepended to the system message.
        blocks_count: Number of blocks injected (0 when injection_happened is False).
        provider: Short provider label e.g. "anthropic", "openai", "google", "custom".
        model: Model name from the request body.
    """
    if not _is_proxy_telemetry_enabled():
        return
    track_event(
        TelemetryEvent.PROXY_TURN,
        {
            "session_id": session_id,
            "reason": reason,
            "prompt_word_count": prompt_word_count,
            "injection_happened": injection_happened,
            "blocks_count": blocks_count,
            "provider": provider,
            "model": model,
        },
    )
