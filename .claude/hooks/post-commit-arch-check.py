#!/usr/bin/env python3
"""PostToolUse hook — remind to sync docs after every git commit."""
from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if "git commit" not in cmd:
        sys.exit(0)

    reminder = (
        "POST-COMMIT DOC SYNC — check each item now, not at end of session:\n"
        "  [ ] internal/ARCHITECTURE.md — update 'Last verified' line + any changed sections\n"
        "  [ ] internal/PROJECT_STATE.md — mark ticket done, capture new debt\n"
        "  [ ] CLAUDE.md — version and test count still accurate?\n"
        "  [ ] BENCHMARK.md — was a benchmark run this session?\n"
        "  [ ] README.md / FAQ.md / ROADMAP.md — public-facing design or client list changed?\n"
        "  [ ] SECURITY.md — supported version table current?\n"
        "Skip items that genuinely do not apply. Do not skip silently."
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": reminder,
                }
            }
        )
    )


main()
