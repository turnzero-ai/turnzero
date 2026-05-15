"""Discovery and preview CLI commands."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import typer
import yaml
from rich import box
from rich.table import Table

from turnzero.analytics import SessionAnalytics
from turnzero.blocks import Block
from turnzero.cli.base import (
    DEFAULT_THRESHOLD,
    MAX_PREVIEW_ANTI_PATTERNS,
    MAX_PREVIEW_CONSTRAINTS,
    PREVIEW_TEXT_LIMIT,
    console,
    err_console,
)
from turnzero.config import (
    get_active_domains,
    get_blocks_dir,
    get_bundled_blocks_dir,
    get_bundled_index_path,
    get_data_dir,
    get_index_path,
    load_telemetry_config,
)
from turnzero.formatters import block_fmt
from turnzero.retrieval import (
    IDENTITY_SCORE_THRESHOLD,
    classify_intent,
    detect_domain,
    get_identity_context,
    is_implementation_prompt,
)
from turnzero.retrieval import (
    query as _query,
)
from turnzero.services import retrieval_svc, stats_svc
from turnzero.telemetry import track_list_viewed, track_stats_viewed
from turnzero.types import Tier
from turnzero.upgrade import check_for_upgrade

discovery_app = typer.Typer(no_args_is_help=True)


def _load_blocks_and_index() -> tuple[dict[str, Block], list[Any]]:
    """Load blocks and index via service layer with bundled fallback."""
    try:
        index_path = get_index_path()
        if not index_path.exists():
            index_path = get_bundled_index_path()
        if not index_path.exists():
            raise FileNotFoundError("No index found. Run: turnzero setup")
        blocks_dir = get_blocks_dir() if get_index_path().exists() else get_bundled_blocks_dir()
        return retrieval_svc.get_all_blocks(blocks_dir), retrieval_svc.load_index_entries(index_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _load_stats_data(data_dir: Path) -> dict[str, Any]:
    """Delegate to stats_svc for stats aggregation."""
    return stats_svc.compute_display_data(data_dir)


def _render_stats(data: dict[str, Any]) -> None:
    """Render stats tables and nudges to the console."""

    sessions_total = data["sessions_total"]

    console.print()
    console.print("[bold]📎 TurnZero — Stats[/bold]\n")

    if sessions_total > 0:
        parts = [
            f"[bold]{data['sessions_week']}[/bold] sessions",
            f"[bold]{data['priors_week']}[/bold] injections",
            f"[bold]{data['corrections_week']}[/bold] corrections",
        ]
        console.print(f"  Last 7 days  [dim]{'  ·  '.join(parts)}[/dim]\n")

    usage = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    usage.add_column("", style="dim", min_width=26)
    usage.add_column("", justify="right")

    if sessions_total == 0:
        usage.add_row("Sessions with injection", "[dim]none yet[/dim]")
        if data["corrections_total"] == 0:
            usage.add_row(
                "Corrections captured",
                "[dim]none yet — AI will learn from your corrections[/dim]",
            )
    else:
        usage.add_row(
            "Sessions with injection",
            f"[bold]{sessions_total}[/bold]  [dim](+{data['sessions_week']} this week)[/dim]",
        )
        usage.add_row(
            "Priors applied",
            f"[bold]{data['priors_total']}[/bold]  [dim](+{data['priors_week']} this week)[/dim]",
        )
        usage.add_row(
            "Corrections captured",
            f"[bold]{data['corrections_total']}[/bold]  "
            f"[dim](+{data['corrections_week']} this week)[/dim]",
        )
        if data["tokens_injected_total"] > 0:
            usage.add_row(
                "Prior content added (~est)",
                f"[bold]{data['tokens_injected_total']:,}[/bold] tokens"
                f"  [dim](+{data['tokens_injected_week']:,} this week)[/dim]",
            )
        if data["overhead_total"] > 0:
            usage.add_row(
                "MCP call overhead (~est)",
                f"[bold]{data['overhead_total']:,}[/bold] tokens"
                f"  [dim](+{data['overhead_week']:,} this week)[/dim]",
            )
        usage.add_row(
            "Est. turns saved",
            f"[bold green]~{data['est_turns']}[/bold green]"
            f"  [dim](~{int(data['est_tokens'] / 1000)}k tokens est. saved)[/dim]",
        )
        if data["top_domains"]:
            usage.add_row(
                "Top domains",
                "  ".join(f"[cyan]{d}[/cyan]" for d in data["top_domains"]),
            )

    console.print(usage)

    console.print()
    lib = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    lib.add_column("", style="dim", min_width=26)
    lib.add_column("", justify="right")
    blocks_total = data["blocks_total"]
    personal_count = data["personal_count"]
    lib.add_row("Block library", f"{blocks_total} blocks total")
    lib.add_row("  - Expert Priors", str(blocks_total - personal_count))
    if personal_count > 0 and data["personal_weeks"] is not None:
        lib.add_row(
            "  - Personal Priors",
            f"[magenta]{personal_count}[/magenta]"
            f"  [dim](0 → {personal_count} in {data['personal_weeks']}w)[/dim]",
        )
    else:
        lib.add_row("  - Personal Priors", f"[magenta]{personal_count}[/magenta]")
    stale_count = data["stale_count"]
    lib.add_row(
        "Stale blocks (>90d)",
        f"[red]{stale_count}[/red]" if stale_count else "[green]0[/green]",
    )
    if data["index_count"] is not None:
        lib.add_row("Index entries", str(data["index_count"]))
    else:
        lib.add_row("Index", "[yellow]not built[/yellow]")

    console.print(lib)

    if sessions_total == 0:
        setup_done = bool(load_telemetry_config(data["data_dir"]).get("anonymous_id"))
        if setup_done:
            console.print(
                "[yellow]No sessions logged yet.[/yellow] "
                "Open your AI client and start with your usual prompt — "
                "priors inject automatically.\n"
                "[dim]Browse your library: [/dim][cyan]turnzero list[/cyan]  "
                "[dim]See what fires: [/dim][cyan]turnzero query \"<your prompt>\"[/cyan]\n"
            )


def _display_preview(results: list[tuple[Block, float]], threshold: float) -> None:
    """Print a visual preview of suggested blocks."""
    total_weight = sum(b.context_weight for b, _ in results)
    console.print(
        f"\n[bold]TurnZero Suggestions[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n"
    )

    for i, (block, score) in enumerate(results, 1):
        stale_tag = "  [red][STALE][/red]" if block.is_stale() else ""
        # High scores (2.0) indicate Identity Priors
        tier_label = (
            "[magenta]Identity[/magenta]"
            if score >= IDENTITY_SCORE_THRESHOLD
            else "[cyan]Expert[/cyan]"
        )

        console.print(
            f"  [bold cyan]{i}.[/bold cyan] [bold]{block.slug}[/bold]{stale_tag}    "
            f"[dim]{tier_label} | score: {score:.2f} | weight: {block.context_weight}[/dim]"
        )
        if block.constraints:
            preview_text = block.constraints[0][:PREVIEW_TEXT_LIMIT]
            console.print(
                f'     [dim]"{preview_text}{"..." if len(block.constraints[0]) > PREVIEW_TEXT_LIMIT else ""}"[/dim]'
            )
        console.print()

    console.print(
        "[dim]This is what TurnZero injects at Turn 0 of your AI session.[/dim]\n"
        "[dim]To manage: [/dim][cyan]turnzero review[/cyan]\n"
    )


def _print_explain(
    prompt: str,
    index: list[Any],
    blocks: dict[str, Any],
    identity_blocks: list[tuple[Any, float]],
    identity_weight: int,
    threshold: float,
    top_k: int,
    context_weight: int,
    strict_intent: bool,
) -> None:
    intent = classify_intent(prompt)
    domain = detect_domain(prompt, project_root=Path.cwd())
    is_impl = is_implementation_prompt(prompt, project_root=Path.cwd())

    console.print("\n[bold]TurnZero — Explain[/bold]\n")

    if not is_impl:
        console.print(
            "  Impl gate:        [red]✗ failed[/red] — prompt is chitchat or not substantive"
        )
        console.print(
            "\n  [dim]No blocks inject for this prompt. This is expected.[/dim]\n"
        )
        return

    console.print(f"  Intent detected:  [cyan]{intent}[/cyan]")
    domain_label = f"[cyan]{domain}[/cyan]" if domain else "[dim]none detected[/dim]"
    console.print(f"  Domain detected:  {domain_label}")
    console.print("  Impl gate:        [green]✓ passed[/green]")
    console.print(f"  Threshold:        {threshold}")

    if identity_blocks:
        console.print(
            f"\n  [magenta]Personal Priors[/magenta] ({len(identity_blocks)} matched):"
        )
        for block, _ in identity_blocks:
            console.print(
                f"    • {block.slug}  [dim]{block.context_weight} tokens[/dim]"
            )
    else:
        console.print("\n  [dim]Personal Priors: none configured[/dim]")

    # Run with no threshold + no intent filter to surface all candidates including near-misses
    all_candidates = _query(
        prompt,
        index,
        blocks,
        top_k=max(top_k, 15),
        threshold=0.0,
        context_weight=999_999,
        strict_intent=False,
        project_root=Path.cwd(),
        exclude_block_ids={b.slug for b, _ in identity_blocks},
    )

    above = [(b, s) for b, s in all_candidates if s >= threshold]
    near_misses = [
        (b, s) for b, s in all_candidates if s < threshold and s >= threshold * 0.70
    ][:5]

    if above:
        console.print(f"\n  [green]Matched (score ≥ {threshold}):[/green]")
        for block, score in above:
            intent_tag = (
                f"  [dim]intent: {block.intent}[/dim]" if block.intent != intent else ""
            )
            console.print(
                f"    [green]✓[/green] {block.slug:<42} score: {score:.3f}  weight: {block.context_weight}{intent_tag}"
            )
    else:
        console.print(
            f"\n  [yellow]No Expert Priors above threshold ({threshold}).[/yellow]"
        )

    if near_misses:
        console.print(
            f"\n  [dim]Near misses (score < {threshold}, top {len(near_misses)}):[/dim]"
        )
        for block, score in near_misses:
            gap = threshold - score
            console.print(
                f"    [dim]✗ {block.slug:<42} score: {score:.3f}  (gap: -{gap:.3f})[/dim]"
            )

    console.print()


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
        True,
        "--strict/--no-strict",
        help="Only return blocks matching detected intent.",
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
    explain: bool = typer.Option(
        False, "--explain", "-e", help="Show why blocks did or did not inject."
    ),
) -> None:
    """Suggest Expert Priors for an opening prompt."""

    blocks, index = _load_blocks_and_index()

    # 1. Personal Identity context (unconditional)
    identity_blocks, limit_exceeded = get_identity_context(
        blocks, project_root=Path.cwd()
    )
    identity_weight = sum(b.context_weight for b, _ in identity_blocks)

    if explain:
        _print_explain(
            prompt=prompt,
            index=index,
            blocks=blocks,
            identity_blocks=identity_blocks,
            identity_weight=identity_weight,
            threshold=threshold,
            top_k=top_k,
            context_weight=context_weight,
            strict_intent=strict_intent,
        )
        return

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
        console.print("\n[dim]No blocks found for this prompt.[/dim]\n")
        console.print("[dim]Run with --explain to diagnose why.[/dim]\n")
        return

    # Load session analytics
    analytics = SessionAnalytics.load(session, get_data_dir())

    # Update session ROI
    analytics.log_injection([b.slug for b, _ in results])
    analytics.save(get_data_dir())

    _display_preview(results, threshold)


@discovery_app.command()
def preview(
    prompt: str = typer.Argument(..., help="Opening prompt to preview."),
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum cosine similarity."
    ),
) -> None:
    """Full-content preview of what would be injected for a prompt."""

    blocks, index = _load_blocks_and_index()

    # Use the same dual-stream logic as query()
    identity_blocks, _ = get_identity_context(blocks, project_root=Path.cwd())
    identity_weight = sum(b.context_weight for b, _ in identity_blocks)

    expert_results = _query(
        prompt,
        index,
        blocks,
        threshold=threshold,
        context_weight=4000 - identity_weight,
        project_root=Path.cwd(),
        exclude_block_ids={b.slug for b, _ in identity_blocks},
    )

    results = identity_blocks + expert_results

    if not results:
        console.print("\n[dim]No blocks found for this prompt.[/dim]\n")
        return

    total_weight = sum(b.context_weight for b, _ in results)
    console.print(
        f"\n[bold]TurnZero Preview[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n"
    )

    for block, score in results:
        # Identity priors get magenta color, Experts get cyan
        color = "magenta" if score >= IDENTITY_SCORE_THRESHOLD else "cyan"
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


@discovery_app.command()
def show(
    slug: str = typer.Argument(..., help="Block slug to display."),
) -> None:
    """Display full content of a block."""

    try:
        blocks = retrieval_svc.get_all_blocks(get_blocks_dir())
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
    console.print(
        f"[dim]verified: {block.last_verified}  confidence: {block.confidence:.2f}[/dim]\n"
    )

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
    inputs: list[str] = typer.Argument(
        ..., help="One or more block slugs OR natural language queries to inject."
    ),
) -> None:
    """Print formatted Expert Priors ready for injection into an AI session.

    If an input matches an exact block slug, it is injected directly.
    Otherwise, the input is treated as a query to find the best matching block.
    """

    try:
        blocks = retrieval_svc.get_all_blocks(get_blocks_dir())
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    parts: list[str] = []
    for val in inputs:
        # 1. Direct slug match
        if val in blocks:
            parts.append(block_fmt.to_injection_text(blocks[val]))
            continue

        # 2. Query retrieval fallback
        try:
            index = retrieval_svc.load_index_entries(get_index_path())
            results = _query(
                val,
                index,
                blocks,
                top_k=1,
                threshold=DEFAULT_THRESHOLD,
                strict_intent=False,
            )
            if results:
                block, _score = results[0]
                err_console.print(
                    f"[dim]✓ No slug match for '{val}' — retrieving best match: [bold]{block.slug}[/bold][/dim]"
                )
                parts.append(block_fmt.to_injection_text(block))
            else:
                err_console.print(
                    f"[red]Error: '{val}' is not a slug and no relevant blocks were found.[/red]"
                )
        except Exception as e:
            err_console.print(f"[red]Retrieval error for '{val}': {e}[/red]")

    if parts:
        print("\n\n---\n\n".join(parts))


@discovery_app.command(name="list")
def list_blocks(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Show blocks in a specific domain."
    ),
    candidates: bool = typer.Option(
        False, "--candidates", "-c", help="Show pending candidates awaiting review."
    ),
    stale: bool = typer.Option(
        False, "--stale", help="Show only stale blocks (>90d unverified)."
    ),
) -> None:
    """Browse the Expert Prior library."""


    if candidates:
        cand_dir = get_data_dir() / "candidates"
        if not cand_dir.exists() or not list(cand_dir.glob("*.yaml")):
            console.print("\n[dim]No candidates pending review.[/dim]\n")
            console.print(
                "[dim]Candidates are created when the AI is corrected mid-session. "
                "Run `turnzero review` to manage them.[/dim]\n"
            )
            return

        console.print("\n[bold]Candidates pending review[/bold]\n")
        tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        tbl.add_column("slug", style="cyan", min_width=30)
        tbl.add_column("domain", min_width=12)
        tbl.add_column("confidence", justify="right")
        tbl.add_column("submitted", min_width=10)

        for path in sorted(cand_dir.glob("*.yaml")):
            with contextlib.suppress(Exception):
                raw = yaml.safe_load(path.read_text())
                conf = f"{float(raw.get('confidence', 0.0)):.2f}"
                tbl.add_row(
                    str(raw.get("slug", path.stem)),
                    str(raw.get("domain", "—")),
                    conf,
                    str(raw.get("last_verified", "—")),
                )
        console.print(tbl)
        console.print("[dim]Run `turnzero review` to approve or reject.[/dim]\n")
        cand_count = sum(1 for _ in cand_dir.glob("*.yaml"))
        track_list_viewed(mode="candidates", blocks_shown=cand_count)
        return

    try:
        blocks = retrieval_svc.get_all_blocks(get_blocks_dir())
    except FileNotFoundError:
        # Fall back to bundled index
        try:
            blocks = retrieval_svc.get_all_blocks(get_bundled_blocks_dir())
        except FileNotFoundError:
            console.print("[red]No block library found. Run: turnzero setup[/red]")
            raise typer.Exit(1)

    if stale:
        stale_blocks = {k: v for k, v in blocks.items() if v.is_stale()}
        if not stale_blocks:
            console.print("\n[green]No stale blocks.[/green]\n")
            return
        console.print("\n[bold]Stale blocks[/bold] [dim](>90d unverified)[/dim]\n")
        tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        tbl.add_column("slug", style="cyan", min_width=36)
        tbl.add_column("domain", min_width=12)
        tbl.add_column("last verified", min_width=12)
        tbl.add_column("confidence", justify="right")
        for b in sorted(stale_blocks.values(), key=lambda b: b.last_verified):
            tbl.add_row(b.slug, b.domain, b.last_verified, f"{b.confidence:.2f}")
        console.print(tbl)
        track_list_viewed(mode="stale", blocks_shown=len(stale_blocks))
        return

    if domain:
        domain_blocks = [b for b in blocks.values() if b.domain == domain]
        if not domain_blocks:
            console.print(f"\n[yellow]No blocks found for domain: {domain}[/yellow]\n")
            domains_present = sorted({b.domain for b in blocks.values()})
            console.print(
                f"[dim]Available domains: {', '.join(domains_present)}[/dim]\n"
            )
            raise typer.Exit(1)

        console.print(
            f"\n[bold]Domain: {domain}[/bold] [dim]({len(domain_blocks)} block(s))[/dim]\n"
        )
        tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        tbl.add_column("slug", style="cyan", min_width=36)
        tbl.add_column("tier", min_width=10)
        tbl.add_column("confidence", justify="right")
        tbl.add_column("last verified", min_width=12)
        tbl.add_column("", min_width=6)

        for b in sorted(domain_blocks, key=lambda b: b.slug):
            stale_tag = "[red]STALE[/red]" if b.is_stale() else "[green]ok[/green]"
            tbl.add_row(b.slug, b.tier, f"{b.confidence:.2f}", b.last_verified, stale_tag)
        console.print(tbl)
        track_list_viewed(mode="domain", blocks_shown=len(domain_blocks), domain=domain)
        return

    # Default: domain summary
    from collections import Counter

    # Exclude personal-tier blocks from domain table — they inject unconditionally
    # and are not subject to active_domains filtering. Show them as a separate row.
    personal_blocks_list = [b for b in blocks.values() if b.tier == Tier.PERSONAL]
    expert_blocks = {k: v for k, v in blocks.items() if v.tier != Tier.PERSONAL}

    domain_counts: Counter[str] = Counter(b.domain for b in expert_blocks.values())
    stale_by_domain: Counter[str] = Counter(
        b.domain for b in expert_blocks.values() if b.is_stale()
    )

    active_domains = get_active_domains(get_data_dir())

    console.print(
        f"\n[bold]Expert Prior Library[/bold] [dim]({len(blocks)} blocks across {len(domain_counts)} domains)[/dim]\n"
    )
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("domain", style="cyan", min_width=20)
    tbl.add_column("blocks", justify="right", min_width=6)
    tbl.add_column("stale", justify="right", min_width=5)
    tbl.add_column("status", min_width=10)

    # Personal-tier row always first, always-on regardless of active_domains
    if personal_blocks_list:
        personal_stale = sum(1 for b in personal_blocks_list if b.is_stale())
        stale_cell = f"[red]{personal_stale}[/red]" if personal_stale else "[dim]0[/dim]"
        tbl.add_row(
            "[magenta]personal[/magenta]",
            str(len(personal_blocks_list)),
            stale_cell,
            "[magenta]always-on[/magenta]",
        )

    for d, count in sorted(domain_counts.items()):
        stale_n = stale_by_domain.get(d, 0)
        stale_cell = f"[red]{stale_n}[/red]" if stale_n else "[dim]0[/dim]"
        if active_domains is None or d in active_domains:
            status = "[green]active[/green]"
        else:
            status = "[dim]inactive[/dim]"
        tbl.add_row(d, str(count), stale_cell, status)

    console.print(tbl)

    # Pending candidates
    cand_dir = get_data_dir() / "candidates"
    cand_count = len(list(cand_dir.glob("*.yaml"))) if cand_dir.exists() else 0
    if cand_count:
        console.print(
            f"[yellow]{cand_count} candidate(s) pending review.[/yellow] "
            f"Run [cyan]turnzero list --candidates[/cyan] or "
            f"[cyan]turnzero review[/cyan].\n"
        )
    else:
        console.print(
            "[dim]Use [/dim][cyan]turnzero list --domain <name>[/cyan]"
            "[dim] to see blocks in a specific domain.[/dim]\n"
        )
    track_list_viewed(mode="summary", blocks_shown=len(blocks))


@discovery_app.command()
def stats() -> None:
    """Show injection history and block library statistics."""

    data_dir = get_data_dir()
    data = _load_stats_data(data_dir)

    track_stats_viewed(sessions_total=data["sessions_total"], blocks_total=data["blocks_total"])
    _render_stats(data)

    latest, is_newer = check_for_upgrade(data_dir)
    if is_newer:
        console.print(f"[dim]TurnZero {latest} available — pipx upgrade turnzero[/dim]\n")
    else:
        console.print()
