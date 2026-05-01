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
_POSTHOG_HOST = "https://us.i.posthog.com"

# In-memory set of session_ids that already fired session_start this process.
_session_start_fired: set[str] = set()


def _is_enabled() -> bool:
    if os.environ.get("TURNZERO_TELEMETRY", "").strip() in ("0", "false", "off"):
        return False
    from turnzero.config import _data_dir, load_telemetry_config
    return bool(load_telemetry_config(_data_dir()).get("enabled", True))


def _anonymous_id() -> str:
    import uuid

    from turnzero.config import _data_dir, load_telemetry_config, save_telemetry_config

    data_dir = _data_dir()
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
        "client_version": _client_version(),
        "os_type": _os_type(),
        "$lib": "turnzero",
    }


async def _post(event: str, props: dict[str, Any]) -> None:
    try:
        import httpx
        payload = {
            "api_key": _POSTHOG_API_KEY,
            "event": event,
            "distinct_id": _anonymous_id(),
            "properties": {**_base_props(), **props},
        }
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{_POSTHOG_HOST}/capture/", json=payload)
    except Exception:
        pass


def track_event(event: str, props: dict[str, Any] | None = None) -> None:
    """Fire-and-forget telemetry event. Silent on any error."""
    if _POSTHOG_API_KEY == "phc_REPLACE_ME":
        return
    if not _is_enabled():
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_post(event, props or {}))
        else:
            asyncio.run(_post(event, props or {}))
    except Exception:
        pass


def track_session_start(
    session_id: str | None,
    blocks_suggested: int,
    domains: list[str],
    has_personal_priors: bool,
) -> None:
    """Fire session_start once per session_id per process."""
    key = session_id or "__no_session__"
    if key in _session_start_fired:
        return
    _session_start_fired.add(key)
    track_event("session_start", {
        "blocks_suggested": blocks_suggested,
        "domains_suggested": domains,
        "has_personal_priors": has_personal_priors,
    })


def track_block_injected(domain: str, tier: str) -> None:
    track_event("block_injected", {"domain": domain, "tier": tier})


def track_candidate_submitted(domain: str, auto_approved: bool, result: str) -> None:
    track_event("candidate_submitted", {
        "domain": domain,
        "auto_approved": auto_approved,
        "result": result,
    })


def track_session_summary(session_id: str | None) -> None:
    """Signal session end. PostHog derives rates from individual events."""
    track_event("session_summary", {})
    _session_start_fired.discard(session_id or "__no_session__")


def track_setup_completed(embedding_backend: str) -> None:
    track_event("setup_completed", {"embedding_backend": embedding_backend})
