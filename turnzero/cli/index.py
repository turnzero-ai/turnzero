"""Index management and validation commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.table import Table

from turnzero.cli.base import (
    THRESHOLD_TEST_GOOD_RECALL,
    THRESHOLD_TEST_WARN_RECALL,
    console,
    err_console,
    get_blocks_dir,
    get_data_dir,
    get_index_path,
)
from turnzero.services import retrieval_svc

index_app = typer.Typer(help="Manage the embedding index.", no_args_is_help=True)


@index_app.command("build")
def index_build() -> None:
    """Embed all blocks and write the similarity index."""
    from turnzero.index import build as _build

    console.print(f"Building index from [bold]{get_blocks_dir()}[/bold] ...")
    try:
        count = _build(get_blocks_dir(), get_index_path(), data_dir=get_data_dir())
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Indexed {count} block(s) → {get_index_path()}")


@index_app.command("verify")
def index_verify(
    max_age_days: int = typer.Option(90, "--days", help="Staleness threshold in days."),
) -> None:
    """Flag blocks not verified within the staleness window."""
    from turnzero.index import verify as _verify

    try:
        stale = _verify(get_blocks_dir(), max_age_days)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not stale:
        console.print(
            f"[green]✓[/green] All blocks verified within {max_age_days} days."
        )
    else:
        console.print(f"[yellow]{len(stale)} stale block(s):[/yellow]")
        for block_id in stale:
            console.print(f"  • {block_id}")


def validate(
    validation_file: Path = typer.Option(
        Path("tests/validation_set.json"),
        "--file",
        "-f",
        help="Path to validation set JSON file.",
    ),
    top_k: int = typer.Option(3, "--top-k", "-k", help="K for Hit Rate@K."),
    threshold: float = typer.Option(
        0.70, "--threshold", "-t", help="Minimum cosine similarity."
    ),
    context_weight: int = typer.Option(
        4000, "--weight", help="Weight budget for query."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-query results."
    ),
) -> None:
    """Run Hit Rate@K evaluation against the validation set.

    Reads tests/validation_set.json, runs each prompt through the retrieval
    pipeline, and computes Hit Rate@K.
    Exits with code 1 if Hit Rate@K is below 0.70.
    """
    import json

    from turnzero.retrieval import query as _query

    if not validation_file.exists():
        err_console.print(f"[red]Validation file not found: {validation_file}[/red]")
        raise typer.Exit(1)

    try:
        with validation_file.open(encoding="utf-8") as f:
            validation_set = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        err_console.print(f"[red]Failed to load validation file: {e}[/red]")
        raise typer.Exit(1)

    try:
        blocks = retrieval_svc.get_all_blocks(get_blocks_dir())
        index = retrieval_svc.load_index_entries(get_index_path())
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    hits: list[bool] = []

    table = Table(title=f"Hit Rate@{top_k} Validation", box=box.SIMPLE)
    table.add_column("Prompt", max_width=45)
    table.add_column("Expected", style="dim")
    table.add_column("Got #1")
    table.add_column("Hit", justify="right")

    for entry in validation_set:
        prompt = entry["prompt"]
        relevant = set(entry["relevant_block_ids"])

        results = _query(
            prompt,
            index,
            blocks,
            top_k=top_k,
            threshold=threshold,
            context_weight=context_weight,
        )
        retrieved_ids = [block.id for block, _ in results]

        hit = any(rid in relevant for rid in retrieved_ids)
        hits.append(hit)

        got_top = retrieved_ids[0] if retrieved_ids else "[none]"
        expected_top = next(iter(entry.get("relevant_block_ids", [])), "[none]")
        hit_str = "[green]✓[/green]" if hit else "[red]✗[/red]"

        table.add_row(prompt[:45], expected_top[:30], got_top[:30], hit_str)

        if verbose:
            console.print(f"\n[bold]{prompt[:60]}[/bold]")
            console.print(f"  Expected: {', '.join(sorted(relevant))}")
            console.print(f"  Got:      {', '.join(retrieved_ids) or '[none]'}")
            console.print(f"  Hit: {'yes' if hit else 'no'}")

    console.print(table)

    if not hits:
        console.print("[yellow]No validation entries found.[/yellow]")
        raise typer.Exit(1)

    hit_rate = sum(hits) / len(hits)
    target = 0.70
    color = "green" if hit_rate >= target else "red"

    console.print(
        f"\n[bold]Hit Rate@{top_k}:[/bold] [{color}]{hit_rate:.3f}[/{color}]  "
        f"(target ≥ {target:.2f}, {len(hits)} queries)"
    )

    if hit_rate < target:
        console.print(f"[red]✗ Below target {target:.2f}[/red]")
        raise typer.Exit(1)
    else:
        console.print(f"[green]✓ Meets target {target:.2f}[/green]")


def _is_blocked(
    prompt: str,
    min_words: int,
    require_impl: bool,
    is_implementation_prompt: Callable[..., bool],
) -> bool:
    if min_words > 0 and len(prompt.split()) < min_words:
        return True
    return bool(require_impl and not is_implementation_prompt(prompt))


def _run_verbose_dump(
    val_set: list[dict[str, Any]],
    negatives: list[str],
    blocks: Mapping[str, Any],
    index: Sequence[Any],
    min_words: int,
    require_impl: bool,
    strict_intent: bool,
    is_implementation_prompt: Callable[..., bool],
    _query: Callable[..., Any],
) -> None:
    console.print("\n[bold]Per-prompt top scores[/bold] (all prompts, no threshold filter)\n")
    all_prompts: list[tuple[str, bool]] = (
        [(str(e["prompt"]), True) for e in val_set] + [(p, False) for p in negatives]
    )
    score_table = Table(box=box.SIMPLE)
    score_table.add_column("Type", width=4)
    score_table.add_column("Prompt", max_width=55)
    score_table.add_column("Top block", max_width=35)
    score_table.add_column("Score", justify="right")
    score_table.add_column("Intent hit")

    for prompt_text, is_positive in all_prompts:
        word_blocked = min_words > 0 and len(prompt_text.split()) < min_words
        impl_blocked = require_impl and not is_implementation_prompt(prompt_text)
        raw = _query(prompt_text, index, blocks, top_k=1, threshold=0.0, context_weight=99999, strict_intent=False)
        type_str = "[green]+[/green]" if is_positive else "[red]-[/red]"
        if raw:
            top_block, top_score = raw[0]
            strict_raw = _query(prompt_text, index, blocks, top_k=1, threshold=0.0, context_weight=99999, strict_intent=strict_intent)
            intent_ok = "[green]✓[/green]" if strict_raw else "[yellow]no[/yellow]"
            if word_blocked:
                label = "[dim]word-blocked[/dim]"
            elif impl_blocked:
                label = "[dim]impl-blocked[/dim]"
            else:
                label = intent_ok
            score_table.add_row(type_str, prompt_text[:55], top_block.slug[:35], f"{top_score:.3f}", label)
        else:
            score_table.add_row(type_str, prompt_text[:55], "[none]", "0.000", "—")

    console.print(score_table)
    console.print("[dim]+ = should fire  - = should NOT fire  Intent hit = passes strict_intent filter[/dim]\n")


def _compute_recall(
    val_set: list[dict[str, Any]],
    t: float,
    blocks: Mapping[str, Any],
    index: Sequence[Any],
    top_k: int,
    min_words: int,
    require_impl: bool,
    strict_intent: bool,
    is_implementation_prompt: Callable[..., bool],
    _query: Callable[..., Any],
) -> tuple[int, int]:
    """Return (tp_hits, eligible_count) for the given threshold."""
    hits = 0
    eligible = 0
    for entry in val_set:
        prompt = str(entry["prompt"])
        if _is_blocked(prompt, min_words, require_impl, is_implementation_prompt):
            continue
        eligible += 1
        relevant: set[str] = set(entry["relevant_block_ids"])
        results = _query(prompt, index, blocks, top_k=top_k, threshold=t, context_weight=4000, strict_intent=strict_intent)
        if any(b.id in relevant for b, _ in results):
            hits += 1
    return hits, eligible


def _render_threshold_table(
    t_values: list[float],
    val_set: list[dict[str, Any]],
    negatives: list[str],
    blocks: Mapping[str, Any],
    index: Sequence[Any],
    top_k: int,
    min_words: int,
    require_impl: bool,
    strict_intent: bool,
    is_implementation_prompt: Callable[..., bool],
    _query: Callable[..., Any],
) -> None:
    sweep_table = Table(title="Threshold Sweep", box=box.SIMPLE)
    sweep_table.add_column("Threshold", justify="right")
    sweep_table.add_column("TP rate (recall)", justify="right")
    sweep_table.add_column("FP rate", justify="right")
    sweep_table.add_column("Fires on", max_width=50)

    for t in t_values:
        tp_hits, eligible_count = _compute_recall(
            val_set, t, blocks, index, top_k, min_words, require_impl, strict_intent,
            is_implementation_prompt, _query,
        )
        recall = tp_hits / eligible_count if eligible_count else 0.0

        fp_hits = 0
        eligible_neg = [n for n in negatives if not _is_blocked(n, min_words, require_impl, is_implementation_prompt)]
        for neg in eligible_neg:
            results = _query(neg, index, blocks, top_k=top_k, threshold=t, context_weight=4000, strict_intent=strict_intent)
            if results:
                fp_hits += 1
        fp_rate_str = f"{fp_hits}/{len(eligible_neg)}" if negatives else "n/a"

        fires_on = []
        for entry in val_set:
            results = _query(str(entry["prompt"]), index, blocks, top_k=1, threshold=t, context_weight=4000, strict_intent=strict_intent)
            if results:
                fires_on.append(results[0][0].slug)

        recall_color = (
            "green" if recall >= THRESHOLD_TEST_GOOD_RECALL
            else ("yellow" if recall >= THRESHOLD_TEST_WARN_RECALL else "red")
        )
        sweep_table.add_row(
            f"{t:.2f}",
            f"[{recall_color}]{recall:.0%} ({tp_hits}/{len(val_set)})[/{recall_color}]",
            fp_rate_str,
            ", ".join(dict.fromkeys(fires_on))[:48] or "[dim]nothing[/dim]",
        )

    console.print(sweep_table)
    if negatives:
        console.print("[dim]FP rate = negative prompts that triggered an injection[/dim]")
    else:
        console.print(
            "[dim]No negatives file provided — FP rate unavailable. "
            "Use --negatives to pass a JSON list of prompts that should NOT trigger.[/dim]"
        )
    console.print(
        "\n[dim]Tip: run with --verbose to see the raw similarity score for every prompt, "
        "which helps identify where the natural gap is between signal and noise.[/dim]"
    )


def threshold_test(
    thresholds: str = typer.Option(
        "0.50,0.55,0.60,0.65,0.70,0.75",
        "--thresholds",
        "-t",
        help="Comma-separated thresholds to sweep.",
    ),
    validation_file: Path = typer.Option(
        Path("tests/validation_set.json"),
        "--file",
        "-f",
        help="Validation set for true positives.",
    ),
    negative_file: Path = typer.Option(
        None,
        "--negatives",
        "-n",
        help="Optional JSON file with prompts that should NOT trigger (list of strings).",
    ),
    top_k: int = typer.Option(3, "--top-k", "-k"),
    strict_intent: bool = typer.Option(True, "--strict/--no-strict"),
    min_words: int = typer.Option(
        0,
        "--min-words",
        "-w",
        help="Skip prompts shorter than N words (mirrors hook MIN_PROMPT_WORDS). 0 = disabled.",
    ),
    require_impl: bool = typer.Option(
        False,
        "--require-impl/--no-require-impl",
        help="Apply is_implementation_prompt() gate before similarity check (mirrors hook).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-prompt scores."
    ),
) -> None:
    """Sweep thresholds and show precision/recall trade-off.

    For each threshold prints: true positive rate (Hit Rate@K on validation set),
    false positive rate (if --negatives provided), and a sample of what fires.
    Use this to find the sweet spot before changing the hook threshold.
    """
    import json

    from turnzero.retrieval import is_implementation_prompt
    from turnzero.retrieval import query as _query

    try:
        blocks = retrieval_svc.get_all_blocks(get_blocks_dir())
        index = retrieval_svc.load_index_entries(get_index_path())
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not validation_file.exists():
        err_console.print(f"[red]Validation file not found: {validation_file}[/red]")
        raise typer.Exit(1)

    with validation_file.open(encoding="utf-8") as f:
        val_set = json.load(f)

    negatives: list[str] = []
    if negative_file and negative_file.exists():
        with negative_file.open(encoding="utf-8") as f:
            negatives = json.load(f)

    try:
        t_values = [float(x.strip()) for x in thresholds.split(",")]
    except ValueError:
        err_console.print(
            "[red]--thresholds must be comma-separated floats, e.g. 0.55,0.60,0.65[/red]"
        )
        raise typer.Exit(1)

    if verbose:
        _run_verbose_dump(val_set, negatives, blocks, index, min_words, require_impl,
                          strict_intent, is_implementation_prompt, _query)

    _render_threshold_table(t_values, val_set, negatives, blocks, index, top_k,
                            min_words, require_impl, strict_intent,
                            is_implementation_prompt, _query)
