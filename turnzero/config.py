"""TurnZero source configuration — controls which block tiers are active."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

_TELEMETRY_DEFAULTS: dict[str, object] = {
    "enabled": True,
    "anonymous_id": "",
}


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


class ConfigManager:
    """Unified interface for any config section stored as a YAML file.

    Usage:
        mgr = ConfigManager("config", data_dir, defaults=_DEFAULTS)
        cfg = mgr.load()
        mgr.save(cfg)
    """

    def __init__(
        self,
        filename: str,
        data_dir: Path,
        defaults: dict[str, Any],
    ) -> None:
        self._path = data_dir / f"{filename}.yaml"
        self._defaults = defaults

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return _deep_merge(self._defaults, {})
        raw: dict[str, Any] = yaml.safe_load(self._path.read_text()) or {}
        return _deep_merge(self._defaults, raw)

    def save(self, config: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=True)
        )


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into a copy of base, recursively for nested dicts."""
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in override.items():
        if k in result:
            if isinstance(result[k], dict) and isinstance(v, dict):
                result[k].update(v)
            else:
                result[k] = v
    return result


def get_data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def get_telemetry_dir() -> Path:
    """Always ~/.turnzero/ — never the TURNZERO_DATA_DIR override.

    TURNZERO_DATA_DIR redirects block/index paths for dev workflows.
    Telemetry anonymous_id must follow the user, not the data dir, so
    dev and prod sessions appear under the same PostHog identity.
    """
    return Path.home() / ".turnzero"


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
    return ConfigManager("config", data_dir, _DEFAULTS).load()


def save_config(data_dir: Path, config: dict[str, dict[str, bool]]) -> None:
    ConfigManager("config", data_dir, _DEFAULTS).save(config)


def enabled_sources(data_dir: Path) -> list[str]:
    """Return list of tier names that are currently enabled."""
    return [s for s, on in load_config(data_dir)["sources"].items() if on]


def load_telemetry_config(data_dir: Path) -> dict[str, object]:
    return ConfigManager("telemetry", data_dir, _TELEMETRY_DEFAULTS).load()


def save_telemetry_config(data_dir: Path, config: dict[str, object]) -> None:
    ConfigManager("telemetry", data_dir, _TELEMETRY_DEFAULTS).save(config)


def get_active_domains(data_dir: Path) -> list[str] | None:
    """Return active domain whitelist, or None if all domains are active."""
    val = load_config(data_dir).get("active_domains")
    if isinstance(val, list):
        return val
    return None


def allow_mcp_auto_approve() -> bool:
    """Return True if the model is allowed to auto-approve candidates without user intent."""
    return os.environ.get("TURNZERO_ALLOW_MCP_AUTO_APPROVE", "false").lower() == "true"
