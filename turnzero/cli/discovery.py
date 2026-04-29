"""Discovery and preview CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.table import Table

from turnzero.blocks import Block
from turnzero.config import (
    _blocks_dir,
    _bundled_blocks_dir,
    _bundled_index_path,
    _data_dir,
    _index_path,
)
from turnzero.cli.base import (
    DEFAULT_THRESHOLD,
    MAX_PREVIEW_ANTI_PATTERNS,
    MAX_PREVIEW_CONSTRAINTS,
    PREVIEW_TEXT_LIMIT,
    console,
    err_console,
)

discovery_app = typer.Typer(no_args_is_help=True)


def _display_preview(results: list[tuple[Block, float]], threshold: float) -> None:
    """Print a visual preview of suggested blocks."""
    total_weight = sum(b.context_weight for b, _ in results)
    console.print(
        f"\n[bold]TurnZero Suggestions[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n"
    )

    for i, (block, score) in enumerate(results, 1):
        stale_tag = "  [red][STALE][/red]" if block.is_stale() else ""
        # High scores (2.0) indicate Identity Priors
        tier_label = "[magenta]Identity[/magenta]" if score >= 2.0 else "[cyan]Expert[/cyan]"
        
        console.print(
            f"  [bold cyan]{i}.[/bold cyan] [bold]{block.slug}[/bold]{stale_tag}    "
            f"[dim]{tier_label} | score: {score:.2f} | weight: {block.context_weight}[/dim]"
        )
        if block.constraints:
            preview_text = block.constraints[0][:PREVIEW_TEXT_LIMIT]
            console.print(
                f"     [dim]\"{preview_text}{'...' if len(block.constraints[0]) > PREVIEW_TEXT_LIMIT else ''}\"[/dim]"
            )
        console.print()

    console.print(
        "[dim]This is what TurnZero injects at Turn 0 of your AI session.[/dim]\n"
        "[dim]To manage: [/dim][cyan]turnzero review[/cyan]\n"
    )


@discovery_app.command()
def query(
    prompt: str = typer.Argument(..., help="Opening prompt to find blocks for."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Maximum blocks to return."),
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum cosine similarity."
    ),
    context_weight: int = typer.Option(
        4000, "--weight", help="Max total weight across injected blocks."
    ),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Confirm each block before including."
    ),
    strict_intent: bool = typer.Option(
        True, "--strict/--no-strict", help="Only return blocks matching detected intent."
    ),
    rerank: str = typer.Option(
        None,
        "--rerank",
        "-r",
        help="Local LLM model to use for second-stage reranking (e.g. llama3.2).",
    ),
    session: str = typer.Option(
        "default", "--session", "-s", help="Session ID for cumulative ROI tracking."
    ),
) -> None:
    """Suggest Expert Priors for an opening prompt."""
    from turnzero.analytics import SessionAnalytics
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import get_identity_context, load_index
    from turnzero.retrieval import query as _query

    try:
        blocks_dir = _blocks_dir()
        index_path = _index_path()

        if not index_path.exists():
            blocks_dir = _bundled_blocks_dir()
            index_path = _bundled_index_path()

        if not index_path.exists():
            raise FileNotFoundError("No index found. Run: turnzero setup")

        blocks = load_all_blocks(blocks_dir)
        index = load_index(index_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 1. Personal Identity context (unconditional)
    identity_blocks, limit_exceeded = get_identity_context(blocks)
    identity_weight = sum(b.context_weight for b, _ in identity_blocks)

    # 2. Expert Prior context (semantic)
    expert_results = _query(
        prompt,
        index,
        blocks,
        top_k=top_k,
        threshold=threshold,
        context_weight=context_weight - identity_weight,
        strict_intent=strict_intent,
        rerank_model=rerank,
        project_root=Path.cwd(),
        exclude_block_ids={b.slug for b, _ in identity_blocks},
    )

    results = identity_blocks + expert_results

    if not results:
        console.print(f"\n[dim]No blocks found for this prompt.[/dim]\n")
        return

    # Load session analytics
    analytics = SessionAnalytics.load(session, _data_dir())

    # Update session ROI
    analytics.log_injection([b.slug for b, _ in results])
    analytics.save(_data_dir())

    _display_preview(results, threshold)


@discovery_app.command()
def preview(
    prompt: str = typer.Argument(..., help="Opening prompt to preview."),
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum cosine similarity."
    ),
) -> None:
    """Full-content preview of what would be injected for a prompt."""
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import get_identity_context, load_index
    from turnzero.retrieval import query as _query

    try:
        blocks = load_all_blocks(_blocks_dir())
        index = load_index(_index_path())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Use the same dual-stream logic as query()
    identity_blocks, _ = get_identity_context(blocks)
    identity_weight = sum(b.context_weight for b, _ in identity_blocks)
    
    expert_results = _query(
        prompt, index, blocks, 
        threshold=threshold,
        context_weight=4000 - identity_weight,
        project_root=Path.cwd(),
        exclude_block_ids={b.slug for b, _ in identity_blocks},
    )
    
    results = identity_blocks + expert_results

    if not results:
        console.print(f"\n[dim]No blocks found for this prompt.[/dim]\n")
        return

    total_weight = sum(b.context_weight for b, _ in results)
    console.print(
        f"\n[bold]TurnZero Preview[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n"
    )

    for block, score in results:
        # Identity priors get magenta color, Experts get cyan
        color = "magenta" if score >= 2.0 else "cyan"
        title = block.slug
        console.print(
            f"  [bold {color}]{title}[/bold {color}]  [dim]{block.domain}/{block.intent}  score={score:.2f}[/dim]"
        )

        constraints = block.constraints
        anti_patterns = block.anti_patterns

        if constraints:
            console.print("    [green]constraints:[/green]")
            for c in constraints[:MAX_PREVIEW_CONSTRAINTS]:
                console.print(f"      • {c}")
            if len(constraints) > MAX_PREVIEW_CONSTRAINTS:
                console.print(f"      [dim]… +{len(constraints) - MAX_PREVIEW_CONSTRAINTS} more[/dim]")

        if anti_patterns:
            console.print("    [red]anti-patterns:[/red]")
            for a in anti_patterns[:MAX_PREVIEW_ANTI_PATTERNS]:
                console.print(f"      • {a}")
            if len(anti_patterns) > MAX_PREVIEW_ANTI_PATTERNS:
                console.print(f"      [dim]… +{len(anti_patterns) - MAX_PREVIEW_ANTI_PATTERNS} more[/dim]")

        console.print()


@discovery_app.command()
def show(
    slug: str = typer.Argument(..., help="Block slug to display."),
) -> None:
    """Display full content of a block."""
    from turnzero.blocks import load_all_blocks

    try:
        blocks = load_all_blocks(_blocks_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if slug not in blocks:
        console.print(f"[red]Block not found: {slug}[/red]")
        available = sorted(blocks.keys())
        console.print(f"[dim]Available: {', '.join(available[:10])}...[/dim]")
        raise typer.Exit(1)

    block = blocks[slug]
    stale = "  [red][STALE][/red]" if block.is_stale() else ""

    console.print(f"\n[bold]{block.slug}[/bold]  v{block.version}{stale}")
    console.print(
        f"[dim]tier: {block.tier}  domain: {block.domain}  intent: {block.intent}  weight: {block.context_weight}[/dim]"
    )
    console.print(f"[dim]verified: {block.last_verified}  confidence: {block.confidence:.2f}[/dim]\n")

    if block.rationale:
        console.print(f"[italic]{block.rationale}[/italic]\n")

    if block.constraints:
        console.print("[bold green]Constraints:[/bold green]")
        for c in block.constraints:
            console.print(f"  • {c}")
        console.print()

    if block.anti_patterns:
        console.print("[bold red]Anti-patterns:[/bold red]")
        for a in block.anti_patterns:
            console.print(f"  • {a}")
        console.print()

    if block.doc_anchors:
        console.print("[bold cyan]Documentation:[/bold cyan]")
        for anchor in block.doc_anchors:
            console.print(f"  • {anchor.url}")
        console.print()


@discovery_app.command()
def inject(
    slugs: list[str] = typer.Argument(..., help="One or more block slugs to inject."),
) -> None:
    """Print formatted Expert Priors ready for injection into an AI session."""
    from turnzero.blocks import load_all_blocks

    try:
        blocks = load_all_blocks(_blocks_dir())
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    parts: list[str] = []
    for slug in slugs:
        if slug not in blocks:
            err_console.print(f"[red]Block not found: {slug}[/red]")
            continue
        parts.append(blocks[slug].to_injection_text())

    if parts:
        print("\n\n---\n\n".join(parts))


@discovery_app.command()
def stats() -> None:
    """Show injection history and block library statistics."""
    import contextlib
    import json
    import time
    from collections import Counter
    from rich import box
    from rich.table import Table

    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index

    data_dir = _data_dir()

    # ── Live injection log ───────────────────────────────────────────────
    log_path = data_dir / "hook_log.jsonl"
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))

    now = time.time()
    week_ago = now - 7 * 86400

    sessions_total = len(entries)
    sessions_week = sum(1 for e in entries if e.get("ts", 0) >= week_ago)
    priors_total = sum(len(e.get("blocks", [])) for e in entries)
    priors_week = sum(len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago)

    block_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for e in entries:
        for slug in e.get("blocks", []):
            block_counts[slug] += 1
        for d in e.get("domains", []):
            domain_counts[d] += 1

    top_blocks = block_counts.most_common(3)
    top_domains = [d for d, _ in domain_counts.most_common(5)]

    est_turns = round(priors_total * 0.5)
    est_tokens = priors_total * 0.5 * 1500

    # ── Tool call log ─────────────────────────────────────────────────────
    tool_log_path = data_dir / "tool_call_log.jsonl"
    tool_entries: list[dict[str, Any]] = []
    if tool_log_path.exists():
        for line in tool_log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                tool_entries.append(json.loads(line))

    tool_calls_total = len(tool_entries)
    tokens_in_total = sum(e.get("tokens_in", 0) for e in tool_entries)
    tokens_out_total = sum(e.get("tokens_out", 0) for e in tool_entries)

    # ── Library stats ─────────────────────────────────────────────────────
    try:
        blocks = load_all_blocks(_blocks_dir())
    except FileNotFoundError:
        blocks = {}

    stale = [b for b in blocks.values() if b.is_stale()]
    personal_count = sum(1 for b in blocks.values() if b.tier == "personal")

    # ── Render ────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]📎 TurnZero — Stats[/bold]\n")

    usage = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    usage.add_column("", style="dim", min_width=26)
    usage.add_column("", justify="right")

    if sessions_total == 0:
        usage.add_row("Sessions with injection", "[dim]none yet[/dim]")
    else:
        usage.add_row("Sessions with injection", f"[bold]{sessions_total}[/bold]  [dim](+{sessions_week} this week)[/dim]")
        usage.add_row("Priors applied", f"[bold]{priors_total}[/bold]  [dim](+{priors_week} this week)[/dim]")
        usage.add_row("Est. turns saved", f"[bold green]~{est_turns}[/bold green]  [dim](~{int(est_tokens/1000)}k tokens)[/dim]")
        if top_domains:
            usage.add_row("Top domains", "  ".join(f"[cyan]{d}[/cyan]" for d in top_domains))

    console.print(usage)

    console.print()
    lib = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    lib.add_column("", style="dim", min_width=26)
    lib.add_column("", justify="right")
    lib.add_row("Block library", f"{len(blocks)} blocks total")
    lib.add_row("  - Expert Priors", str(len(blocks) - personal_count))
    lib.add_row("  - Personal Priors", f"[magenta]{personal_count}[/magenta]")
    lib.add_row("Stale blocks (>90d)", f"[red]{len(stale)}[/red]" if stale else "[green]0[/green]")
    
    try:
        index = load_index(_index_path())
        lib.add_row("Index entries", str(len(index)))
    except FileNotFoundError:
        lib.add_row("Index", "[yellow]not built[/yellow]")

    console.print(lib)
    console.print()
