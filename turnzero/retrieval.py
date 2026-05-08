"""Intent classification and block retrieval."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from turnzero.blocks import Block
from turnzero.embed import cosine_similarity
from turnzero.repositories.index_repo import IndexEntry  # re-exported for callers
from turnzero.signals import (
    _ALL_SIGNALS,
    _FUZZY_SIGNALS,
    _QUESTION_PATTERNS,
    _SHORT_QUESTION_STARTERS,
    _SOCIAL_PATTERNS,
    FUZZY_MAX_LENGTH_DELTA,
    FUZZY_MIN_RATIO,
    FUZZY_WORD_MIN_LEN,
    INTENT_SIGNALS,
    MIN_MULTI_WORD_PROMPT_WORDS,
    MIN_SINGLE_WORD_QUESTION_LEN,
    MIN_SUBSTANTIVE_WORD_LEN,
)
from turnzero.types import Tier

# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------


def classify_intent(prompt: str) -> str:
    """Keyword-based intent classifier — no model required.

    Returns one of: build | debug | migrate | review.
    Defaults to 'build' when no signals match.
    """
    prompt_lower = prompt.lower()
    scores = {
        intent: sum(1 for kw in keywords if kw in prompt_lower)
        for intent, keywords in INTENT_SIGNALS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "build"


# ---------------------------------------------------------------------------
# Implementation gate — three-tier, domain-agnostic
# ---------------------------------------------------------------------------
# Tier 1: pre-filters (fast, no domain knowledge required)
#   - reject known social/chitchat patterns
#   - require minimum length/substance or professional question starter
# Tier 2: positive signal (ANY one passes)
#   - action/problem keyword hit (software + security verbs)
#   - question pattern (domain-agnostic: "?", "how do I", "should I", ...)
#   - domain detected in prompt or filesystem
# Tier 3: similarity threshold (0.70) is the final quality gate


def _fuzzy_signal_match(words: list[str]) -> bool:
    """Return True if any prompt word is within edit distance 1 of a fuzzy signal."""
    from difflib import SequenceMatcher

    for word in words:
        if len(word) < FUZZY_WORD_MIN_LEN:
            continue
        for signal in _FUZZY_SIGNALS:
            if abs(len(word) - len(signal)) > FUZZY_MAX_LENGTH_DELTA:
                continue
            if SequenceMatcher(None, word, signal).ratio() >= FUZZY_MIN_RATIO:
                return True
    return False


def _has_substance(prompt: str, lower: str) -> bool:
    """Pre-filter: reject pure chitchat before the positive signal check.

    Returns False (no substance) when:
      - the entire prompt matches a known social pattern, OR
      - the prompt is extremely short (< 2 words) AND not a direct question.
    """
    if lower.strip() in _SOCIAL_PATTERNS:
        return False

    words = lower.split()
    if len(words) < MIN_MULTI_WORD_PROMPT_WORDS:
        # Allow single-word "Question?" but not just "Hey"
        return "?" in lower and len(lower) > MIN_SINGLE_WORD_QUESTION_LEN

    # Professional question starters bypass length checks (e.g. "How to X")
    if any(lower.startswith(q) for q in _SHORT_QUESTION_STARTERS):
        return True

    # Require at least one substantial word.
    return any(len(w) >= MIN_SUBSTANTIVE_WORD_LEN for w in words)


def is_implementation_prompt(prompt: str, project_root: Path | None = None) -> bool:
    """Return True when the prompt is likely a real professional task.

    Three-tier gate (domain-agnostic):
      1. Pre-filter: reject known social patterns and vocabulary-free prompts
      2. Positive signal: action keyword OR question pattern OR known domain detected
      3. Final quality gate: similarity ≥ 0.75 (in the query layer, not here)

    Works for any domain — software, medicine, law, finance, security, etc.
    """
    lower = prompt.lower().strip()

    # Tier 1: pre-filters
    if not _has_substance(prompt, lower):
        return False

    # Tier 2a: action / problem keyword (exact or fuzzy)
    if any(sig in lower for sig in _ALL_SIGNALS):
        return True
    if _fuzzy_signal_match(lower.split()):
        return True

    # Tier 2b: question / intent pattern
    if any(pat in lower for pat in _QUESTION_PATTERNS):
        return True

    # Tier 2c: domain detected from filesystem (high-confidence — physical files exist)
    # Keyword-based domain detection is NOT used here: a mention of "security" or
    # "CVE" in a passive sentence ("I like reading about CVEs") would fire a false positive.
    # Question patterns in tier 2b already cover professional cross-domain prompts.
    return project_root is not None and detect_domain(prompt, project_root) is not None


# ---------------------------------------------------------------------------
# Domain detection
# ---------------------------------------------------------------------------


def detect_domain(prompt: str, project_root: Path | None = None) -> str | None:
    """Identify the primary tech domain from the prompt OR the filesystem.

    Checks signature files in project_root if provided, then falls back
    to keyword matching in the prompt text.
    Returns the domain name (e.g. 'fastapi') or None if not found.
    """
    # 1. Try Filesystem Detection (Highest Confidence)
    if project_root and project_root.exists():
        # Next.js / React
        pkg_json = project_root / "package.json"
        if pkg_json.exists():
            content = pkg_json.read_text(encoding="utf-8").lower()
            if '"next"' in content:
                return "nextjs"
            if '"react-native"' in content:
                return "react-native"
            if '"stripe"' in content:
                return "stripe"

        # FastAPI / Python
        pyproject = project_root / "pyproject.toml"
        reqs = project_root / "requirements.txt"
        for f in [pyproject, reqs]:
            if f.exists():
                content = f.read_text(encoding="utf-8").lower()
                if "fastapi" in content:
                    return "fastapi"
                if "langchain" in content:
                    return "langchain"

        # Docker
        if (project_root / "docker-compose.yml").exists() or (
            project_root / "Dockerfile"
        ).exists():
            return "docker"

        # Supabase (config file)
        if (project_root / "supabase").exists() or (
            project_root / "supabase.yaml"
        ).exists():
            return "supabase"

    # 2. Fallback to Keyword Detection in Prompt
    prompt_lower = prompt.lower()
    # Hardcoded mapping for MVP domains
    domains = {
        "fastapi": ["fastapi", "python api", "uvicorn"],
        "nextjs": ["nextjs", "next.js", "app router", "pages router"],
        "postgresql": ["postgresql", "postgres", "psql", "sql database"],
        "supabase": ["supabase", "supabase auth", "supabase storage"],
        "react-native": ["react native", "expo", "react-native"],
        "docker": ["docker", "docker-compose", "docker compose", "container"],
        "langchain": ["langchain", "lcel", "retriever", "llm chain"],
        "stripe": ["stripe", "payment", "checkout", "webhook"],
        "typescript": ["typescript", "ts-config", "strict mode"],
        "rest-api": ["rest api", "api design", "http endpoint"],
        "security": [
            "security",
            "secure",
            "harden",
            "hardening",
            "pentest",
            "penetration test",
            "vulnerability",
            "cve",
            "owasp",
            "threat model",
            "audit",
            "secrets management",
            "iam",
            "least privilege",
            "zero trust",
            "devsecops",
            "rotate secrets",
        ],
    }

    for domain, keywords in domains.items():
        if any(kw in prompt_lower for kw in keywords):
            return domain
    return None


# ---------------------------------------------------------------------------
# Test hook — injected by conftest; None in production
# ---------------------------------------------------------------------------

# Set by tests/conftest.py to tests/fixtures/similarity.test_similarity.
# When set, query() calls this instead of cosine_similarity so tests run
# without a live embedding backend and with stable lexical scores.
_similarity_override: Any = None

# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

DOMAIN_BOOST = 1.5  # Heavy boost for matching the detected domain
INTENT_BOOST = 1.2  # Boost for matching intent
PROJECT_AFFINITY_BOOST = 1.25  # Boost for blocks previously used in this project
# Penalty when no domain is detected AND block has no keyword overlap with the prompt.
# Prevents domain-specific blocks (e.g. nextjs-seo-review) from injecting into
# unrelated sessions where detect_domain returns None (no filesystem or keyword signal).
# 0.6x makes it impossible to clear the 0.70 threshold (would need raw score > 1.0).
DOMAIN_OVERLAP_PENALTY = 0.6
MAX_PERSONAL_WEIGHT = 2500  # Token budget for identity injection
IDENTITY_SCORE_THRESHOLD = 2.0  # Scores >= this indicate Identity Priors
HIGH_CONFIDENCE_THRESHOLD = 0.90  # Threshold for high-confidence matches


def get_identity_context(
    blocks: dict[str, Block],
    project_root: Path | None = None,
    exclude_ids: set[str] | None = None,
) -> tuple[list[tuple[Block, float]], bool]:
    """Return all blocks from the 'personal' tier that fit the context budget.

    Personal Priors establish the 'Portable AI Identity'. They are injected
    unconditionally at session start, regardless of domain (universal persona).

    If project_root is provided, personal priors are filtered:
    - Included if domain is 'global'
    - Included if project_hash matches the project_root
    - Included if project_hash is None (legacy/universal)

    Returns (blocks, limit_exceeded).
    """
    from turnzero.state import _get_project_hash

    exclude_ids = exclude_ids or set()
    personal_results: list[tuple[Block, float]] = []
    personal_weight = 0

    project_hash = None
    if project_root:
        project_hash = _get_project_hash(project_root)

    # Filter all blocks from the personal tier
    candidates = [
        b
        for b in blocks.values()
        if b.tier == Tier.PERSONAL
        and b.slug not in exclude_ids
        and (
            b.domain == "global"
            or not b.project_hash
            or (project_hash and b.project_hash == project_hash)
        )
    ]
    # Sort by verification date to keep newest preferences first
    candidates.sort(key=lambda b: b.last_verified, reverse=True)

    limit_exceeded = False
    for b in candidates:
        if personal_weight + b.context_weight <= MAX_PERSONAL_WEIGHT:
            # Score of 2.0 ensures they rank above all Expert Priors
            personal_results.append((b, IDENTITY_SCORE_THRESHOLD))
            personal_weight += b.context_weight
        else:
            limit_exceeded = True

    return personal_results, limit_exceeded


def _score_entry(
    entry: IndexEntry,
    prompt: str,
    prompt_embedding: Any,
    prompt_lower: str,
    intent: str,
    domain: str | None,
    affinity: dict[str, Any],
    use_override: bool,
    blocks: dict[str, Block],
) -> float | None:
    """Score one index entry against the prompt. Returns None if the entry is filtered."""
    if use_override:
        block = blocks.get(entry.block_id)
        if block is None:
            return None
        score = float(_similarity_override(prompt, block))
    else:
        score = cosine_similarity(prompt_embedding, entry.embedding)

    boost = 1.0
    if entry.intent == intent:
        boost *= INTENT_BOOST
    if domain and entry.domain == domain:
        boost *= DOMAIN_BOOST
    elif domain and entry.domain != domain:
        boost *= 0.5
    if entry.block_id in affinity:
        boost *= PROJECT_AFFINITY_BOOST

    score = min(score * boost, 1.0)

    # Keyword overlap gate: when no domain detected, penalise blocks with
    # no tag/domain overlap with the prompt — prevents off-topic injection.
    if domain is None and entry.domain not in ("global",):
        overlap_tokens = set(entry.tags) | {entry.domain}
        if not any(tok in prompt_lower for tok in overlap_tokens):
            score *= DOMAIN_OVERLAP_PENALTY

    return score


def _select_results(
    scored: list[tuple[IndexEntry, float]],
    effective_threshold: float,
    top_k: int,
    context_weight: int,
    blocks: dict[str, Block],
) -> list[tuple[Block, float]]:
    """Apply saturation logic, budget, archival filter, and confidence weighting."""
    scored.sort(key=lambda x: x[1], reverse=True)

    high_conf = [(e, s) for e, s in scored if s >= HIGH_CONFIDENCE_THRESHOLD]
    candidates = (
        high_conf if len(high_conf) >= top_k
        else [(e, s) for e, s in scored if s >= effective_threshold][:top_k]
    )

    results: list[tuple[Block, float]] = []
    current_weight = 0
    for e, s in candidates:
        block = blocks.get(e.block_id)
        if block is None or block.archived:
            continue
        if current_weight + block.context_weight > context_weight:
            continue
        results.append((block, s * block.confidence))
        current_weight += block.context_weight

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _resolve_conflicts(
    results: list[tuple[Block, float]],
    context_weight: int,
) -> list[tuple[Block, float]]:
    """Remove conflicting blocks and enforce context weight budget (highest score wins).

    Handles both explicit slug-based conflicts and tag-based (provides) conflicts.
    """
    seen_slugs: set[str] = set()
    blocked_slugs: set[str] = set()
    active_provides: set[str] = set()
    resolved: list[tuple[Block, float]] = []
    total_weight = 0

    for block, score in results:
        # Deduplicate — same block can appear in multiple source indexes
        if block.slug in seen_slugs:
            continue
        seen_slugs.add(block.slug)

        # Check explicit slug conflicts
        if block.slug in blocked_slugs:
            continue

        # Check tag-based (provides) conflicts
        if any(tag in active_provides for tag in block.conflicts_with_tags):
            continue

        # Check if any currently provided tag is in this block's conflict list
        # (Inverse check: does a previously accepted block conflict with this one's tags?)
        # Since we iterate by score, higher score blocks set the "provides" state.

        if total_weight + block.context_weight > context_weight:
            continue

        resolved.append((block, score))
        blocked_slugs.update(block.conflicts_with)
        active_provides.update(block.provides)
        total_weight += block.context_weight
    return resolved


def rerank_with_llm(
    prompt: str,
    candidates: list[tuple[Block, float]],
    model: str = "llama3.2",
) -> list[tuple[Block, float]]:
    """Use a local LLM to refine the ranking of top candidates.

    The LLM assesses the prompt against each block's constraints/anti-patterns
    and returns a relevance score [0.0 - 1.0].
    """
    if not candidates:
        return []

    try:
        import ollama
    except ImportError:
        # Fall back to original ranking if ollama is missing
        return candidates

    reranked: list[tuple[Block, float]] = []

    for block, vector_score in candidates:
        verification_prompt = f"""\
Task: Rate the relevance of an 'Expert Prior' to a developer's 'Opening Prompt'.
An Expert Prior is relevant if its constraints or anti-patterns help the AI answer the \
prompt correctly and avoid common mistakes for that specific domain.

Opening Prompt: "{prompt}"

Expert Prior: "{block.slug}"
Constraints: {", ".join(block.constraints[:2])}
Anti-patterns: {", ".join(block.anti_patterns[:2])}

Rate relevance from 0.0 (irrelevant) to 1.0 (perfect match).
Respond with ONLY the numeric score, no prose."""

        try:
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": verification_prompt}],
                options={"temperature": 0.0},
            )
            content = response["message"]["content"].strip()
            match = re.search(r"(\d+\.\d+|\d+)", content)
            llm_score = float(match.group(1)) if match else 0.0
            llm_score = max(0.0, min(1.0, llm_score))
            # LLM score weighted at 80%, vector score as 20% prior
            reranked.append((block, (llm_score * 0.8) + (vector_score * 0.2)))
        except Exception:
            reranked.append((block, vector_score))

    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked


def query(
    prompt: str,
    index: list[IndexEntry],
    blocks: dict[str, Block],
    top_k: int = 5,
    threshold: float = 0.70,
    context_weight: int = 4000,
    strict_intent: bool = True,
    project_root: Path | None = None,
    rerank_model: str | None = None,
    exclude_block_ids: set[str] | None = None,
) -> list[tuple[Block, float]]:
    """Return relevant blocks using saturation-based hybrid retrieval.

    Saturation Logic:
    1. Return ALL blocks with a final score >= 0.90 (High Confidence).
    2. If fewer than top_k blocks are found, fill up to top_k with next best (>= threshold).
    """
    from turnzero.embed import embed
    from turnzero.state import get_project_affinity

    exclude_block_ids = exclude_block_ids or set()
    prompt_embedding = embed(prompt)
    prompt_lower = prompt.lower()
    intent = classify_intent(prompt)
    domain = detect_domain(prompt, project_root=project_root)
    use_override = _similarity_override is not None
    effective_threshold = min(threshold, 0.55) if use_override else threshold
    affinity: dict[str, Any] = get_project_affinity(project_root) if project_root else {}

    scored: list[tuple[IndexEntry, float]] = []
    for entry in index:
        if entry.block_id in exclude_block_ids:
            continue
        if strict_intent and entry.intent != intent:
            continue
        score = _score_entry(
            entry, prompt, prompt_embedding, prompt_lower,
            intent, domain, affinity, use_override, blocks,
        )
        if score is not None:
            scored.append((entry, score))

    results = _select_results(scored, effective_threshold, top_k, context_weight, blocks)

    if rerank_model:
        results = rerank_with_llm(prompt, results, model=rerank_model)

    return _resolve_conflicts(results, context_weight)
