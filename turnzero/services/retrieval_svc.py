"""Retrieval service — block loading, index caching, suggestion, and injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from turnzero.blocks import Block
from turnzero.config import (
    enabled_sources,
    get_active_domains,
    get_blocks_dir,
    get_bundled_blocks_dir,
    get_bundled_index_path,
    get_data_dir,
    get_index_path,
)
from turnzero.formatters import block_fmt
from turnzero.repositories.block_repo import load_all_blocks
from turnzero.repositories.index_repo import IndexEntry, load_index
from turnzero.retrieval import query as _query
from turnzero.state import (
    clear_session_injections,
    get_session_injections,
    record_project_affinity,
    record_session_injection,
)
from turnzero.telemetry import (
    track_block_injected,
    track_session_start,
    track_session_summary,
)

# Per-source index cache: path → (mtime, entries)
_INDEX_CACHE: dict[Path, tuple[float, list[IndexEntry]]] = {}

# Blocks cache: (blocks_dir, tuple(sources)) → (mtime, blocks_dict)
_BLOCKS_CACHE: dict[tuple[Path, tuple[str, ...]], tuple[float, dict[str, Block]]] = {}


def _active_sources() -> list[str]:
    return enabled_sources(get_data_dir())


def _get_blocks_mtime(blocks_dir: Path, sources: list[str]) -> float:
    """Calculate the max mtime of all *.yaml files within enabled source tiers."""
    max_mtime = 0.0
    for tier in sources:
        tier_dir = blocks_dir / tier
        if tier_dir.exists():
            for path in tier_dir.rglob("*.yaml"):
                try:
                    max_mtime = max(max_mtime, path.stat().st_mtime)
                except FileNotFoundError:
                    continue
    return max_mtime


def _load_active_blocks() -> dict[str, Block]:
    blocks_dir = get_blocks_dir()
    if not blocks_dir.exists():
        blocks_dir = get_bundled_blocks_dir()
    sources = _active_sources()
    sources_tuple = tuple(sorted(sources))
    cache_key = (blocks_dir, sources_tuple)

    mtime = _get_blocks_mtime(blocks_dir, sources)
    cached = _BLOCKS_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]

    blocks = load_all_blocks(blocks_dir, sources=sources)
    _BLOCKS_CACHE[cache_key] = (mtime, blocks)
    return blocks


def _load_source_index(source: str) -> list[IndexEntry]:
    """Load index for one source tier with mtime-based cache."""
    data_dir = get_data_dir()
    per_source_path = data_dir / f"index_{source}.jsonl"
    path = per_source_path if per_source_path.exists() else get_index_path()
    if not path.exists():
        path = get_bundled_index_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return []
    cached = _INDEX_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    entries = load_index(path, sources=[source] if path == get_index_path() else None)
    _INDEX_CACHE[path] = (mtime, entries)
    return entries


def _load_active_index() -> list[IndexEntry]:
    result: list[IndexEntry] = []
    for source in _active_sources():
        result.extend(_load_source_index(source))
    return result


def list_suggested_blocks(
    prompt: str,
    top_k: int = 5,
    threshold: float = 0.70,
    context_weight: int = 5000,
    strict_intent: bool = True,
    project_root: Path | None = None,
    session_id: str | None = None,
    inject_all: bool = False,
) -> list[dict[str, Any]]:
    """Return ranked block suggestions for prompt as serialisable dicts."""
    from turnzero.retrieval import get_identity_context
    from turnzero.services import stats_svc

    blocks = _load_active_blocks()

    # Apply domain whitelist: personal tier always passes, others filtered when set.
    active_domains = get_active_domains(get_data_dir())
    if active_domains is not None:
        active_set = set(active_domains)
        blocks = {
            k: v for k, v in blocks.items()
            if v.tier == "personal" or v.domain in active_set
        }

    index = _load_active_index()
    exclude_ids = get_session_injections(session_id) if session_id else set()

    # WF-2: skip personal priors on Turn N — they were already injected this session.
    # Turn 0 = no injections recorded yet; Turn N = at least one injection exists.
    is_turn_0 = not exclude_ids
    if is_turn_0:
        personal_results, limit_exceeded = get_identity_context(
            blocks, project_root=project_root, exclude_ids=exclude_ids
        )
    else:
        personal_results, limit_exceeded = [], False

    personal_weight = sum(b.context_weight for b, _ in personal_results)

    expert_results = _query(
        prompt,
        index,
        blocks,
        top_k=top_k,
        threshold=threshold,
        context_weight=context_weight - personal_weight,
        strict_intent=strict_intent,
        project_root=project_root,
        exclude_block_ids=exclude_ids | {b.slug for b, _ in personal_results},
    )

    turn = "first" if is_turn_0 else "subsequent"

    _PREVIEW_WORDS = 6

    def _expert_preview(block: Any) -> str:
        text = block.constraints[0] if block.constraints else ""
        words = text.split()
        return " ".join(words[:_PREVIEW_WORDS]) + (
            "…" if len(words) > _PREVIEW_WORDS else ""
        )

    def _build_entry(block: Block, score: float, is_personal: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "block_id": block.slug,
            "score": round(score, 3),
            "domain": block.domain,
            "intent": block.intent,
            "tags": block.tags,
            "context_weight": block.context_weight,
            "stale": block.is_stale(),
            "turn": turn,
            "preview": (
                "[personal prior — call inject_block to read]"
                if is_personal
                else _expert_preview(block)
            ),
        }
        # WF-3: inline full text and record injection when inject_all=True
        if inject_all:
            entry["full_text"] = block_fmt.to_injection_text(block)
            if session_id:
                record_session_injection(session_id, block.slug)
            if project_root:
                record_project_affinity(project_root, block.slug)
            track_block_injected(domain=block.domain, tier=block.tier or "local")
        return entry

    formatted: list[dict[str, Any]] = [
        _build_entry(block, score, is_personal=True)
        for block, score in personal_results
    ] + [
        _build_entry(block, score, is_personal=False) for block, score in expert_results
    ]

    if limit_exceeded:
        formatted.append(
            {
                "block_id": "personal-priors-limit-warning",
                "score": 0.0,
                "domain": "system",
                "intent": "review",
                "tags": ["warning"],
                "context_weight": 0,
                "stale": False,
                "turn": turn,
                "preview": "⚠ Personal Priors budget exceeded (2500 tokens). Some rules omitted.",
            }
        )

    # Logging and telemetry
    real_blocks = [
        s for s in formatted if s["block_id"] != "personal-priors-limit-warning"
    ]
    if formatted:
        stats_svc.log_injection(
            block_ids=[s["block_id"] for s in real_blocks],
            domains=list({s["domain"] for s in real_blocks if s.get("domain")}),
            prompt_words=len(prompt.split()),
            session_id=session_id,
            tokens_injected=sum(s.get("context_weight", 0) for s in real_blocks),
        )

    personal_count = sum(1 for b in blocks.values() if b.tier == "personal")
    track_session_start(
        session_id=session_id,
        blocks_suggested=len(formatted),
        domains=list({s["domain"] for s in formatted if s.get("domain")}),
        has_personal_priors=len(personal_results) > 0,
        personal_block_count=personal_count,
        total_block_count=len(blocks),
    )

    return formatted


def _check_domain_active(block: Block, block_id: str) -> bool:
    """Return True if block's domain is in the active whitelist (or no whitelist set)."""
    active = get_active_domains(get_data_dir())
    if active is None or block.tier == "personal":
        return True
    return block.domain in active


def get_block(block_id: str) -> dict[str, Any]:
    """Return full block data as a serialisable dict."""
    blocks = _load_active_blocks()
    if block_id not in blocks:
        available = sorted(blocks.keys())
        raise ValueError(
            f"Block '{block_id}' not found. Available blocks: {', '.join(available)}"
        )
    block: Block = blocks[block_id]
    is_active = _check_domain_active(block, block_id)
    return {
        "id": block.slug,
        "slug": block.slug,
        "hash": block.hash,
        "version": block.version,
        "domain": block.domain,
        "intent": block.intent,
        "last_verified": block.last_verified,
        "stale": block.is_stale(),
        "tags": block.tags,
        "context_weight": block.context_weight,
        "provides": block.provides,
        "conflicts_with_tags": block.conflicts_with_tags,
        "constraints": block.constraints,
        "anti_patterns": block.anti_patterns,
        "doc_anchors": [
            {"url": a.url, "verified": a.verified} for a in block.doc_anchors
        ],
        "conflicts_with": block.conflicts_with,
        "requires": block.requires,
        "active": is_active,
    }


def inject_block(
    block_id: str,
    session_id: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Return formatted injection text for a block and record state."""
    blocks = _load_active_blocks()
    if block_id not in blocks:
        available = sorted(blocks.keys())
        raise ValueError(
            f"Block '{block_id}' not found. Available blocks: {', '.join(available)}"
        )
    block: Block = blocks[block_id]
    if not _check_domain_active(block, block_id):
        raise ValueError(
            f"Block '{block_id}' domain '{block.domain}' is not in active domains. "
            f"Run `turnzero domain add {block.domain}` to activate it."
        )
    if session_id:
        record_session_injection(session_id, block_id)
    if project_root:
        record_project_affinity(project_root, block_id)

    block = blocks[block_id]
    track_block_injected(domain=block.domain, tier=block.tier or "local")
    return block_fmt.to_injection_text(block)


def reset_session(session_id: str | None = None) -> str:
    """Clear session memory and fire telemetry summary."""
    track_session_summary(session_id=session_id)
    if session_id:
        clear_session_injections(session_id)
    return "✓ TurnZero session memory cleared."
