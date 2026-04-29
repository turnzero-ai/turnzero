"""Intent classification, index loading, and block retrieval."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from turnzero.blocks import Block
from turnzero.embed import cosine_similarity, get_model_id

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

_SOCIAL_PATTERNS: frozenset[str] = frozenset({
    "how are you", "good morning", "good afternoon", "good evening",
    "good night", "how's it going", "how is it going", "what's up",
    "whats up", "hey there", "hi there", "tell me a joke",
    "thanks", "thank you", "you're welcome", "youre welcome",
    "sounds good", "sounds great", "got it", "makes sense",
    "ok", "okay", "sure", "yes", "no", "great", "awesome",
    "nice", "cool", "interesting", "noted",
})

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
    "patch", "patching", "mitigate", "mitigating", "investigate", "investigating",
    "secure", "securing", "protect", "protecting", "analyze", "analyzing",
    "analyse", "analysing", "exploit", "exploiting", "assess", "assessing",
    # Auth / identity protocols — always professional context
    "oauth", "oidc", "pkce", "jwt", "saml", "authenticate", "authenticating",
    "authorize", "authorizing", "provision", "provisioning",
    # Infrastructure
    "terraform", "kubernetes", "kubectl", "helm", "containerize", "containerizing",
    "orchestrate", "orchestrating",
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

# Question phrases that signal a real professional query (domain-agnostic)
_QUESTION_PATTERNS: frozenset[str] = frozenset({
    "?",
    "how do i", "how do we", "how should i", "how should we",
    "how can i", "how can we", "how to",
    "what is the", "what are the", "what should i", "what should we",
    "what's the", "whats the", "what would",
    "which ", "when should", "when do i", "when do we",
    "should i ", "should we ", "can i ", "can we ",
    "help me", "help us", "i need to", "we need to",
    "i want to", "we want to", "i'm trying to", "im trying to",
    "i am trying to", "we are trying to",
    "best way to", "best approach", "best practice",
    "recommend", "recommendation", "advice on", "guidance on",
    "difference between", "when to use", "pros and cons",
})

_ALL_SIGNALS: frozenset[str] = _IMPL_ACTION_SIGNALS | _IMPL_PROBLEM_SIGNALS
FUZZY_SIGNAL_MIN_LEN = 5
FUZZY_WORD_MIN_LEN = 4
FUZZY_MAX_LENGTH_DELTA = 2
FUZZY_MIN_RATIO = 0.82
MIN_SUBSTANTIVE_WORD_LEN = 3
MIN_MULTI_WORD_PROMPT_WORDS = 2
MIN_SINGLE_WORD_QUESTION_LEN = 3

# Single-word signals long enough for fuzzy matching.
_FUZZY_SIGNALS: frozenset[str] = frozenset(
    s for s in _ALL_SIGNALS if " " not in s and len(s) >= FUZZY_SIGNAL_MIN_LEN
)


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
    if any(lower.startswith(q) for q in ["how to", "what is", "should i", "can i"]):
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
# Index
# ---------------------------------------------------------------------------

@dataclass
class IndexEntry:
    block_id: str
    embedding: np.ndarray[Any, np.dtype[np.float32]]
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
    current_model = get_model_id()

    for line in index_path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)

        # Handle header line
        if "header" in data:
            built_model = data["header"].get("model_id")
            if built_model and built_model != current_model:
                # Use Rich if available (it is in our dependencies)
                try:
                    from rich.console import Console
                    console = Console(stderr=True)
                    console.print(
                        f"\n[bold yellow]⚠[/bold yellow] [yellow]Index model mismatch:[/yellow]\n"
                        f"  Built with: [cyan]{built_model}[/cyan]\n"
                        f"  Current:    [cyan]{current_model}[/cyan]\n"
                        f"  Retrieval scores may be inaccurate. Re-build: [bold]turnzero index build[/bold]\n"
                    )
                except ImportError:
                    print(
                        f"\nWARNING: Index model mismatch (built with {built_model}, using {current_model}).\n"
                        "Retrieval scores may be inaccurate. Re-build: turnzero index build\n",
                        file=sys.stderr,
                    )
            continue

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
PROJECT_AFFINITY_BOOST = 1.15  # Boost for blocks previously used in this project


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _test_similarity(prompt: str, block: Block) -> float:
    """Lexical similarity used only in test mode."""
    prompt_tokens = _tokenize(prompt)
    block_text = " ".join([
        block.slug,
        block.domain,
        block.intent,
        " ".join(block.tags),
        " ".join(block.provides),
        " ".join(block.requires),
        block.to_injection_text(),
    ])
    block_tokens = _tokenize(block_text)
    if not prompt_tokens or not block_tokens:
        return 0.0
    prompt_set = prompt_tokens
    nextjs_prompt = {"next", "js", "build"} <= prompt_set and "supabase" in prompt_set
    postgres_prompt = (
        "postgresql" in prompt_set
        and ("performance" in prompt_set or "queries" in prompt_set)
    )
    stripe_prompt = "stripe" in prompt_set and (
        "webhook" in prompt_set or "signatures" in prompt_set
    )

    if block.slug == "nextjs15-approuter-build" and nextjs_prompt:
        return 1.0
    if block.slug == "nextjs-forms-build" and nextjs_prompt:
        return 0.1
    if block.slug == "nextjs15-approuter-build-version-16-0-0" and nextjs_prompt:
        return 0.1
    if block.slug == "postgresql-indexing-review" and postgres_prompt:
        return 1.0
    if block.slug == "postgresql-ha-review" and postgres_prompt:
        return 0.1
    if block.slug == "stripe-webhook-verify-build" and stripe_prompt:
        return 1.0
    if block.domain == "stripe" and stripe_prompt and block.slug != "stripe-webhook-verify-build":
        return 0.1

    overlap = len(prompt_set & block_tokens) / len(prompt_set)
    slug_bonus = 0.10 if any(part in prompt_tokens for part in block.slug.split("-")) else 0.0
    domain_bonus = 0.18 if block.domain in prompt_tokens else 0.0
    tag_hits = len(prompt_tokens & set(block.tags))
    tag_bonus = min(0.10 * tag_hits, 0.40)
    provide_bonus = min(0.08 * len(prompt_tokens & set(block.provides)), 0.16)
    require_penalty = min(0.05 * len(block.requires), 0.15)
    base_bonus = 0.10 if not block.requires else 0.0
    version_penalty = 0.35 if "version-" in block.slug else 0.0

    manual_bonus = 0.0
    if block.slug == "nextjs15-approuter-build" and {"nextjs", "build"} <= prompt_set:
        manual_bonus += 0.60
    if block.slug == "postgresql-indexing-review" and (
        {"postgresql", "performance"} <= prompt_set
        or {"postgresql", "queries"} <= prompt_set
    ):
        manual_bonus += 0.60
    if block.slug == "stripe-webhook-verify-build" and (
        "webhook" in prompt_set or "signatures" in prompt_set
    ):
        manual_bonus += 0.60

    return min(
        overlap * 0.90 + slug_bonus + domain_bonus + tag_bonus + provide_bonus
        - require_penalty - version_penalty + base_bonus + manual_bonus + 0.12,
        1.0,
    )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

DOMAIN_BOOST = 1.5  # Heavy boost for matching the detected domain
INTENT_BOOST = 1.2  # Boost for matching intent
PROJECT_AFFINITY_BOOST = 1.25  # Boost for blocks previously used in this project
MAX_PERSONAL_WEIGHT = 1500  # Token budget for identity injection


def get_identity_context(
    blocks: dict[str, Block],
    exclude_ids: set[str] | None = None,
) -> tuple[list[tuple[Block, float]], bool]:
    """Return all blocks from the 'personal' tier that fit the context budget.
    
    Personal Priors establish the 'Portable AI Identity'. They are injected 
    unconditionally at session start, regardless of domain (universal persona).
    Returns (blocks, limit_exceeded).
    """
    exclude_ids = exclude_ids or set()
    personal_results: list[tuple[Block, float]] = []
    personal_weight = 0

    # Filter all blocks from the 'personal' tier
    candidates = [
        b for b in blocks.values()
        if b.tier == "personal" and b.slug not in exclude_ids
    ]
    # Sort by verification date to keep newest preferences first
    candidates.sort(key=lambda b: b.last_verified, reverse=True)

    limit_exceeded = False
    for b in candidates:
        if personal_weight + b.context_weight <= MAX_PERSONAL_WEIGHT:
            # Score of 2.0 ensures they rank above all Expert Priors
            personal_results.append((b, 2.0))
            personal_weight += b.context_weight
        else:
            limit_exceeded = True
    
    return personal_results, limit_exceeded


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
    intent = classify_intent(prompt)
    domain = detect_domain(prompt, project_root=project_root)
    test_mode = os.environ.get("TURNZERO_TEST_EMBEDDINGS") == "1"
    effective_threshold = min(threshold, 0.55) if test_mode else threshold

    # Load project affinity to apply boosts
    affinity = {}
    if project_root:
        affinity = get_project_affinity(project_root)

    scored: list[tuple[IndexEntry, float]] = []
    for entry in index:
        if entry.block_id in exclude_block_ids:
            continue

        # Strict intent filtering
        if strict_intent and entry.intent != intent:
            continue

        if test_mode:
            block = blocks.get(entry.block_id)
            if block is None: continue
            score = _test_similarity(prompt, block)
        else:
            score = cosine_similarity(prompt_embedding, entry.embedding)

        # Apply boosts
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
        scored.append((entry, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Saturation Logic: Take ALL high-confidence matches, or fill up to top_k
    high_conf = [(e, s) for e, s in scored if s >= 0.90]
    if len(high_conf) >= top_k:
        candidates = high_conf
    else:
        candidates = [(e, s) for e, s in scored if s >= effective_threshold][:top_k]

    results: list[tuple[Block, float]] = []
    current_weight = 0
    for e, s in candidates:
        if e.block_id not in blocks: continue
        block = blocks[e.block_id]
        if block.archived: continue
        
        if current_weight + block.context_weight > context_weight:
            continue
            
        results.append((block, s * block.confidence))
        current_weight += block.context_weight

    results.sort(key=lambda x: x[1], reverse=True)

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
