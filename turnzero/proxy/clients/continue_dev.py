"""Continue.dev config patcher — adds/updates TurnZero proxy model entry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path.home() / ".continue" / "config.json"
_ENTRY_TITLE = "TurnZero Proxy"


def is_installed() -> bool:
    return _CONFIG_PATH.exists()


def _make_entry(port: int, secret: str) -> dict[str, Any]:
    return {
        "title": _ENTRY_TITLE,
        "provider": "openai",
        "model": "gpt-4o",
        "apiBase": f"http://localhost:{port}/v1",
        "apiKey": "YOUR_PROVIDER_KEY_HERE",
        "requestOptions": {
            "headers": {"X-TurnZero-Secret": secret},
        },
    }


def _load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {"models": []}
    raw = _CONFIG_PATH.read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    if "models" not in result:
        result["models"] = []
    return result


def _save_config(cfg: dict[str, Any]) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def patch(port: int, secret: str) -> bool:
    """Add or update TurnZero Proxy entry in ~/.continue/config.json.

    Creates the config file if absent (Continue.dev will pick it up on next launch).
    Always returns True.
    """
    cfg = _load_config()
    models: list[dict[str, Any]] = cfg.get("models", [])

    entry = _make_entry(port, secret)
    idx = next((i for i, m in enumerate(models) if m.get("title") == _ENTRY_TITLE), -1)
    if idx >= 0:
        # Preserve apiKey the user may have already set — only update structural fields
        existing_key = models[idx].get("apiKey", entry["apiKey"])
        models[idx] = {**entry, "apiKey": existing_key}
    else:
        models.append(entry)

    cfg["models"] = models
    _save_config(cfg)
    return True
