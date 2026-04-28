"""Discovery and status commands (query, show, inject, stats, preview)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.table import Table

from turnzero.cli.base import (
    DEFAULT_THRESHOLD,
    MAX_PREVIEW_ANTI_PATTERNS,
    MAX_PREVIEW_CONSTRAINTS,
    PREVIEW_TEXT_LIMIT,
    _blocks_dir,
    _bundled_blocks_dir,
    _bundled_index_path,
    _data_dir,
    _index_path,
    console,
    err_console,
)


def preview(
    prompt: str = typer.Argument(..., help="Opening prompt to preview injection for."),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Max blocks to show."),
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum similarity score."
    ),
) -> None:
    """Preview which Expert Priors would be injected for a prompt.

    Uses the pre-built index bundled with the package.
    Requires an embedding backend:
      - local: `ollama serve && ollama pull nomic-embed-text`
      - cloud: OPENAI_API_KEY
    This preview path does not build embeddings itself; it reads the bundled
    index and uses whatever backend is already available.

    \b
    Example:
      turnzero preview "Building a REST API with FastAPI and PostgreSQL"
      turnzero preview "goroutine leaking in my HTTP handler"
    """
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index
    from turnzero.retrieval import query as _query

    index_path = _bundled_index_path()
    blocks_dir = _bundled_blocks_dir()

    if not index_path.exists():
        err_console.print("[red]No index found. Run: turnzero setup[/red]")
        raise typer.Exit(1)

    blocks = load_all_blocks(blocks_dir)
    index = load_index(index_path)
    results = _query(
        prompt,
        index,
        blocks,
        top_k=top_k,
        threshold=threshold,
        strict_intent=False,
    )

    if not results:
        console.print(
            f"\n[dim]No blocks above threshold {threshold} for this prompt.[/dim]"
        )
        console.print(
            "[dim]Try a more specific technical prompt, or lower --threshold.[/dim]\n"
        )
        return

    total_weight = sum(b.context_weight for b, _ in results)
    console.print(
        f"\n[bold]TurnZero Preview[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n"
    )

    for block, score in results:
        title = getattr(block, "title", None) or block.slug
        console.print(
            f"  [bold cyan]{title}[/bold cyan]  [dim]{block.domain}/{block.intent}  score={score:.2f}[/dim]"
        )

        constraints = block.constraints
        anti_patterns = block.anti_patterns

        if constraints:
            console.print("    [green]constraints:[/green]")
            for c in constraints[:MAX_PREVIEW_CONSTRAINTS]:
                console.print(f"      • {c}")
            if len(constraints) > MAX_PREVIEW_CONSTRAINTS:
                console.print(
                    f"      [dim]… +{len(constraints) - MAX_PREVIEW_CONSTRAINTS} more[/dim]"
                )

        if anti_patterns:
            console.print("    [red]anti-patterns:[/red]")
            for a in anti_patterns[:MAX_PREVIEW_ANTI_PATTERNS]:
                console.print(f"      • {a}")
            if len(anti_patterns) > MAX_PREVIEW_ANTI_PATTERNS:
                console.print(
                    f"      [dim]… +{len(anti_patterns) - MAX_PREVIEW_ANTI_PATTERNS} more[/dim]"
                )

        console.print()

    console.print(
        "[dim]This is what TurnZero injects at Turn 0 of your AI session.[/dim]\n"
        "[dim]To activate: [/dim][cyan]turnzero setup[/cyan]\n"
    )


def query(
    prompt: str = typer.Argument(..., help="Opening prompt to find blocks for."),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Maximum blocks to return."),
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
    from turnzero.analytics import SessionAnalytics, get_global_roi
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import classify_intent, load_index
    from turnzero.retrieval import query as _query

    try:
        blocks_dir = _blocks_dir()
        index_path = _index_path()

        if not index_path.exists():
            # Fallback to bundled data
            blocks_dir = _bundled_blocks_dir()
            index_path = _bundled_index_path()

        if not index_path.exists():
            raise FileNotFoundError("No index found. Run: turnzero setup")

        blocks = load_all_blocks(blocks_dir)
        index = load_index(index_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Load session analytics
    analytics = SessionAnalytics.load(session, _data_dir())

    intent = classify_intent(prompt)
    results = _query(
        prompt,
        index,
        blocks,
        top_k=top_k,
        threshold=threshold,
        context_weight=context_weight,
        strict_intent=strict_intent,
        project_root=Path.cwd(),
        rerank_model=rerank,
    )

    if not results:
        console.print(
            f"[yellow]No blocks found above threshold {threshold:.2f} (intent: {intent}).[/yellow]"
        )
        console.print("[dim]Try --no-strict or adding more blocks to data/blocks/[/dim]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]Suggested Expert Priors[/bold] for: [italic]\"{prompt[:80]}\"[/italic]"
    )
    console.print(f"[dim]Intent detected: {intent} | Session: {session}[/dim]\n")

    selected = []
    for i, (block, score) in enumerate(results, 1):
        stale_tag = "  [red][STALE][/red]" if block.is_stale() else ""
        console.print(
            f"  [bold cyan]{i}.[/bold cyan] [bold]{block.slug}[/bold]{stale_tag}    "
            f"[dim]score: {score:.2f}  {block.context_weight} weight[/dim]"
        )
        console.print(f"     [dim]{', '.join(block.tags)}[/dim]")
        if block.constraints:
            preview_text = block.constraints[0][:PREVIEW_TEXT_LIMIT]
            console.print(
                f"     [dim]\"{preview_text}{'...' if len(block.constraints[0]) > PREVIEW_TEXT_LIMIT else ''}\"[/dim]"
            )
        console.print()

        if interactive:
            include = typer.confirm(f"  Inject block {i}?", default=True)
            if include:
                selected.append(block)
        else:
            selected.append(block)

    if selected:
        # Log injection to session
        analytics.log_injection([b.slug for b in selected])
        analytics.save(_data_dir())

    total_weight = sum(b.context_weight for b in selected)
    weight_color = "red" if total_weight > context_weight * 0.9 else "dim"
    console.print(
        f"[{weight_color}]Total injection weight: {total_weight:,}[/{weight_color}]"
    )

    roi = analytics.calculate_roi()
    global_roi = get_global_roi(_data_dir())

    console.print("\n[bold green]Estimated savings (rough heuristic):[/bold green]")
    console.print(
        f"  [dim]• Session:  ~{roi['tokens_saved']:,} tokens | ~{roi['minutes_saved']} min ({roi['turns_saved']} turns)[/dim]"
    )
    console.print(
        f"  [dim]• All time: ~{global_roi['total_minutes_saved']:,} min across {global_roi['total_sessions']} sessions[/dim]"
    )

    if selected:
        ids = " ".join(b.slug for b in selected)
        console.print(f"\nRun: [bold green]turnzero inject {ids}[/bold green]")


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
        console.print(f"[dim]Available: {', '.join(sorted(blocks))}[/dim]")
        raise typer.Exit(1)

    block = blocks[slug]
    stale = "  [red][STALE][/red]" if block.is_stale() else ""

    console.print(f"\n[bold]{block.slug}[/bold]  v{block.version}{stale}")
    console.print(
        f"[dim]domain: {block.domain}  intent: {block.intent}  weight: {block.context_weight}[/dim]"
    )
    console.print(f"[dim]hash: {block.hash}[/dim]")
    console.print(f"[dim]tags: {', '.join(block.tags)}[/dim]")
    console.print(f"[dim]verified: {block.last_verified}[/dim]")
    if block.provides:
        console.print(f"[dim]provides: {', '.join(block.provides)}[/dim]")
    if block.conflicts_with_tags:
        console.print(
            f"[dim]conflicts with tags: {', '.join(block.conflicts_with_tags)}[/dim]"
        )
    if block.conflicts_with:
        console.print(
            f"[dim]conflicts with slugs: {', '.join(block.conflicts_with)}[/dim]"
        )
    console.print()

    if block.constraints:
        console.print("[bold]Constraints:[/bold]")
        for c in block.constraints:
            console.print(f"  • {c}")
        console.print()

    if block.anti_patterns:
        console.print("[bold]Anti-patterns:[/bold]")
        for a in block.anti_patterns:
            console.print(f"  • {a}")
        console.print()

    if block.doc_anchors:
        console.print("[bold]Docs:[/bold]")
        for anchor in block.doc_anchors:
            console.print(f"  • {anchor.url}")


def inject(
    slugs: list[str] = typer.Argument(..., help="One or more block slugs to inject."),  # noqa: B008
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


def stats() -> None:
    """Show injection history and block library statistics."""
    import contextlib
    import json
    import time
    from collections import Counter

    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index

    data_dir = _data_dir()

    # ── Live injection log (written by hook) ─────────────────────────────
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
    priors_week = sum(
        len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago
    )

    block_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for e in entries:
        for slug in e.get("blocks", []):
            block_counts[slug] += 1
        for d in e.get("domains", []):
            domain_counts[d] += 1

    top_blocks = block_counts.most_common(3)
    top_domains = [d for d, _ in domain_counts.most_common(5)]

    # Conservative estimate: 0.5 turns saved per prior (one correction prevented per 2 priors)
    TURNS_PER_PRIOR = 0.5
    TOKENS_PER_TURN = 1500
    est_turns = round(priors_total * TURNS_PER_PRIOR)
    est_tokens = priors_total * TURNS_PER_PRIOR * TOKENS_PER_TURN

    # ── Tool call log ─────────────────────────────────────────────────────
    tool_log_path = data_dir / "tool_call_log.jsonl"
    tool_entries: list[dict[str, Any]] = []
    if tool_log_path.exists():
        for line in tool_log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                tool_entries.append(json.loads(line))

    tool_calls_total = len(tool_entries)
    tool_calls_week = sum(1 for e in tool_entries if e.get("ts", 0) >= week_ago)
    tokens_in_total = sum(e.get("tokens_in", 0) for e in tool_entries)
    tokens_out_total = sum(e.get("tokens_out", 0) for e in tool_entries)
    tokens_week = sum(
        e.get("tokens_in", 0) + e.get("tokens_out", 0)
        for e in tool_entries
        if e.get("ts", 0) >= week_ago
    )
    submit_tokens = sum(
        e.get("tokens_in", 0) + e.get("tokens_out", 0)
        for e in tool_entries
        if e.get("tool") == "submit_candidate"
    )
    by_tool: Counter[str] = Counter(e.get("tool", "unknown") for e in tool_entries)

    # ── Library stats ─────────────────────────────────────────────────────
    try:
        blocks = load_all_blocks(_blocks_dir())
    except FileNotFoundError:
        blocks = {}

    stale = [b for b in blocks.values() if b.is_stale()]
    domains_all = sorted({b.domain for b in blocks.values()})

    # ── Render ────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]📎 TurnZero — Stats[/bold]\n")

    usage = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    usage.add_column("", style="dim", min_width=26)
    usage.add_column("", justify="right")

    if sessions_total == 0:
        usage.add_row("Sessions with injection", "[dim]none yet[/dim]")
        usage.add_row(
            "", "[dim]Start a new Claude Code session with a specific tech prompt[/dim]"
        )
    else:
        usage.add_row(
            "Sessions with injection",
            f"[bold]{sessions_total}[/bold]  [dim](+{sessions_week} this week)[/dim]",
        )
        usage.add_row(
            "Expert Priors applied",
            f"[bold]{priors_total}[/bold]  [dim](+{priors_week} this week)[/dim]",
        )
        usage.add_row(
            "Est. turns saved",
            f"[bold green]~{est_turns}[/bold green]  [dim](~{int(est_tokens/1000)}k tokens)[/dim]",
        )
        if top_domains:
            usage.add_row(
                "Top domains", "  ".join(f"[cyan]{d}[/cyan]" for d in top_domains)
            )
        if top_blocks:
            usage.add_row(
                "Top priors",
                "  ".join(f"{slug.split('-')[0]}… ({n}×)" for slug, n in top_blocks),
            )

    console.print(usage)

    if tool_calls_total > 0:
        console.print()
        overhead = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        overhead.add_column("", style="dim", min_width=26)
        overhead.add_column("", justify="right")
        overhead.add_row(
            "MCP tool calls",
            f"[bold]{tool_calls_total}[/bold]  [dim](+{tool_calls_week} this week)[/dim]",
        )
        overhead.add_row(
            "MCP token cost (est.)",
            f"[bold]{(tokens_in_total + tokens_out_total) // 1000}k[/bold]"
            f"  [dim]in {tokens_in_total // 1000}k · out {tokens_out_total // 1000}k · "
            f"+{tokens_week // 1000}k this week[/dim]",
        )
        if submit_tokens:
            overhead.add_row(
                "  of which: new priors",
                f"[dim]{submit_tokens // 1000}k tokens[/dim]",
            )
        if by_tool:
            breakdown = "  ".join(f"{t}({n})" for t, n in by_tool.most_common())
            overhead.add_row("  by tool", f"[dim]{breakdown}[/dim]")
        net_tokens = int(est_tokens) - (tokens_in_total + tokens_out_total)
        net_label = (
            f"[bold green]+{net_tokens // 1000}k net saved[/bold green]"
            if net_tokens > 0
            else f"[yellow]{net_tokens // 1000}k net[/yellow]"
        )
        overhead.add_row("Net token benefit", net_label)
        console.print(overhead)

    console.print()
    lib = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    lib.add_column("", style="dim", min_width=26)
    lib.add_column("", justify="right")
    lib.add_row("Block library", f"{len(blocks)} blocks · {len(domains_all)} domains")
    lib.add_row(
        "Stale blocks (>90d)",
        f"[red]{len(stale)}[/red]" if stale else "[green]0[/green]",
    )
    try:
        index = load_index(_index_path())
        lib.add_row("Index entries", str(len(index)))
    except FileNotFoundError:
        lib.add_row("Index", "[yellow]not built — run: turnzero index build[/yellow]")

    lib.add_row("Data dir", str(data_dir))
    console.print(lib)
    console.print()
