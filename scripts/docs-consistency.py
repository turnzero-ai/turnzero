#!/usr/bin/env python3
"""Docs consistency checker — runs as Tier 2 pre-push gate and in CI docs-guard.

Checks:
  1. pyproject.toml version == version in CLAUDE.md
  2. pyproject.toml version == version in SECURITY.md supported table
  3. ARCHITECTURE.md Last verified date is within 7 days of today

Exits 0 on PASS, exits 1 with clear message on any drift.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCH_AGE_DAYS = 7

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_pyproject_version() -> str:
    """Return version string from pyproject.toml."""
    text = _read(ROOT / "pyproject.toml")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("Could not parse version from pyproject.toml")
    return m.group(1)


def check_claude_md(expected: str) -> bool:
    text = _read(ROOT / "CLAUDE.md")
    m = re.search(r"TurnZero is at \*\*v([\d.]+)", text)
    if not m:
        print(f"  {FAIL} CLAUDE.md: version string not found")
        return False
    actual = m.group(1)
    if actual != expected:
        print(f"  {FAIL} CLAUDE.md: v{actual} != pyproject v{expected}")
        return False
    print(f"  {PASS} CLAUDE.md: v{actual}")
    return True


def check_security_md(expected: str) -> bool:
    text = _read(ROOT / "SECURITY.md")
    m = re.search(r">=\s*([\d.]+)", text)
    if not m:
        print(f"  {FAIL} SECURITY.md: supported version line not found")
        return False
    actual = m.group(1)
    if actual != expected:
        print(f"  {FAIL} SECURITY.md: >= {actual} != pyproject v{expected}")
        return False
    print(f"  {PASS} SECURITY.md: >= {actual}")
    return True


def check_architecture_freshness() -> bool:
    arch_path = ROOT / "internal" / "ARCHITECTURE.md"
    if not arch_path.exists():
        print(f"  {PASS} ARCHITECTURE.md: not found (skipping — internal file may not exist)")
        return True
    text = _read(arch_path)
    m = re.search(r"\*\*Last verified:\*\*.*?(\d{4}-\d{2}-\d{2})", text)
    if not m:
        print(f"  {FAIL} ARCHITECTURE.md: Last verified date not found")
        return False
    verified = date.fromisoformat(m.group(1))
    age = (date.today() - verified).days
    if age > MAX_ARCH_AGE_DAYS:
        print(
            f"  {FAIL} ARCHITECTURE.md: Last verified {verified} is {age} days ago "
            f"(max {MAX_ARCH_AGE_DAYS}). Update 'Last verified' line."
        )
        return False
    print(f"  {PASS} ARCHITECTURE.md: Last verified {verified} ({age}d ago)")
    return True


def main() -> None:
    print("docs-consistency: checking version and staleness...\n")
    version = check_pyproject_version()
    print(f"  pyproject.toml version: {version}\n")

    results = [
        check_claude_md(version),
        check_security_md(version),
        check_architecture_freshness(),
    ]

    print()
    if all(results):
        print(f"docs-consistency: {PASS} — all checks passed.")
        sys.exit(0)
    else:
        failed = results.count(False)
        print(f"docs-consistency: {FAIL} — {failed} check(s) failed. Fix before pushing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
