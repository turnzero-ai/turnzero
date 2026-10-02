"""Builders for Claude Code transcript fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_TS = "2026-09-15T10:{:02d}:{:02d}.000Z"


def _base(kind: str, second: int) -> dict[str, Any]:
    return {
        "type": kind,
        "isSidechain": False,
        "cwd": "/work/proj",
        "timestamp": _TS.format(second // 60, second % 60),
    }


def user(text: str, second: int = 0, **extra: Any) -> dict[str, Any]:
    """A turn the user typed."""
    return {
        **_base("user", second),
        "origin": {"kind": "human"},
        "message": {"role": "user", "content": text},
        **extra,
    }


def assistant(
    text: str = "Done.",
    second: int = 0,
    tool_uses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content = [{"type": "text", "text": text}, *(tool_uses or [])]
    return {
        **_base("assistant", second),
        "message": {"role": "assistant", "content": content},
    }


def suggest_call(tool_use_id: str, inject_all: bool = True) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": "mcp__turnzero__list_suggested_blocks",
        "input": {"prompt": "p", "inject_all": inject_all},
    }


def inject_call(block_id: str) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": f"inject-{block_id}",
        "name": "mcp__turnzero__inject_block",
        "input": {"block_id": block_id},
    }


def tool_result(
    tool_use_id: str, block_ids: list[str], second: int = 0
) -> dict[str, Any]:
    payload = json.dumps({"result": [{"block_id": b, "score": 0.9} for b in block_ids]})
    return {
        **_base("user", second),
        "toolUseResult": payload,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": payload}
            ],
        },
    }


def write_transcript(
    projects_dir: Path, name: str, entries: list[dict[str, Any]]
) -> Path:
    path = projects_dir / "proj" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def append_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    stamp = path.stat().st_mtime + 5
    os.utime(path, (stamp, stamp))
