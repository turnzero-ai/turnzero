"""Continue.dev config patcher — adds/updates TurnZero proxy model entry.

Continue v1.2+ uses config.yaml (schema v1) as primary config.
config.json is the legacy format (pre-v1.2) — we patch both for compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONTINUE_DIR = Path.home() / ".continue"
_CONFIG_YAML = _CONTINUE_DIR / "config.yaml"
_CONFIG_JSON = _CONTINUE_DIR / "config.json"
_ENTRY_TITLE = "TurnZero Proxy"
_ENTRY_NAME = "TurnZero Proxy"  # config.yaml uses 'name', config.json uses 'title'


def is_installed() -> bool:
    return _CONTINUE_DIR.exists()


# ---------------------------------------------------------------------------
# config.yaml (Continue v1.2+, schema v1) — primary
# ---------------------------------------------------------------------------


def _yaml_entry(port: int, secret: str) -> str:
    return (
        f"  - name: {_ENTRY_NAME}\n"
        f"    provider: openai\n"
        f"    model: gemini-2.5-flash\n"
        f"    apiBase: http://localhost:{port}/v1\n"
        f"    apiKey: YOUR_PROVIDER_KEY_HERE\n"
        f"    requestOptions:\n"
        f"      headers:\n"
        f"        X-TurnZero-Secret: {secret}\n"
    )


def _patch_yaml(port: int, secret: str) -> None:
    if not _CONFIG_YAML.exists():
        return

    text = _CONFIG_YAML.read_text(encoding="utf-8")

    # Remove existing TurnZero block if present (idempotent)
    lines = text.splitlines(keepends=True)
    filtered: list[str] = []
    skip = False
    for line in lines:
        if line.strip().startswith(f"- name: {_ENTRY_NAME}"):
            skip = True
        elif skip and (line.startswith("  - ") or not line.startswith(" ")):
            skip = False
        if not skip:
            filtered.append(line)
    text = "".join(filtered)

    # Ensure models: key exists
    if "models:" not in text:
        text = text.rstrip() + "\nmodels:\n"
    elif "models: []" in text:
        text = text.replace("models: []", "models:")

    text = text.rstrip() + "\n" + _yaml_entry(port, secret)
    _CONFIG_YAML.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# config.json (Continue pre-v1.2) — legacy fallback
# ---------------------------------------------------------------------------


def _json_entry(port: int, secret: str) -> dict[str, Any]:
    return {
        "title": _ENTRY_TITLE,
        "provider": "openai",
        "model": "gemini-2.5-flash",
        "apiBase": f"http://localhost:{port}/v1",
        "apiKey": "YOUR_PROVIDER_KEY_HERE",
        "requestOptions": {"headers": {"X-TurnZero-Secret": secret}},
    }


def _patch_json(port: int, secret: str) -> None:
    if not _CONFIG_JSON.exists():
        cfg: dict[str, Any] = {"models": []}
    else:
        raw = _CONFIG_JSON.read_text(encoding="utf-8")
        cfg = json.loads(raw) if raw.strip() else {}
        if "models" not in cfg:
            cfg["models"] = []

    models: list[dict[str, Any]] = cfg["models"]
    entry = _json_entry(port, secret)
    idx = next((i for i, m in enumerate(models) if m.get("title") == _ENTRY_TITLE), -1)
    if idx >= 0:
        existing_key = models[idx].get("apiKey", entry["apiKey"])
        models[idx] = {**entry, "apiKey": existing_key}
    else:
        models.append(entry)

    cfg["models"] = models
    _CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_JSON.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch(port: int, secret: str) -> bool:
    """Add/update TurnZero Proxy in both config.yaml (v1.2+) and config.json (legacy).

    Creates config files if absent. Always returns True.
    """
    _CONTINUE_DIR.mkdir(parents=True, exist_ok=True)
    _patch_yaml(port, secret)
    _patch_json(port, secret)
    return True
