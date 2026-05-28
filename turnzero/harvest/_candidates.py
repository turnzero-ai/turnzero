"""Candidate validation, YAML parsing, normalisation, writing, and harvest pipeline."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from turnzero.blocks import compute_confidence
from turnzero.types import Intent

MIN_CONTEXT_WEIGHT = 50

_BLOCK_TOP_KEYS = frozenset(
    {
        "id",
        "version",
        "domain",
        "intent",
        "last_verified",
        "tags",
        "context_weight",
        "conflicts_with",
        "requires",
        "constraints",
        "anti_patterns",
        "doc_anchors",
        "slug",
        "title",
        "description",
    }
)


def validate_candidate(candidate: dict[str, Any]) -> str | None:
    """Return an error string if the candidate is junk, else None.

    Checks:
    - No placeholder text (<...>) in constraints or anti_patterns
    - context_weight >= MIN_CONTEXT_WEIGHT (anything lower is effectively empty)
    - No empty or placeholder URLs in doc_anchors
    """
    for field in ("constraints", "anti_patterns"):
        for item in candidate.get(field, []):
            if "<" in str(item) and ">" in str(item):
                return f"placeholder text in {field}: {str(item)[:60]}"

    if candidate.get("anti_patterns") and not candidate.get("rationale"):
        return "missing rationale (required when anti_patterns are present)"

    if int(candidate.get("context_weight", 0)) < MIN_CONTEXT_WEIGHT:
        return f"context_weight too low ({candidate.get('context_weight')})"

    for anchor in candidate.get("doc_anchors", []):
        url = str(anchor.get("url", "")).strip()
        if not url or url in ("", "https://example.com", "https://promptgraph.io"):
            return f"invalid doc_anchor url: '{url}'"

    return None


def _strip_prose(text: str) -> str:
    """Drop any prose lines before the first YAML content line."""
    for i, line in enumerate(text.splitlines()):
        if line.startswith("---") or line.startswith("- "):
            return "\n".join(text.splitlines()[i:])
    return text


def _fix_key_indentation(text: str) -> str:
    """Fix LLM indentation bug where anti_patterns/doc_anchors end up nested
    under the last constraints list item instead of being siblings.

    Detects base indentation from constraints: then re-indents any top-level
    block keys that are wrongly over-indented.
    """
    lines = text.splitlines()

    # Detect base indent from constraints: (present in both list and mapping fmt)
    base_indent = 0
    for line in lines:
        m = re.match(r"^(\s*)constraints\s*:", line)
        if m:
            base_indent = len(m.group(1))
            break

    result = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped[0] in ("-", "#"):
            result.append(line)
            continue
        key = stripped.split(":")[0].strip()
        current_indent = len(line) - len(stripped)
        if key in _BLOCK_TOP_KEYS and current_indent != base_indent:
            result.append(" " * base_indent + stripped)
        else:
            result.append(line)
    return "\n".join(result)


def _compute_context_weight(candidate: dict[str, Any]) -> int:
    """Estimate token count from actual content (4 tokens/word)."""
    text = " ".join(
        str(s)
        for s in candidate.get("constraints", []) + candidate.get("anti_patterns", [])
    )
    return max(50, len(text.split()) * 4)


def _normalise(candidate: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults and ensure required fields exist."""
    candidate.setdefault("version", "1.0.0")
    from datetime import date

    candidate.setdefault("last_verified", date.today().isoformat())
    candidate.setdefault("verification_level", "observed")
    candidate.setdefault("tags", [])
    candidate.setdefault("conflicts_with", [])
    candidate.setdefault("requires", [])
    candidate.setdefault("constraints", [])
    candidate.setdefault("anti_patterns", [])
    candidate.setdefault("doc_anchors", [])
    candidate.setdefault("archived", False)

    # Always recompute weight — don't trust the LLM's estimate
    candidate["context_weight"] = _compute_context_weight(candidate)

    # Compute confidence for harvested block
    candidate["confidence"] = compute_confidence(
        slug=candidate.get("id", ""),
        constraints=candidate["constraints"],
        anti_patterns=candidate["anti_patterns"],
        tags=candidate["tags"],
        reason="Harvested from session transcript",
    )

    # Ensure intent is valid
    valid_intents = set(Intent)
    if candidate.get("intent") not in valid_intents:
        candidate["intent"] = Intent.BUILD

    # Generate ID if missing or placeholder
    if not candidate.get("id") or candidate["id"] == "<descriptive-slug>-<intent>":
        domain = str(candidate.get("domain", candidate.get("stack", "unknown")))
        intent = str(candidate.get("intent", Intent.BUILD))
        candidate["id"] = f"{domain}-{intent}-extracted"

    return candidate


def parse_candidates(raw_yaml: str) -> list[dict[str, Any]]:
    """Parse LLM output into a list of block candidate dicts.

    Handles LLM quirks: markdown fences, extra prose, partial YAML,
    and multi-document YAML (--- separators between blocks).

    Each --- section is parsed independently so one malformed block
    does not discard the rest.
    """
    cleaned = re.sub(r"```(?:yaml)?\n?", "", raw_yaml).strip()
    cleaned = _strip_prose(cleaned)
    cleaned = _fix_key_indentation(cleaned)

    # Split on --- and parse each chunk independently
    chunks = re.split(r"\n?---\n?", cleaned)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for chunk in chunks:
        stripped_chunk = chunk.strip()
        if not stripped_chunk:
            continue
        try:
            doc = yaml.safe_load(stripped_chunk)
        except yaml.YAMLError:
            errors.append(chunk[:60])
            continue
        if isinstance(doc, dict):
            results.append(_normalise(doc))
        elif isinstance(doc, list):
            results.extend(_normalise(c) for c in doc if isinstance(c, dict))

    if not results and errors:
        raise ValueError(
            f"Could not parse LLM output as YAML "
            f"({len(errors)} chunk(s) failed).\n\nRaw output:\n{raw_yaml}"
        )

    return results


def content_hash(candidate: dict[str, Any]) -> str:
    """First 16 hex chars of SHA-256 of canonical YAML content."""
    payload = {k: v for k, v in candidate.items() if k != "id"}
    canonical = yaml.dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def write_candidate(candidate: dict[str, Any], blocks_dir: Path) -> Path:
    """Write a candidate dict to a YAML file in blocks_dir. Returns the path."""
    block_id = str(candidate["id"])
    path = blocks_dir / f"{block_id}.yaml"
    path.write_text(
        yaml.dump(
            candidate, sort_keys=False, allow_unicode=True, default_flow_style=False
        ),
        encoding="utf-8",
    )
    return path


def harvest(
    conversation_path: Path,
    blocks_dir: Path,
    model: str = "llama3.2",
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Full harvest pipeline: load → extract → parse → return candidates.

    If dry_run=False and the caller approves, write blocks via write_candidate().
    Returns list of parsed candidate dicts.
    """
    from turnzero.harvest._extraction import extract_with_llm
    from turnzero.harvest._parsers import load_conversation

    conversation = load_conversation(conversation_path)
    raw = extract_with_llm(conversation, model=model)
    candidates = parse_candidates(raw)
    return candidates
