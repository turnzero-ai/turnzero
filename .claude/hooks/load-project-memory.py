#!/usr/bin/env python3
"""SessionStart hook — inject full TurnZero project memory into context."""
import glob
import json
import os
from contextlib import suppress

mem_dir = os.path.expanduser(
    "~/.claude/projects/-Users-darijomilicevic-Development-TurnZero/memory/"
)

files = sorted(
    f for f in glob.glob(os.path.join(mem_dir, "*.md"))
    if not f.endswith("MEMORY.md")
)

parts = []
for path in files:
    with suppress(OSError), open(path) as file:
        parts.append(file.read().strip())

if not parts:
    raise SystemExit(0)

context = (
    "## TurnZero project memory (auto-loaded at session start)\n\n"
    + "\n\n---\n\n".join(parts)
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }
}))
