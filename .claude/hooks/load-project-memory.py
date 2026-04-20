#!/usr/bin/env python3
"""SessionStart hook — inject full TurnZero project memory into context."""
import glob
import json
import os

mem_dir = os.path.expanduser(
    "~/.claude/projects/-Users-darijomilicevic-Development-TurnZero/memory/"
)

files = sorted(
    f for f in glob.glob(os.path.join(mem_dir, "*.md"))
    if not f.endswith("MEMORY.md")
)

parts = []
for path in files:
    try:
        parts.append(open(path).read().strip())
    except OSError:
        pass

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
