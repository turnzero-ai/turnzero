"""Intent classification, index loading, and block retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from turnzero.blocks import Block
from turnzero.embed import cosine_similarity

# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

INTENT_SIGNALS: dict[str, list[str]] = {
    "build": [
        "build", "create", "scaffold", "implement", "add", "make",
        "set up", "write", "develop", "integrate",
    ],
    "debug": [
        "error", "bug", "fix", "not working", "failing", "broken",
        "why", "problem", "crash", "exception", "undefined",
        "issue", "persisting", "help with", "correct",
        "leaked", "exposed", "compromised", "breached", "accidentally",
    ],
    "migrate": [
        "upgrade", "migrate", "convert", "move", "port",
        "refactor", "replace", "switch", "from v", "to v",
    ],
    "review": [
        "review", "check", "is this", "best practice", "correct",
        "improve", "audit", "better way", "should i", "performance",
    ],
}


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


# Positive signals that a prompt describes an active technical task.
# Require at least one to be present before hitting the similarity index.
# Two categories: action verbs (user is doing something) and
# problem signals (something concrete is failing or broken).
_IMPL_ACTION_SIGNALS: frozenset[str] = frozenset({
    "build", "building", "create", "creating", "scaffold", "implement",
    "implementing", "set up", "setting up", "configure", "configuring",
    "deploy", "deploying", "write", "writing", "develop", "developing",
    "migrate", "migrating", "integrate", "integrating", "add", "adding",
    "start", "starting", "launch", "launching", "init", "generate",
    "connect", "connecting", "install", "installing", "run", "running",
    "refactor", "refactoring", "convert", "converting", "upgrade",
    "upgrading", "wire up", "hook up", "spin up",
    "harden", "hardening", "scan", "scanning", "audit", "auditing",
    "pentest", "pentesting", "rotate", "rotating", "remediate", "remediating",
})

_IMPL_PROBLEM_SIGNALS: frozenset[str] = frozenset({
    "keeps", "throwing", "throws", "not working", "failing", "broken",
    "returns", "return", "crashes", "crashing", "doesn't work", "does not work",
    "can't", "cannot", "stuck", "blocked", "error", "exception", "bug",
    "not persisting", "not rendering", "not loading", "not connecting",
    "wrong", "incorrect", "unexpected", "undefined", "null pointer",
    "fix", "fixing", "debug", "debugging", "issue",
    "leaked", "exposed", "compromised", "breached", "accidentally",
})


_ALL_SIGNALS: frozenset[str] = _IMPL_ACTION_SIGNALS | _IMPL_PROBLEM_SIGNALS

# Single-word signals long enough for fuzzy matching (≥5 chars).
# Short words like "add", "run", "fix" require exact match to avoid false positives.
_FUZZY_SIGNALS: frozenset[str] = frozenset(
    s for s in _ALL_SIGNALS if " " not in s and len(s) >= 5
)


def _fuzzy_signal_match(words: list[str]) -> bool:
    """Return True if any prompt word is within edit distance 1 of a fuzzy signal.

    Uses SequenceMatcher ratio ≥ 0.82, which catches single-character typos and
    transpositions (e.g. 'biulding' → 'building', 'depoly' → 'deploy') while
    rejecting unrelated words.
    """
    from difflib import SequenceMatcher

    for word in words:
        if len(word) < 4:
            continue
        for signal in _FUZZY_SIGNALS:
            if abs(len(word) - len(signal)) > 2:
                continue
            if SequenceMatcher(None, word, signal).ratio() >= 0.82:
                return True
    return False


def is_implementation_prompt(prompt: str) -> bool:
    """Return True only when the prompt describes an active technical task.

    Requires at least one action signal (user is doing something) or
    problem signal (something is broken/failing). Evaluation, comparison,
    and learning prompts that lack these signals return False.

    Exact substring match runs first (free). Fuzzy word-level match runs as
    fallback to catch typos (e.g. 'biulding', 'depoly', 'creaet').
    """
    lower = prompt.lower()
    if any(sig in lower for sig in _ALL_SIGNALS):
        return True
    return _fuzzy_signal_match(lower.split())


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@dataclass
class IndexEntry:
    block_id: str
    embedding: np.ndarray
    domain: str
    intent: str
    tags: list[str]
    source: str = "local"


def load_index(
    index_path: Path,
    sources: list[str] | None = None,
) -> list[IndexEntry]:
    """Load index.jsonl written by index.build().

    If sources is given, only return entries whose source tier is in the list.
    """
    if not index_path.exists():
        raise FileNotFoundError(
            f"Index not found at {index_path}\n"
            "Build it first:  turnzero index build"
        )

    entries: list[IndexEntry] = []
    for line in index_path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        source = data.get("source", "local")
        if sources is not None and source not in sources:
            continue
        entries.append(
            IndexEntry(
                block_id=data["block_id"],
                embedding=np.array(data["embedding"], dtype=np.float32),
                domain=data.get("domain", data.get("stack", "unknown")),
                intent=data["intent"],
                tags=data["tags"],
                source=source,
            )
        )
    return entries


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
        if (project_root / "docker-compose.yml").exists() or (project_root / "Dockerfile").exists():
            return "docker"

        # Supabase (config file)
        if (project_root / "supabase").exists() or (project_root / "supabase.yaml").exists():
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
            "security", "secure", "harden", "hardening", "pentest", "penetration test",
            "vulnerability", "cve", "owasp", "threat model", "audit", "secrets management",
            "iam", "least privilege", "zero trust", "devsecops", "rotate secrets",
        ],
    }

    for domain, keywords in domains.items():
        if any(kw in prompt_lower for kw in keywords):
            return domain
    return None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

DOMAIN_BOOST = 1.3  # Heavy boost for matching the detected domain
INTENT_BOOST = 1.1  # Boost for matching intent


def query(
    prompt: str,
    index: list[IndexEntry],
    blocks: dict[str, Block],
    top_k: int = 3,
    threshold: float = 0.75,
    context_weight: int = 4000,
    strict_intent: bool = True,
    project_root: Path | None = None,
    rerank_model: str | None = None,
) -> list[tuple[Block, float]]:
    """Return up to top_k blocks relevant to prompt, above similarity threshold.

    Steps:
    1. Embed the prompt.
    2. Detect intent and domain (from prompt AND filesystem).
    3. Filter/Score entries with intent and domain awareness.
    4. Resolve conflicts and enforce context weight budget.
    """
    from turnzero.embed import embed

    prompt_embedding = embed(prompt)
    intent = classify_intent(prompt)
    domain = detect_domain(prompt, project_root=project_root)

    scored: list[tuple[IndexEntry, float]] = []
    for entry in index:
        # Strict intent filtering
        if strict_intent and entry.intent != intent:
            continue

        score = cosine_similarity(prompt_embedding, entry.embedding)

        # Apply boosts
        boost = 1.0
        if entry.intent == intent:
            boost *= INTENT_BOOST
        
        # Domain match boost
        if domain and entry.domain == domain:
            boost *= DOMAIN_BOOST
        elif domain and entry.domain != domain:
            # Penalize blocks from DIFFERENT domains if a project domain is detected
            boost *= 0.5

        score = min(score * boost, 1.0)
        scored.append((entry, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    candidates = [(e, s) for e, s in scored if s >= threshold][:top_k]

    results: list[tuple[Block, float]] = [
        (blocks[e.block_id], s)
        for e, s in candidates
        if e.block_id in blocks
    ]

    if rerank_model:
        results = rerank_with_llm(prompt, results, model=rerank_model)

    return _resolve_conflicts(results, context_weight)


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
        # Construct a small verification prompt
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
            # Extract the first float-like string
            match = re.search(r"(\d+\.\d+|\d+)", content)
            llm_score = float(match.group(1)) if match else 0.0
            
            # Clip score to [0, 1]
            llm_score = max(0.0, min(1.0, llm_score))
            
            # Combine scores: LLM score is high-fidelity, vector score is a fallback
            # We weight LLM score at 80% and vector search as a 20% prior
            combined_score = (llm_score * 0.8) + (vector_score * 0.2)
            reranked.append((block, combined_score))
        except Exception:
            # Fallback to vector score on LLM failure
            reranked.append((block, vector_score))

    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked


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
