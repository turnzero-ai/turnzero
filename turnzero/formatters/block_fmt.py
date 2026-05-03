"""Presentation layer for Block — formatting to injection text and search text."""

from __future__ import annotations

from turnzero.blocks import Block


def to_search_text(block: Block) -> str:
    """Text used when embedding a block into the index.

    Phrased as a natural-language query matching how users open AI sessions.
    Intent-aware framing: build=imperative, debug=problem statement,
    migrate=transition language, review=evaluation request.
    """
    tag_str = " ".join(block.tags)

    intent_prefix = {
        "build": f"build a {block.domain} {tag_str} project",
        "debug": f"fix {block.domain} {tag_str} error or problem",
        "migrate": f"migrate or upgrade {block.domain} {tag_str} project",
        "review": f"review or check {block.domain} {tag_str} code",
    }.get(block.intent, f"{block.intent} {block.domain} {tag_str}")

    if block.intent == "debug" and block.anti_patterns:
        hint = block.anti_patterns[0].split(".")[0][:100]
    elif block.constraints:
        hint = block.constraints[0].split(".")[0][:100]
    else:
        return intent_prefix

    return f"{intent_prefix}: {hint}"


def to_injection_text(block: Block) -> str:
    """Formatted Expert Prior ready to inject into an AI session.

    Uses a hierarchical structure (Identity -> Constraints -> Task)
    to maximize LLM anchoring based on research (Ni, 2026).
    """
    domain_title = block.domain.replace("-", " ").title()
    role = f"Expert {domain_title} {block.intent.title()} Assistant"

    lines: list[str] = [
        "# EXPERT_PRIOR_IDENTITY",
        f"Role: {role}",
        f"Slug: {block.slug} (v{block.version})",
        "",
        "# SESSION_CONSTRAINTS",
    ]

    if block.constraints:
        for c in block.constraints:
            lines.append(f"- {c}")

    if block.rationale:
        lines.append("")
        lines.append("# RATIONALE")
        lines.append(block.rationale)

    if block.anti_patterns:
        lines.append("")
        lines.append("# ANTI_PATTERNS")
        for a in block.anti_patterns:
            prefix = "" if a.lower().startswith("do not") else "Do not: "
            lines.append(f"- {prefix}{a}")

    lines.extend(
        [
            "",
            "# VALIDATION_TASK",
            f"Prioritize the constraints and anti-patterns above for the duration of this {block.domain} {block.intent} session.",
        ]
    )

    if block.doc_anchors:
        lines.append("")
        lines.append("# REFERENCE_DOCS")
        for anchor in block.doc_anchors:
            lines.append(f"- {anchor.url}")

    return "\n".join(lines)
