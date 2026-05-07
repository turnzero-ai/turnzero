"""TurnZero source configuration — controls which block tiers are active."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

TIERS = ("local", "community", "team", "personal")

# Domains written to config on fresh install. Users can extend with `turnzero domain add`.
DEFAULT_ACTIVE_DOMAINS: list[str] = [
    "python",
    "typescript",
    "security",
    "rest-api",
    "docker",
    "fastapi",
    "nextjs",
    "postgresql",
]

_DEFAULTS: dict[str, Any] = {
    "sources": {
        "local": True,
        "community": True,
        "team": False,
        "personal": True,
    },
    "harvest_opt_in": False,
    # None = all domains active (backward compat). List = only those domains score.
    "active_domains": None,
}


def get_data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def get_blocks_dir() -> Path:
    return get_data_dir() / "blocks"


def get_index_path() -> Path:
    return get_data_dir() / "index.jsonl"


def get_affinity_path() -> Path:
    """Return the path to the project affinity storage."""
    return get_data_dir() / "affinity.json"


def get_session_injections_dir() -> Path:
    """Return the directory where transient session injections are tracked."""
    return get_data_dir() / "sessions"


def get_bundled_index_path() -> Path:
    """Return the pre-built index shipped inside the package (no setup needed)."""
    # Path(__file__) is turnzero/config.py
    # .parent is turnzero/
    pkg = Path(__file__).parent / "data" / "index.jsonl"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "index.jsonl"
    if repo.exists():
        return repo
    return get_index_path()


def get_bundled_blocks_dir() -> Path:
    """Return the blocks directory shipped inside the package (no setup needed)."""
    pkg = Path(__file__).parent / "data" / "blocks"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "blocks"
    if repo.exists():
        return repo
    return get_blocks_dir()


def load_config(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "config.yaml"
    if not path.exists():
        return {
            k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULTS.items()
        }
    raw = yaml.safe_load(path.read_text()) or {}
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULTS.items()}
    for k, v in raw.items():
        if k in result:
            if isinstance(result[k], dict) and isinstance(v, dict):
                result[k].update(v)
            else:
                result[k] = v
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


def get_active_domains(data_dir: Path) -> list[str] | None:
    """Return active domain whitelist, or None if all domains are active."""
    val = load_config(data_dir).get("active_domains")
    if isinstance(val, list):
        return val
    return None


def allow_mcp_auto_approve() -> bool:
    """Return True if the model is allowed to auto-approve candidates without user intent."""
    return os.environ.get("TURNZERO_ALLOW_MCP_AUTO_APPROVE", "false").lower() == "true"
