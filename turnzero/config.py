"""TurnZero source configuration — controls which block tiers are active."""

from __future__ import annotations

from pathlib import Path

import yaml

TIERS = ("local", "community", "team")

_DEFAULTS: dict[str, dict[str, bool]] = {
    "sources": {
        "local": True,
        "community": True,
        "team": False,
    }
}


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
