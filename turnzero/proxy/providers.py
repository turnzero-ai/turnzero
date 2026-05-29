"""Provider URL resolution — data-driven rule list evaluated in order."""

from __future__ import annotations

# Rules evaluated top-to-bottom; first match wins.
# User config can prepend custom rules (see resolve_provider_url).
DEFAULT_PROVIDER_RULES: list[dict[str, str]] = [
    {"key_prefix": "sk-ant-",   "url": "https://api.anthropic.com/v1"},
    {"model_prefix": "claude-", "url": "https://api.anthropic.com/v1"},
    {"model_prefix": "gemini-", "url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    {"model_prefix": "gpt-",    "url": "https://api.openai.com/v1"},
    {"model_prefix": "o1",      "url": "https://api.openai.com/v1"},
    {"model_prefix": "o3",      "url": "https://api.openai.com/v1"},
    {"default": "true",         "url": "https://api.openai.com/v1"},
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
