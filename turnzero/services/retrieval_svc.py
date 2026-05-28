"""Retrieval service — block loading, index caching, suggestion, and injection."""

from __future__ import annotations

from pathlib import Path

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
from turnzero.retrieval import is_implementation_prompt
from turnzero.retrieval import query as _query
from turnzero.session import (
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
from turnzero.types import (
    BLOCK_ID_NO_MATCH_HINT,
    BLOCK_ID_PERSONAL_LIMIT_WARNING,
    BlockData,
    Intent,
    SuggestionEntry,
    Tier,
    TurnLabel,
)

# Per-source index cache: path → (mtime, entries)
_INDEX_CACHE: dict[Path, tuple[float, list[IndexEntry]]] = {}

# Blocks cache: (blocks_dir, tuple(sources)) → (mtime, blocks_dict)
_BLOCKS_CACHE: dict[tuple[Path, tuple[str, ...]], tuple[float, dict[str, Block]]] = {}

# Number of words to show in an expert block preview string
_EXPERT_PREVIEW_WORDS = 6


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


def _expert_preview(block: Block) -> str:
    """Return a short preview string from the first constraint."""
    text = block.constraints[0] if block.constraints else ""
    words = text.split()
    return " ".join(words[:_EXPERT_PREVIEW_WORDS]) + (
        "…" if len(words) > _EXPERT_PREVIEW_WORDS else ""
    )


def _apply_domain_whitelist(blocks: dict[str, Block]) -> dict[str, Block]:
    """Filter blocks by active domain whitelist; personal tier always passes."""
    active_domains = get_active_domains(get_data_dir())
    if active_domains is None:
        return blocks
    active_set = set(active_domains)
    return {
        k: v for k, v in blocks.items()
        if v.tier == Tier.PERSONAL or v.domain in active_set
    }


def _assemble_suggestions(
    personal_results: list[tuple[Block, float]],
    expert_results: list[tuple[Block, float]],
    limit_exceeded: bool,
    turn: TurnLabel,
    session_id: str | None,
    project_root: Path | None,
    inject_all: bool,
) -> list[SuggestionEntry]:
    """Build SuggestionEntry list and record injections when inject_all=True."""
    def _build_entry(block: Block, score: float, is_personal: bool) -> SuggestionEntry:
        entry: SuggestionEntry = {
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
        if inject_all:
            # WF-3: inline full text and record injection in one round trip
            entry["full_text"] = block_fmt.to_injection_text(block)
            if session_id:
                record_session_injection(session_id, block.slug)
            if project_root:
                record_project_affinity(project_root, block.slug)
            track_block_injected(domain=block.domain, tier=block.tier or "local")
        return entry

    formatted: list[SuggestionEntry] = [
        _build_entry(block, score, is_personal=True)
        for block, score in personal_results
    ] + [
        _build_entry(block, score, is_personal=False)
        for block, score in expert_results
    ]

    if limit_exceeded:
        formatted.append(
            {
                "block_id": BLOCK_ID_PERSONAL_LIMIT_WARNING,
                "score": 0.0,
                "domain": "system",
                "intent": Intent.REVIEW,
                "tags": ["warning"],
                "context_weight": 0,
                "stale": False,
                "turn": turn,
                "preview": "⚠ Personal Priors budget exceeded (2500 tokens). Some rules omitted.",
            }
        )
    return formatted


def _record_and_track(
    formatted: list[SuggestionEntry],
    blocks: dict[str, Block],
    prompt: str,
    session_id: str | None,
    personal_results: list[tuple[Block, float]],
) -> None:
    """Log injection event and fire session_start telemetry."""
    from turnzero.services import stats_svc

    real_blocks = [s for s in formatted if s["block_id"] != BLOCK_ID_PERSONAL_LIMIT_WARNING]
    if formatted:
        stats_svc.log_injection(
            block_ids=[s["block_id"] for s in real_blocks],
            domains=list({s["domain"] for s in real_blocks if s.get("domain")}),
            prompt_words=len(prompt.split()),
            session_id=session_id,
            tokens_injected=sum(s.get("context_weight", 0) for s in real_blocks),
        )

    personal_count = sum(1 for b in blocks.values() if b.tier == Tier.PERSONAL)
    track_session_start(
        session_id=session_id,
        blocks_suggested=len(formatted),
        domains=list({s["domain"] for s in formatted if s.get("domain")}),
        has_personal_priors=len(personal_results) > 0,
        personal_block_count=personal_count,
        total_block_count=len(blocks),
    )


def list_suggested_blocks(
    prompt: str,
    top_k: int = 5,
    threshold: float = 0.70,
    context_weight: int = 5000,
    strict_intent: bool = True,
    project_root: Path | None = None,
    session_id: str | None = None,
    inject_all: bool = False,
) -> list[SuggestionEntry]:
    """Return ranked block suggestions for prompt as serialisable dicts."""
    from turnzero.retrieval import get_identity_context

    blocks = _apply_domain_whitelist(_load_active_blocks())
    index = _load_active_index()
    exclude_ids = get_session_injections(session_id) if session_id else set()

    # WF-2: skip personal priors on Turn N (already injected this session).
    is_turn_0 = not exclude_ids
    if is_turn_0:
        personal_results, limit_exceeded = get_identity_context(
            blocks, project_root=project_root, exclude_ids=exclude_ids
        )
    else:
        personal_results, limit_exceeded = [], False

    personal_weight = sum(b.context_weight for b, _ in personal_results)
    expert_results = _query(
        prompt, index, blocks,
        top_k=top_k, threshold=threshold,
        context_weight=context_weight - personal_weight,
        strict_intent=strict_intent, project_root=project_root,
        exclude_block_ids=exclude_ids | {b.slug for b, _ in personal_results},
    )

    turn = TurnLabel.FIRST if is_turn_0 else TurnLabel.SUBSEQUENT
    formatted = _assemble_suggestions(
        personal_results, expert_results, limit_exceeded, turn,
        session_id, project_root, inject_all,
    )
    _record_and_track(formatted, blocks, prompt, session_id, personal_results)

    # UX-1: when gate passed but no blocks matched, guide user to diagnose
    if not formatted and is_implementation_prompt(prompt, project_root=project_root):
        formatted = [
            SuggestionEntry(
                block_id=BLOCK_ID_NO_MATCH_HINT,
                score=0.0,
                domain="system",
                intent=Intent.REVIEW,
                tags=["hint"],
                context_weight=0,
                stale=False,
                turn=TurnLabel.SUBSEQUENT,
                preview=(
                    "No priors matched. Run "
                    '`turnzero query --explain "<your prompt>"` to diagnose.'
                ),
            )
        ]
    return formatted


def _check_domain_active(block: Block, block_id: str) -> bool:
    """Return True if block's domain is in the active whitelist (or no whitelist set)."""
    active = get_active_domains(get_data_dir())
    if active is None or block.tier == Tier.PERSONAL:
        return True
    return block.domain in active


def get_block(block_id: str) -> BlockData:
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


def get_all_blocks(blocks_dir: Path | None = None) -> dict[str, Block]:
    """Return all blocks from the given dir (or active data dir). CLI service boundary."""
    from turnzero.repositories.block_repo import load_all_blocks as _load

    target = blocks_dir or get_blocks_dir()
    if not target.exists():
        target = get_bundled_blocks_dir()
    return _load(target)


def load_index_entries(index_path: Path | None = None) -> list[IndexEntry]:
    """Return index entries from the given path (or active index). CLI service boundary."""
    path = index_path or get_index_path()
    if not path.exists():
        path = get_bundled_index_path()
    return load_index(path)


def query_blocks(
    prompt: str,
    top_k: int = 5,
    threshold: float = 0.70,
    strict_intent: bool = True,
    project_root: Path | None = None,
    exclude_block_ids: set[str] | None = None,
) -> list[tuple[Block, float]]:
    """Run retrieval query via service layer — no direct repo access from CLI needed."""
    blocks = _load_active_blocks()
    index = _load_active_index()
    return _query(
        prompt,
        index,
        blocks,
        top_k=top_k,
        threshold=threshold,
        strict_intent=strict_intent,
        project_root=project_root,
        exclude_block_ids=exclude_block_ids,
    )
