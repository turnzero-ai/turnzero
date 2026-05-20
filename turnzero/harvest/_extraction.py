"""LLM extraction backends — provider-agnostic harvest extraction."""

from __future__ import annotations

import os

EXTRACTION_PROMPT = """\
You are a TurnZero Expert Prior extractor. Your job is to analyse an AI \
conversation and extract reusable Expert Priors that represent knowledge an \
expert would inject at the START of that session to prevent mid-session corrections.\
Expert Priors can be from any domain — software, law, medicine, finance, design, \
writing, science, or any other field where domain-specific knowledge prevents mistakes.

An Expert Prior captures:
- constraints: rules the AI should follow (version-specific, domain-specific)
- anti_patterns: things the AI should NOT do (the wrong library, the deprecated API)
- rationale: research-backed explanation of why the rule exists
- doc_anchors: official documentation URLs referenced in the conversation

PERSONAL PRIORS (domain: persona):
If the conversation contains the user's idiosyncratic preferences, personal coding
style, or project-specific workflow rules (e.g. "I prefer 2-space indents",
"Never use comments in my code", "Always use mypy strict"), extract these as
Personal Priors with domain: persona.

INTENT RULES (pick exactly one):
- build:   conversation is about creating something new
- debug:   conversation is about fixing an error or unexpected behaviour
- migrate: conversation is about upgrading versions or switching libraries
- review:  conversation is about evaluating or improving existing code

CONFLICT RULES:
- conflicts_with lists block IDs that would give contradictory instructions
- Most blocks have an empty conflicts_with list
- Only flag a conflict when two blocks would give opposite instructions for \
the SAME decision (e.g. "use bind mounts" vs "use named volumes")

OUTPUT FORMAT — respond with ONLY valid YAML, no prose, no markdown fences:

- id: <descriptive-slug>-<intent>
  version: "1.0.0"
  domain: <primary technology, lowercase, single word>
  intent: <build|debug|migrate|review>
  last_verified: "{today}"
  verification_level: "observed"
  tags: [<tag1>, <tag2>, ...]
  context_weight: <estimated token count of this block, integer>
  conflicts_with: []
  requires: []
  constraints:
    - "<constraint 1>"
    - "<constraint 2>"
  anti_patterns:
    - "<anti-pattern 1>"
    - "<anti-pattern 2>"
  doc_anchors:
    - url: "<url if mentioned in conversation>"
      verified: "{today}"

EXTRACTION RULES:
1. Extract 1-3 blocks maximum. Quality over quantity.
2. Each constraint must be specific, version-anchored where possible, \
and name both the wrong pattern AND the right pattern.
3. Each anti_pattern must start with "Do not".
4. Ignore generic advice that applies to all software.
5. Focus on the mid-session CORRECTIONS — what did the user have to clarify \
after the AI got it wrong? Those corrections are your highest-signal source.
6. context_weight: estimate 4 tokens per word across all constraints + anti_patterns.
7. Do NOT extract personal preferences, individual habits, team conventions, or \
OS-specific paths. A valid Expert Prior must be true for ANYONE working in \
that domain — not just this one person.
8. If the session contains no mid-session corrections and no domain-specific \
gotchas, output nothing. An empty response is better than a junk block.
9. SCOPE CHECK — if the session is casual conversation, venting, or contains \
no domain-specific knowledge that would prevent an AI mistake, output nothing.

GOOD Expert Prior (specific, universally true for the domain, based on a real correction):
  domain: nextjs — "Do not use getServerSideProps — Pages Router only, does not exist in App Router"
  domain: law — "In Swiss employment law, non-compete clauses are unenforceable beyond 3 years"
  domain: finance — "Options Delta is not linear near expiration — gamma accelerates rapidly"
  domain: medicine — "eGFR thresholds for CKD staging differ between CKD-EPI 2009 and 2021 equations"

BAD Expert Prior (personal preference or generic advice):
  "Always write unit tests" — generic, not domain-specific
  "Use VSCode with Prettier" — personal tooling preference
  "Be more concise in your writing" — personal style feedback

CONVERSATION TO ANALYSE:
---
{conversation}
---

Respond with ONLY the YAML block(s). No explanation."""


def extract_with_llm(
    conversation: str,
    model: str = "llama3.2",
    max_chars: int = 8000,
    backend: str = "auto",
) -> str:
    """Extract Expert Prior candidates from a conversation using an LLM.

    backend="auto" priority: Anthropic API → OpenAI API → ollama (local).
    Pass backend="ollama" to force local extraction regardless of API keys.

    Raises RuntimeError with actionable instructions if no backend is available.
    """
    from datetime import date

    today = date.today().isoformat()
    truncated = conversation[:max_chars]
    if len(conversation) > max_chars:
        truncated += "\n\n[... conversation truncated for context window ...]"
    prompt = EXTRACTION_PROMPT.format(conversation=truncated, today=today)

    if backend == "ollama":
        return _extract_ollama(prompt, model)

    if backend == "anthropic" or (
        backend == "auto" and os.environ.get("ANTHROPIC_API_KEY")
    ):
        return _extract_anthropic(prompt)

    if backend == "openai" or (backend == "auto" and os.environ.get("OPENAI_API_KEY")):
        return _extract_openai(prompt)

    # Local fallback
    try:
        return _extract_ollama(prompt, model)
    except RuntimeError:
        pass

    raise RuntimeError(
        "No LLM backend available for harvest extraction.\n\n"
        "Option 1 (Anthropic, fast):\n"
        "  export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "Option 2 (OpenAI):\n"
        "  export OPENAI_API_KEY=sk-...\n\n"
        "Option 3 (local, free):\n"
        "  ollama serve && ollama pull llama3.2"
    )


def _extract_ollama(prompt: str, model: str) -> str:
    try:
        import ollama as _ollama
    except ImportError as e:
        raise RuntimeError("ollama package not installed") from e
    try:
        response = _ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        return str(response["message"]["content"])
    except Exception as e:
        raise RuntimeError(f"ollama unavailable: {e}") from e


def _extract_openai(prompt: str) -> str:
    import httpx

    api_key = os.environ["OPENAI_API_KEY"]
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        raise RuntimeError(f"OpenAI extraction failed: {e}") from e


def _extract_anthropic(prompt: str) -> str:
    import httpx

    api_key = os.environ["ANTHROPIC_API_KEY"]
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return str(resp.json()["content"][0]["text"])
    except Exception as e:
        raise RuntimeError(f"Anthropic extraction failed: {e}") from e
