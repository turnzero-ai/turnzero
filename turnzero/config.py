"""TurnZero source configuration — controls which block tiers are active."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

TIERS = ("local", "community", "team", "personal")
TURNZERO_FEEDBACK_URL_ENV = "TURNZERO_FEEDBACK_URL"
TURNZERO_FEEDBACK_FORM_URL = "https://tally.so/r/REPLACE_WITH_TURNZERO_FORM_ID"

_DEFAULTS: dict[str, dict[str, bool]] = {
    "sources": {
        "local": True,
        "community": True,
        "team": False,
        "personal": True,
    }
}


def _data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def _blocks_dir() -> Path:
    return _data_dir() / "blocks"


def _index_path() -> Path:
    return _data_dir() / "index.jsonl"


def feedback_form_url() -> str:
    """Return the hosted feedback form URL, allowing an environment override."""
    return os.environ.get(TURNZERO_FEEDBACK_URL_ENV, "").strip() or (
        TURNZERO_FEEDBACK_FORM_URL
    )


def feedback_form_url_is_placeholder(url: str) -> bool:
    """Return True when the repository placeholder feedback URL is still active."""
    return url == TURNZERO_FEEDBACK_FORM_URL


def _affinity_path() -> Path:
    """Return the path to the project affinity storage."""
    return _data_dir() / "affinity.json"


def _session_injections_dir() -> Path:
    """Return the directory where transient session injections are tracked."""
    return _data_dir() / "sessions"


def _bundled_index_path() -> Path:
    """Return the pre-built index shipped inside the package (no setup needed)."""
    # Path(__file__) is turnzero/config.py
    # .parent is turnzero/
    pkg = Path(__file__).parent / "data" / "index.jsonl"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "index.jsonl"
    if repo.exists():
        return repo
    return _index_path()


def _bundled_blocks_dir() -> Path:
    """Return the blocks directory shipped inside the package (no setup needed)."""
    pkg = Path(__file__).parent / "data" / "blocks"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "blocks"
    if repo.exists():
        return repo
    return _blocks_dir()


def load_config(data_dir: Path) -> dict[str, dict[str, bool]]:
    path = data_dir / "config.yaml"
    if not path.exists():
        return {k: dict(v) for k, v in _DEFAULTS.items()}
    raw = yaml.safe_load(path.read_text()) or {}
    result = {k: dict(v) for k, v in _DEFAULTS.items()}
    if "sources" in raw:
        result["sources"].update(raw["sources"])
    return result


def save_config(data_dir: Path, config: dict[str, dict[str, bool]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=True)
    )


def enabled_sources(data_dir: Path) -> list[str]:
    """Return list of tier names that are currently enabled."""
    return [s for s, on in load_config(data_dir)["sources"].items() if on]


# ---------------------------------------------------------------------------
# Telemetry config — separate section, never touches sources config
# ---------------------------------------------------------------------------

_TELEMETRY_DEFAULTS: dict[str, object] = {
    "enabled": True,
    "anonymous_id": "",
}


def _telemetry_config_path(data_dir: Path) -> Path:
    return data_dir / "telemetry.yaml"


def load_telemetry_config(data_dir: Path) -> dict[str, object]:
    path = _telemetry_config_path(data_dir)
    if not path.exists():
        return dict(_TELEMETRY_DEFAULTS)
    raw = yaml.safe_load(path.read_text()) or {}
    result = dict(_TELEMETRY_DEFAULTS)
    result.update({k: v for k, v in raw.items() if k in _TELEMETRY_DEFAULTS})
    return result


def save_telemetry_config(data_dir: Path, config: dict[str, object]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _telemetry_config_path(data_dir).write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=True)
    )


def allow_mcp_auto_approve() -> bool:
    """Return True if the model is allowed to auto-approve candidates without user intent."""
    return os.environ.get("TURNZERO_ALLOW_MCP_AUTO_APPROVE", "false").lower() == "true"
