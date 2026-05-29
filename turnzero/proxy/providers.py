"""Provider URL resolution — data-driven rule list evaluated in order.

Adding a new provider: add one entry to DEFAULT_PROVIDER_RULES with url + label.
Nothing else needs to change — resolve_provider_url and provider_label_for_url
both derive from the same list.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Provider URL constants — single source of truth for all provider URLs.
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
OPENAI_API_URL = "https://api.openai.com/v1"
GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# ---------------------------------------------------------------------------
# Rule list — evaluated top-to-bottom; first match wins.
# Each rule carries a label used by provider_label_for_url().
# User config can prepend custom rules (see resolve_provider_url).
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER_RULES: list[dict[str, str]] = [
    {"key_prefix": "sk-ant-",   "url": ANTHROPIC_API_URL, "label": "anthropic"},
    {"model_prefix": "claude-", "url": ANTHROPIC_API_URL, "label": "anthropic"},
    {"model_prefix": "gemini-", "url": GOOGLE_API_URL,    "label": "google"},
    {"model_prefix": "gpt-",    "url": OPENAI_API_URL,    "label": "openai"},
    {"model_prefix": "o1",      "url": OPENAI_API_URL,    "label": "openai"},
    {"model_prefix": "o3",      "url": OPENAI_API_URL,    "label": "openai"},
    {"default": "true",         "url": OPENAI_API_URL,    "label": "openai"},
]


def resolve_provider_url(
    auth_header: str | None,
    model: str,
    user_rules: list[dict[str, str]] | None = None,
) -> str:
    """Return provider base URL by matching rules in order.

    Args:
        auth_header: Raw Authorization header value (e.g. "Bearer sk-ant-...").
        model: Model name from the request body (e.g. "claude-3-5-sonnet").
        user_rules: Optional user-defined rules prepended before defaults.

    Returns:
        Provider base URL (no trailing slash).
    """
    rules = (user_rules or []) + DEFAULT_PROVIDER_RULES
    key = (auth_header or "").removeprefix("Bearer ").strip()
    for rule in rules:
        if "key_prefix" in rule and key.startswith(rule["key_prefix"]):
            return rule["url"]
        if "model_prefix" in rule and model.startswith(rule["model_prefix"]):
            return rule["url"]
        if "default" in rule:
            return rule["url"]
    return DEFAULT_PROVIDER_RULES[-1]["url"]


def provider_label_for_url(
    url: str,
    user_rules: list[dict[str, str]] | None = None,
) -> str:
    """Return short provider label for a resolved URL.

    Scans rules in order — first match on url wins. Falls back to 'custom'
    for URLs not in the rule list (e.g. local Ollama or private endpoints).

    Args:
        url: Resolved provider base URL (from resolve_provider_url).
        user_rules: Optional user-defined rules prepended before defaults.

    Returns:
        Short label e.g. "anthropic", "openai", "google", "custom".
    """
    normalised = url.rstrip("/")
    rules = (user_rules or []) + DEFAULT_PROVIDER_RULES
    for rule in rules:
        if rule.get("url", "").rstrip("/") == normalised:
            return rule.get("label", "custom")
    return "custom"
