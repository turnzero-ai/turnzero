"""Candidate service — submission, auto-approval guard, and YAML persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from turnzero.blocks import compute_confidence
from turnzero.config import (
    allow_mcp_auto_approve,
    get_blocks_dir,
    get_data_dir,
    get_index_path,
)
from turnzero.repositories.index_repo import append_block, build
from turnzero.validators import safe_path, validate_domain, validate_slug

_AUTO_APPROVE_INTENT_KEYWORDS: set[str] = {
    "remember",
    "save",
    "note",
    "user asked",
    "explicit",
}


def is_intent_present(text: str, keywords: set[str], threshold: int = 2) -> bool:
    """Return True if any keyword appears in text with simple typo tolerance (edit distance ≤ threshold)."""
    _MIN_FUZZY_LEN = 4

    def _dist(s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return _dist(s2, s1)
        if not s2:
            return len(s1)
        prev: list[int] = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
            prev = curr
        return prev[-1]

    text_words = [w.strip(".,!?;:\"'").lower() for w in text.split()]
    for kw in keywords:
        kw_lower = kw.lower()
        for word in text_words:
            if word == kw_lower:
                return True
            if (
                len(kw_lower) >= _MIN_FUZZY_LEN
                and abs(len(word) - len(kw_lower)) <= threshold
                and _dist(word, kw_lower) <= threshold
            ):
                return True
    return False


def check_auto_approve_guard(auto_approve: bool, reason: str) -> tuple[bool, bool]:
    """Return (effective_auto_approve, was_blocked)."""
    if not auto_approve:
        return False, False
    if not allow_mcp_auto_approve():
        return False, True
    if not is_intent_present(reason, _AUTO_APPROVE_INTENT_KEYWORDS):
        return False, True
    return True, False


def submit(
    block_id: str,
    domain: str,
    intent: str,
    constraints: list[str],
    anti_patterns: list[str],
    tags: list[str] | None = None,
    doc_anchors: list[str] | None = None,
    rationale: str | None = None,
    reason: str = "",
    auto_approve: bool = False,
    is_personal: bool = False,
    project_root: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Persist a candidate block and return (message, input_snapshot) for logging."""
    validate_slug(block_id)
    validate_domain(domain)

    import datetime

    today = datetime.date.today().isoformat()
    confidence = compute_confidence(
        block_id, constraints, anti_patterns or [], tags or [], reason
    )
    auto_approve, guard_blocked = check_auto_approve_guard(auto_approve, reason)

    project_hash = None
    if is_personal and domain != "global" and project_root:
        from turnzero.state import _get_project_hash

        project_hash = _get_project_hash(Path(project_root))

    block: dict[str, Any] = {
        "id": block_id,
        "slug": block_id,
        "version": "1.0.0",
        "domain": domain,
        "intent": intent,
        "last_verified": today,
        "tags": tags or [],
        "context_weight": sum(
            len(c.split()) * 4 for c in constraints + (anti_patterns or [])
        ),
        "conflicts_with": [],
        "requires": [],
        "constraints": constraints,
        "anti_patterns": anti_patterns or [],
        "rationale": rationale,
        "doc_anchors": [{"url": u, "verified": today} for u in (doc_anchors or [])],
        "confidence": confidence,
        "archived": False,
        "project_hash": project_hash,
    }

    input_snapshot: dict[str, Any] = {
        "block_id": block_id,
        "domain": domain,
        "intent": intent,
        "constraints": constraints,
        "anti_patterns": anti_patterns or [],
        "tags": tags or [],
        "doc_anchors": doc_anchors or [],
        "rationale": rationale,
        "reason": reason,
        "auto_approve": auto_approve,
        "is_personal": is_personal,
        "project_root": project_root,
    }

    if auto_approve:
        tier = "personal" if is_personal else "local"
        dest_dir = safe_path(get_blocks_dir(), tier, domain)
        dest_dir.mkdir(parents=True, exist_ok=True)
        block_path = safe_path(dest_dir, f"{block_id}.yaml")
        with open(block_path, "w", encoding="utf-8") as f:
            yaml.dump(block, f, allow_unicode=True, sort_keys=False)

        if not get_index_path().exists():
            build(get_blocks_dir(), get_index_path(), data_dir=get_data_dir())
        else:
            append_block(block_path, tier, get_index_path(), get_data_dir())

        result = (
            f"✓ {'Personal' if is_personal else 'Expert'} Prior '{block_id}' added to "
            f"{tier} library and index updated incrementally. "
            f"It will be injected in future sessions matching this domain."
            + (f" Reason: {reason}" if reason else "")
        )
    else:
        candidates_dir = get_data_dir() / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = safe_path(candidates_dir, f"{block_id}.yaml")
        with open(candidate_path, "w", encoding="utf-8") as f:
            yaml.dump(block, f, allow_unicode=True, sort_keys=False)

        if guard_blocked:
            result = (
                f"⚠ Auto-approval blocked: explicit user intent (e.g., 'remember this') "
                f"was not found in the reason. Candidate '{block_id}' has been queued for "
                f"review instead. Run `turnzero review` to approve it."
            )
        else:
            result = (
                f"✓ Candidate '{block_id}' queued for review. "
                f"Run `turnzero review` to approve it into the library."
                + (f" Reason: {reason}" if reason else "")
            )

    return result, input_snapshot
