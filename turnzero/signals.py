"""Keyword signal data for intent classification and implementation gate.

All frozensets and keyword mappings live here — data-only, no logic.
retrieval.py imports from this module and stays logic-only.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Intent classifier keywords
# ---------------------------------------------------------------------------

INTENT_SIGNALS: dict[str, list[str]] = {
    "build": [
        "build", "create", "scaffold", "implement", "add",
        "make", "set up", "write", "develop", "integrate",
    ],
    "debug": [
        "error", "bug", "fix", "not working", "failing", "broken",
        "why", "problem", "crash", "exception", "undefined", "issue",
        "persisting", "help with", "correct", "leaked", "exposed",
        "compromised", "breached", "accidentally",
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

# ---------------------------------------------------------------------------
# Implementation gate — Tier 1 pre-filter
# ---------------------------------------------------------------------------

_SOCIAL_PATTERNS: frozenset[str] = frozenset({
    "how are you", "good morning", "good afternoon", "good evening",
    "good night", "how's it going", "how is it going",
    "what's up", "whats up", "hey there", "hi there",
    "tell me a joke", "thanks", "thank you",
    "you're welcome", "youre welcome",
    "sounds good", "sounds great", "got it", "makes sense",
    "ok", "okay", "sure", "yes", "no",
    "great", "awesome", "nice", "cool", "interesting", "noted",
})

# ---------------------------------------------------------------------------
# Implementation gate — Tier 2a action / problem signals
# ---------------------------------------------------------------------------

_IMPL_ACTION_SIGNALS: frozenset[str] = frozenset({
    "build", "building", "create", "creating", "scaffold",
    "implement", "implementing", "set up", "setting up",
    "configure", "configuring", "deploy", "deploying",
    "write", "writing", "develop", "developing",
    "migrate", "migrating", "integrate", "integrating",
    "add", "adding", "start", "starting", "launch", "launching",
    "init", "generate", "connect", "connecting",
    "install", "installing", "run", "running",
    "refactor", "refactoring", "convert", "converting",
    "upgrade", "upgrading", "wire up", "hook up", "spin up",
    "harden", "hardening", "scan", "scanning",
    "audit", "auditing", "pentest", "pentesting",
    "rotate", "rotating", "remediate", "remediating",
    "patch", "patching", "mitigate", "mitigating",
    "investigate", "investigating", "secure", "securing",
    "protect", "protecting", "analyze", "analyzing",
    "analyse", "analysing", "exploit", "exploiting",
    "assess", "assessing",
    # Auth / identity protocols — always professional context
    "oauth", "oidc", "pkce", "jwt", "saml",
    "authenticate", "authenticating", "authorize", "authorizing",
    "provision", "provisioning",
    # Infrastructure
    "terraform", "kubernetes", "kubectl", "helm",
    "containerize", "containerizing", "orchestrate", "orchestrating",
})

_IMPL_PROBLEM_SIGNALS: frozenset[str] = frozenset({
    "keeps", "throwing", "throws", "not working", "failing", "broken",
    "returns", "return", "crashes", "crashing",
    "doesn't work", "does not work", "can't", "cannot",
    "stuck", "blocked", "error", "exception", "bug",
    "not persisting", "not rendering", "not loading", "not connecting",
    "wrong", "incorrect", "unexpected", "undefined",
    "null pointer", "fix", "fixing", "debug", "debugging", "issue",
    "leaked", "exposed", "compromised", "breached", "accidentally",
})

# ---------------------------------------------------------------------------
# Implementation gate — Tier 2b question patterns
# ---------------------------------------------------------------------------

_QUESTION_PATTERNS: frozenset[str] = frozenset({
    "?",
    "how do i", "how do we", "how should i", "how should we",
    "how can i", "how can we", "how to",
    "what is the", "what are the", "what should i", "what should we",
    "what's the", "whats the", "what would",
    "which ", "when should", "when do i", "when do we",
    "should i ", "should we ", "can i ", "can we ",
    "help me", "help us",
    "i need to", "we need to", "i want to", "we want to",
    "i'm trying to", "im trying to", "i am trying to", "we are trying to",
    "best way to", "best approach", "best practice",
    "recommend", "recommendation", "advice on", "guidance on",
    "difference between", "when to use", "pros and cons",
})

# Phrases that act as "professional starter" bypasses in _has_substance.
# Subset of _QUESTION_PATTERNS without trailing spaces, used for startswith checks.
_SHORT_QUESTION_STARTERS: frozenset[str] = frozenset({
    "how to", "what is", "should i", "can i",
})

# ---------------------------------------------------------------------------
# Computed sets (derived — do not edit directly)
# ---------------------------------------------------------------------------

_ALL_SIGNALS: frozenset[str] = _IMPL_ACTION_SIGNALS | _IMPL_PROBLEM_SIGNALS

# Fuzzy matching constants
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
