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

_POSTHOG_API_KEY = "phc_BWoXqMusHqiX6d3eqooSm4PVtEABkJnYFwurYmqj7oU3"
_POSTHOG_HOST = "https://eu.i.posthog.com"

# In-memory set of session_ids that already fired session_start this process.
_session_start_fired: set[str] = set()

# Track background tasks to allow flushing before exit.
_pending_tasks: set[asyncio.Task[None]] = set()


def _is_enabled() -> bool:
    if os.environ.get("TURNZERO_TELEMETRY", "").strip() in ("0", "false", "off"):
        return False
    if os.environ.get("TURNZERO_TEST_EMBEDDINGS", "").strip() in ("1", "true"):
        return False
    from turnzero.config import get_data_dir, load_telemetry_config

    return bool(load_telemetry_config(get_data_dir()).get("enabled", True))


def _anonymous_id() -> str:
    import uuid

    from turnzero.config import (
        get_data_dir,
        load_telemetry_config,
        save_telemetry_config,
    )

    data_dir = get_data_dir()
    cfg = load_telemetry_config(data_dir)
    if not cfg.get("anonymous_id"):
        cfg["anonymous_id"] = str(uuid.uuid4())
        save_telemetry_config(data_dir, cfg)
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

    with contextlib.suppress(Exception):
        import logging

        import httpx

        logging.getLogger("httpx").setLevel(logging.WARNING)
        payload = {
            "api_key": _POSTHOG_API_KEY,
            "event": event,
            "distinct_id": _anonymous_id(),
            "properties": {
                **_base_props(),
                **props,
            },
        }
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{_POSTHOG_HOST}/capture", json=payload)


def track_event(event: str, props: dict[str, Any] | None = None) -> None:
    """Fire-and-forget telemetry event. Silent on any error."""
    if _POSTHOG_API_KEY == "phc_REPLACE_ME":
        return
    if not _is_enabled():
        return
    import contextlib

    with contextlib.suppress(Exception):
        loop = asyncio.get_running_loop()
        task = loop.create_task(_post(event, props or {}))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    if not _pending_tasks:  # If create_task failed (no loop)
        with contextlib.suppress(Exception):
            asyncio.run(_post(event, props or {}))


async def flush_telemetry(timeout: float = 2.0) -> None:
    """Wait for all pending telemetry tasks to complete."""
    if not _pending_tasks:
        return
    import contextlib

    with contextlib.suppress(Exception):
        await asyncio.wait_for(
            asyncio.gather(*_pending_tasks, return_exceptions=True),
            timeout=timeout,
        )
    _pending_tasks.clear()


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
        "session_start",
        {
            "blocks_suggested": blocks_suggested,
            "domains_suggested": domains,
            "has_personal_priors": has_personal_priors,
            "personal_block_count": personal_block_count,
            "total_block_count": total_block_count,
        },
    )


def track_block_injected(domain: str, tier: str) -> None:
    track_event("block_injected", {"domain": domain, "tier": tier})


def track_candidate_submitted(domain: str, auto_approved: bool, result: str) -> None:
    track_event(
        "candidate_submitted",
        {
            "domain": domain,
            "auto_approved": auto_approved,
            "result": result,
        },
    )


def track_session_summary(session_id: str | None) -> None:
    """Signal session end. PostHog derives rates from individual events."""
    track_event("session_summary", {})
    _session_start_fired.discard(session_id or "__no_session__")


def track_setup_completed(
    embedding_backend: str, clients_registered: list[str] | None = None
) -> None:
    track_event(
        "setup_completed",
        {
            "embedding_backend": embedding_backend,
            "clients_registered": clients_registered or [],
        },
    )


def track_review_opened(candidate_count: int, low_confidence_count: int) -> None:
    track_event(
        "review_opened",
        {
            "candidate_count": candidate_count,
            "low_confidence_count": low_confidence_count,
        },
    )


def track_stats_viewed(sessions_total: int, blocks_total: int) -> None:
    track_event(
        "stats_viewed",
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
    track_event("list_viewed", props)
