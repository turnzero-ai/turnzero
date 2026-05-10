#!/usr/bin/env python3
"""SessionStart hook — inject TurnZero project memory and maintainer workflow into context."""
from __future__ import annotations

import glob
import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path


def get_project_root() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()


def get_mem_dir(project_root: str) -> str:
    project_slug = project_root.replace("/", "-")
    return os.path.expanduser(f"~/.claude/projects/{project_slug}/memory/")


def main() -> None:
    try:
        project_root = get_project_root()
    except subprocess.CalledProcessError:
        raise SystemExit(0)

    mem_dir = get_mem_dir(project_root)
    parts: list[str] = []

    # Load Claude project memory files
    mem_files = sorted(
        f for f in glob.glob(os.path.join(mem_dir, "*.md"))
        if not f.endswith("MEMORY.md")
    )
    for path in mem_files:
        with suppress(OSError), open(path) as fh:
            parts.append(fh.read().strip())

    # Load maintainer workflow (gitignored, only present for maintainers)
    workflow_path = Path(project_root) / "internal" / "WORKFLOW.md"
    with suppress(OSError), open(workflow_path) as fh:
        parts.append(fh.read().strip())

    if not parts:
        raise SystemExit(0)

    context = (
        "## TurnZero project memory (auto-loaded at session start)\n\n"
        + "\n\n---\n\n".join(parts)
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )


main()
