"""TurnZero source configuration — controls which block tiers are active."""

from __future__ import annotations

from pathlib import Path

import os
import yaml

TIERS = ("local", "community", "team")

_DEFAULTS: dict[str, dict[str, bool]] = {
    "sources": {
        "local": True,
        "community": True,
        "team": False,
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
