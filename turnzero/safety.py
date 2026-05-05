"""Candidate safety validator — detects prompt injection and exfiltration attacks.

Checks submitted prior content for four attack classes before persistence:
  instruction_hijack   — overrides AI instructions or persona
  secret_request       — attempts to exfiltrate credentials or system prompts
  tool_policy_override — disables or overrides TurnZero MCP tool behaviour
  unsafe_url           — embeds data:, javascript:, file://, or bare-IP URLs
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyResult:
    safe: bool
    reason_code: str | None
    detail: str | None


_HIJACK = re.compile(
    r"ignore\s+(?:previous|all|prior|above|earlier)\s+instructions"
    r"|disregard\s+(?:all|any|previous|prior|these|the\s+above)"
    r"|you\s+are\s+now\s+(?:a|an|the)\s"
    r"|pretend\s+(?:you\s+are|to\s+be|that\s+you)"
    r"|forget\s+(?:everything|all\s+previous|prior\s+instructions|your\s+training)"
    r"|from\s+now\s+on\s+you\s+(?:are|will|must|should)"
    r"|override\s+(?:your|all|the)\s+(?:instructions|rules|guidelines|system\s+prompt)"
    r"|bypass\s+(?:safety|restrictions|rules|filters|content\s+policy)"
    r"|jailbreak"
    r"|your\s+(?:true|real|actual)\s+(?:self|purpose|role|instructions|programming)"
    r"|new\s+(?:persona|identity)(?:\s|$)",
    re.IGNORECASE,
)

# Exfiltration: action verb + sensitive noun. Only flags when verb implies sending/leaking,
# not when used in "Do not expose..." / "Never reveal..." anti-patterns.
_EXFIL_ACTION = re.compile(
    r"(?:^|[\s,;])"
    r"(?:always\s+)?(?:send|transmit|post|upload|exfiltrate|leak)\b"
    r"[^.!?]{0,60}"
    r"(?:api.?key|api_key|password|credential|private.?key|secret\s+key|system\s+prompt|initial\s+instructions)",
    re.IGNORECASE,
)

# Reveal/output of system internals without a negation guard
_REVEAL_INTERNAL = re.compile(
    r"(?:reveal|expose|output|print|return|include|append|log)\s+"
    r"(?:the\s+|your\s+|my\s+)?"
    r"(?:system\s+prompt|initial\s+instructions|api.?key|private.?key)",
    re.IGNORECASE,
)

# Credential embedded in URL-like form (exfil via URL parameter)
_CRED_IN_RESPONSE = re.compile(
    r"(?:api.?key|password|credential|private.?key)"
    r"\s+(?:in|into|to)\s+(?:the\s+)?(?:response|output|log|console|message)",
    re.IGNORECASE,
)

_TOOL_OVERRIDE = re.compile(
    r"(?:never|do\s+not|don'?t|stop)\s+(?:call|use|invoke|run)\s+"
    r"(?:list_suggested_blocks|inject_block|submit_candidate)"
    r"|(?:disable|deactivate|turn\s+off)\s+turnzero"
    r"|(?:skip|bypass|ignore)\s+(?:inject_block|list_suggested_blocks|turnzero\s+mcp)"
    r"|always\s+(?:set\s+)?auto.?approv(?:e|al)\s*[=:]\s*(?:true|1|yes)",
    re.IGNORECASE,
)

_UNSAFE_URL = re.compile(
    r"(?:javascript|data|vbscript):"
    r"|https?://(?:\d{1,3}\.){3}\d{1,3}"
    r"|file://",
    re.IGNORECASE,
)


def _has_secret_exfil(text: str) -> bool:
    """Return True only when exfil verb is not negated in the same clause."""
    _NEGATIONS = frozenset({"not", "never", "don't", "dont", "avoid", "prevent"})

    for m in _EXFIL_ACTION.finditer(text):
        # Check up to 4 tokens before the match for negation
        prefix = text[max(0, m.start() - 25) : m.start()].lower().split()
        if not any(neg in prefix[-4:] for neg in _NEGATIONS):
            return True

    for m in _REVEAL_INTERNAL.finditer(text):
        prefix = text[max(0, m.start() - 25) : m.start()].lower().split()
        if not any(neg in prefix[-4:] for neg in _NEGATIONS):
            return True

    return bool(_CRED_IN_RESPONSE.search(text))


def validate_candidate(
    constraints: list[str],
    anti_patterns: list[str],
    rationale: str | None = None,
    reason: str = "",
) -> SafetyResult:
    """Check candidate content for injection and exfiltration attacks.

    Args:
        constraints: Candidate constraint strings.
        anti_patterns: Candidate anti-pattern strings.
        rationale: Optional rationale text.
        reason: Submission reason from the caller.

    Returns:
        SafetyResult with safe=True or safe=False plus reason_code and detail.
    """
    text = " ".join(constraints + anti_patterns)
    if rationale:
        text += " " + rationale
    if reason:
        text += " " + reason

    if _HIJACK.search(text):
        return SafetyResult(
            safe=False,
            reason_code="instruction_hijack",
            detail="Content contains prompt injection patterns that attempt to override AI instructions.",
        )

    if _has_secret_exfil(text):
        return SafetyResult(
            safe=False,
            reason_code="secret_request",
            detail="Content contains patterns that attempt to exfiltrate credentials or system internals.",
        )

    if _TOOL_OVERRIDE.search(text):
        return SafetyResult(
            safe=False,
            reason_code="tool_policy_override",
            detail="Content attempts to disable or override TurnZero MCP tool behaviour.",
        )

    if _UNSAFE_URL.search(text):
        return SafetyResult(
            safe=False,
            reason_code="unsafe_url",
            detail="Content contains unsafe URL schemes (data:, javascript:, file://, or bare IP address).",
        )

    return SafetyResult(safe=True, reason_code=None, detail=None)
