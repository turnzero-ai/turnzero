"""Runtime state management for sessions and project affinity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from turnzero.config import _affinity_path, _session_injections_dir


def _get_project_hash(project_root: Path) -> str:
    """Return a stable hash for a project path."""
    return hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:16]


def get_session_injections(session_id: str) -> set[str]:
    """Return the set of block IDs already injected in this session."""
    if not session_id:
        return set()

    path = _session_injections_dir() / f"{session_id}_injections.json"
    if not path.exists():
        return set()

    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def record_session_injection(session_id: str, block_id: str) -> None:
    """Record that a block was injected in a session."""
    if not session_id:
        return

    dir_path = _session_injections_dir()
    dir_path.mkdir(parents=True, exist_ok=True)

    path = dir_path / f"{session_id}_injections.json"
    injections = get_session_injections(session_id)
    injections.add(block_id)

    path.write_text(json.dumps(list(injections)), encoding="utf-8")


def clear_session_injections(session_id: str) -> None:
    """Delete the injection history for a session."""
    path = _session_injections_dir() / f"{session_id}_injections.json"
    if path.exists():
        path.unlink()


def get_project_affinity(project_root: Path) -> dict[str, int]:
    """Return the block affinity mapping for a project."""
    path = _affinity_path()
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        project_hash = _get_project_hash(project_root)
        return dict(data.get(project_hash, {}))
    except (OSError, json.JSONDecodeError):
        return {}


def record_project_affinity(project_root: Path, block_id: str) -> None:
    """Increment the affinity count for a block in a project."""
    path = _affinity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    project_hash = _get_project_hash(project_root)

    from contextlib import suppress

    data: dict[str, dict[str, int]] = {}
    if path.exists():
        with suppress(OSError, json.JSONDecodeError):
            data = json.loads(path.read_text(encoding="utf-8"))

    project_data = data.setdefault(project_hash, {})
    project_data[block_id] = project_data.get(block_id, 0) + 1

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
