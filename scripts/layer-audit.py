#!/usr/bin/env python3
"""Layer boundary auditor — runs as Tier 2 pre-push gate and in CI.

Validates the enforced DDD layer contract for the turnzero package.

Exits 0 on PASS or WARN-only. Exits 1 if any non-whitelisted (CRITICAL) violations found.
To acknowledge a known violation: add it to KNOWN_VIOLATIONS with a reason.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "turnzero"

PASS   = "\033[32mPASS\033[0m"
WARN   = "\033[33mWARN\033[0m"
FAIL   = "\033[31mFAIL\033[0m"


@dataclass
class Rule:
    description: str
    source_glob: str
    forbidden_prefixes: list[str]


@dataclass
class KnownViolation:
    """Explicitly whitelisted violation — shown as WARN, does not block push."""
    file_suffix: str       # e.g. "cli/review.py"
    import_prefix: str     # e.g. "turnzero.repositories"
    reason: str


# ---------------------------------------------------------------------------
# Layer rules
# ---------------------------------------------------------------------------

RULES: list[Rule] = [
    Rule(
        description="CLI layer must not bypass services to call repositories directly",
        source_glob="cli/*.py",
        forbidden_prefixes=["turnzero.repositories"],
    ),
    Rule(
        description="MCP server must not import CLI layer",
        source_glob="mcp_server.py",
        forbidden_prefixes=["turnzero.cli"],
    ),
    Rule(
        description="Domain model (blocks.py) must not import infrastructure",
        source_glob="blocks.py",
        forbidden_prefixes=["turnzero.services", "turnzero.config", "turnzero.embed", "turnzero.repositories"],
    ),
    Rule(
        description="Domain model (analytics.py) must not import infrastructure",
        source_glob="analytics.py",
        forbidden_prefixes=["turnzero.services", "turnzero.config", "turnzero.embed", "turnzero.repositories"],
    ),
]

# ---------------------------------------------------------------------------
# Acknowledged debt — WARN not FAIL. Fix before next MINOR release.
# ---------------------------------------------------------------------------

KNOWN_VIOLATIONS: list[KnownViolation] = [
    KnownViolation(
        file_suffix="analytics.py",
        import_prefix="turnzero.services",
        reason="Backwards-compat shim in get_global_roi() — deferred import, documented debt. "
               "Fix: remove shim, migrate callers to stats_svc.get_global_roi() directly.",
    ),
    KnownViolation(
        file_suffix="cli/review.py",
        import_prefix="turnzero.repositories",
        reason="CLI imports block_repo.update_fields directly. "
               "Fix: expose update_fields via retrieval_svc or a new service method.",
    ),
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    file: Path
    line: int
    import_name: str
    rule: Rule
    known: bool = False
    known_reason: str = ""


def _is_known(file: Path, import_name: str) -> tuple[bool, str]:
    rel = str(file.relative_to(PKG))
    for kv in KNOWN_VIOLATIONS:
        if rel.endswith(kv.file_suffix) and (
            import_name == kv.import_prefix or import_name.startswith(kv.import_prefix + ".")
        ):
            return True, kv.reason
    return False, ""


def _collect_imports(source: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.lineno, node.module))
    return result


def audit() -> list[Violation]:
    violations: list[Violation] = []
    for rule in RULES:
        for path in PKG.glob(rule.source_glob):
            source = path.read_text(encoding="utf-8")
            for lineno, module in _collect_imports(source):
                for prefix in rule.forbidden_prefixes:
                    if module == prefix or module.startswith(prefix + "."):
                        is_known, reason = _is_known(path, module)
                        violations.append(Violation(
                            file=path,
                            line=lineno,
                            import_name=module,
                            rule=rule,
                            known=is_known,
                            known_reason=reason,
                        ))
    return violations


def main() -> None:
    print("layer-audit: checking DDD layer boundaries...\n")
    violations = audit()

    critical = [v for v in violations if not v.known]
    warned   = [v for v in violations if v.known]

    for v in warned:
        rel = v.file.relative_to(ROOT)
        print(f"  {WARN} {rel}:{v.line} — '{v.import_name}' (acknowledged debt)")
        print(f"         {v.known_reason}\n")

    for v in critical:
        rel = v.file.relative_to(ROOT)
        print(f"  {FAIL} {rel}:{v.line} — '{v.import_name}'")
        print(f"         Rule: {v.rule.description}\n")

    print()
    if critical:
        print(f"layer-audit: {FAIL} — {len(critical)} new violation(s). Fix before pushing.")
        sys.exit(1)
    elif warned:
        print(f"layer-audit: {WARN} — {len(warned)} known violation(s) (acknowledged debt). Push allowed.")
        sys.exit(0)
    else:
        print(f"layer-audit: {PASS} — no violations.")
        sys.exit(0)


if __name__ == "__main__":
    main()
