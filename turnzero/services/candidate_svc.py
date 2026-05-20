"""Candidate service — submission, auto-approval guard, and YAML persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from turnzero.safety import validate_candidate
from turnzero.validators import safe_path, validate_domain, validate_slug


class AutoApprovePolicy:
    """Owns the auto-approval guard logic — intent detection and env flag check."""

    INTENT_KEYWORDS: frozenset[str] = frozenset({
        "remember", "save", "note", "user asked", "explicit",
    })
    _MIN_FUZZY_LEN = 4
    _FUZZY_RATIO = 0.75
    _FUZZY_THRESHOLD = 2

    @classmethod
    def intent_present(cls, text: str) -> bool:
        """Return True if any approval keyword appears in text with typo tolerance."""
        from difflib import SequenceMatcher

        text_words = [w.strip(".,!?;:\"'").lower() for w in text.split()]
        for kw in cls.INTENT_KEYWORDS:
            kw_lower = kw.lower()
            for word in text_words:
                if word == kw_lower:
                    return True
                if (
                    len(kw_lower) >= cls._MIN_FUZZY_LEN
                    and abs(len(word) - len(kw_lower)) <= cls._FUZZY_THRESHOLD
                    and SequenceMatcher(None, word, kw_lower).ratio() >= cls._FUZZY_RATIO
                ):
                    return True
        return False

    @classmethod
    def evaluate(cls, auto_approve: bool, reason: str) -> tuple[bool, bool]:
        """Return (effective_auto_approve, was_blocked)."""
        if not auto_approve:
            return False, False
        if not allow_mcp_auto_approve():
            return False, True
        if not cls.intent_present(reason):
            return False, True
        return True, False


# Module-level shims for callers that use the old function API
def is_intent_present(text: str, keywords: set[str], threshold: int = 2) -> bool:
    """Thin wrapper around AutoApprovePolicy.intent_present for backwards compat."""
    return AutoApprovePolicy.intent_present(text)


def check_auto_approve_guard(auto_approve: bool, reason: str) -> tuple[bool, bool]:
    """Thin wrapper around AutoApprovePolicy.evaluate for backwards compat."""
    return AutoApprovePolicy.evaluate(auto_approve, reason)


@dataclass
class BlockSubmission:
    """All fields required to construct and persist a candidate block."""

    block_id: str
    domain: str
    intent: str
    constraints: list[str]
    anti_patterns: list[str]
    tags: list[str] = field(default_factory=list)
    doc_anchors: list[str] = field(default_factory=list)
    rationale: str | None = None
    confidence: float = 0.5
    today: str = ""
    project_hash: str | None = None


def _build_block_dict(sub: BlockSubmission) -> dict[str, Any]:
    """Construct the canonical block dict from a BlockSubmission. Pure data, no I/O."""
    return {
        "id": sub.block_id,
        "slug": sub.block_id,
        "version": "1.0.0",
        "domain": sub.domain,
        "intent": sub.intent,
        "last_verified": sub.today,
        "tags": sub.tags,
        "context_weight": sum(len(c.split()) * 4 for c in sub.constraints + sub.anti_patterns),
        "conflicts_with": [],
        "requires": [],
        "constraints": sub.constraints,
        "anti_patterns": sub.anti_patterns,
        "rationale": sub.rationale,
        "doc_anchors": [{"url": u, "verified": sub.today} for u in sub.doc_anchors],
        "confidence": sub.confidence,
        "archived": False,
        "project_hash": sub.project_hash,
    }


def _persist_approved(
    block: dict[str, Any],
    block_id: str,
    is_personal: bool,
    domain: str,
    reason: str,
) -> str:
    """Write approved block to the library, update index, return confirmation message."""
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

    return (
        f"✓ {'Personal' if is_personal else 'Expert'} Prior '{block_id}' added to "
        f"{tier} library and index updated incrementally. "
        f"It will be injected in future sessions matching this domain."
        + (f" Reason: {reason}" if reason else "")
    )


def _persist_candidate(
    block: dict[str, Any],
    block_id: str,
    guard_blocked: bool,
    reason: str,
) -> str:
    """Write block to candidates queue, return status message with nudge if new."""
    candidates_dir = get_data_dir() / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = safe_path(candidates_dir, f"{block_id}.yaml")
    is_new = not candidate_path.exists()
    with open(candidate_path, "w", encoding="utf-8") as f:
        yaml.dump(block, f, allow_unicode=True, sort_keys=False)

    if guard_blocked:
        return (
            f"⚠ Auto-approval blocked: explicit user intent (e.g., 'remember this') "
            f"was not found in the reason. Candidate '{block_id}' has been queued for "
            f"review instead. Run `turnzero review` to approve it."
        )
    if is_new:
        return (
            f"💡 Correction captured — '{block_id}' queued for review. "
            f"Run `turnzero review` to approve and add to your library. "
            f"It will prevent this mistake in future sessions."
            + (f" Reason: {reason}" if reason else "")
        )
    return (
        f"✓ Candidate '{block_id}' updated in review queue. "
        f"Run `turnzero review` to approve it into the library."
        + (f" Reason: {reason}" if reason else "")
    )


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
    import datetime

    validate_slug(block_id)
    validate_domain(domain)

    safety = validate_candidate(constraints, anti_patterns or [], rationale, reason)
    if not safety.safe:
        today = datetime.date.today().isoformat()
        quarantine_dir = get_data_dir() / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantine_path = safe_path(quarantine_dir, f"{block_id}.yaml")
        with open(quarantine_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "slug": block_id,
                    "quarantine_reason": safety.reason_code,
                    "quarantine_detail": safety.detail,
                    "domain": domain,
                    "intent": intent,
                    "constraints": constraints,
                    "anti_patterns": anti_patterns or [],
                    "submitted_at": today,
                },
                f, allow_unicode=True, sort_keys=False,
            )
        from turnzero.telemetry import track_candidate_submitted
        track_candidate_submitted(domain=domain, auto_approved=False, result="quarantine")
        return (
            f"⚠ Candidate '{block_id}' was quarantined (reason: {safety.reason_code}). "
            f"{safety.detail} It will NOT be injected into any session."
        ), {
            "block_id": block_id, "domain": domain, "intent": intent,
            "constraints": constraints, "anti_patterns": anti_patterns or [],
            "reason": reason, "quarantine_reason": safety.reason_code,
        }

    today = datetime.date.today().isoformat()
    confidence = compute_confidence(
        block_id, constraints, anti_patterns or [], tags or [], reason
    )
    auto_approve, guard_blocked = AutoApprovePolicy.evaluate(auto_approve, reason)

    project_hash = None
    if is_personal and domain != "global" and project_root:
        from turnzero.session import _get_project_hash
        project_hash = _get_project_hash(Path(project_root))

    block = _build_block_dict(BlockSubmission(
        block_id=block_id,
        domain=domain,
        intent=intent,
        constraints=constraints,
        anti_patterns=anti_patterns or [],
        tags=tags or [],
        doc_anchors=doc_anchors or [],
        rationale=rationale,
        confidence=confidence,
        today=today,
        project_hash=project_hash,
    ))
    input_snapshot: dict[str, Any] = {
        "block_id": block_id, "domain": domain, "intent": intent,
        "constraints": constraints, "anti_patterns": anti_patterns or [],
        "tags": tags or [], "doc_anchors": doc_anchors or [],
        "rationale": rationale, "reason": reason,
        "auto_approve": auto_approve, "is_personal": is_personal,
        "project_root": project_root,
    }

    result = (
        _persist_approved(block, block_id, is_personal, domain, reason)
        if auto_approve
        else _persist_candidate(block, block_id, guard_blocked, reason)
    )
    from turnzero.telemetry import track_candidate_submitted
    track_candidate_submitted(
        domain=domain,
        auto_approved=auto_approve,
        result="approved" if auto_approve else "candidate",
    )
    return result, input_snapshot
