"""Transcript harvesting and manual candidate review."""

from __future__ import annotations

from pathlib import Path

import typer

from turnzero.cli.base import (
    LOW_CONFIDENCE_THRESHOLD,
    _blocks_dir,
    _data_dir,
    _index_path,
    console,
    err_console,
)


def harvest(
    conversation: Path = typer.Argument(
        None, help="Conversation file to harvest from (.jsonl, .json, .md, .txt)."
    ),
    model: str = typer.Option("llama3.2", "--model", help="LLM to use for extraction."),
    backend: str = typer.Option(
        "auto", "--backend", help="LLM backend (ollama|openai|anthropic|auto)."
    ),
    all_new: bool = typer.Option(
        False, "--all", "-a", help="Scan all new sessions from known AI tools."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show detected sessions without extracting."
    ),
) -> None:
    """Harvest Expert Prior candidates from AI conversation logs.

    Extracts rules and anti-patterns that prevented or would have prevented
    mid-session corrections. Uses a local or cloud LLM for extraction.

    Candidates are written to ~/.turnzero/candidates/ for later review.
    """
    from turnzero.harvest import (
        extract_with_llm,
        harvest,
        parse_candidates,
        scan_new_sessions,
        write_candidate,
    )

    data_dir = _data_dir()
    candidates_dir = data_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    if all_new:
        processed_file = data_dir / "processed_sessions.txt"
        to_scan = scan_new_sessions(processed_file)
        if not to_scan:
            console.print("[dim]No new sessions found since last harvest.[/dim]")
            return

        console.print(f"\n[bold]Harvesting from {len(to_scan)} session(s)...[/bold]\n")
        if dry_run:
            for f in to_scan:
                console.print(f"  • {f}")
            return

        total_extracted = 0
        for f in to_scan:
            console.print(f"  Scanning [cyan]{f.name}[/cyan] ...", end="\r")
            try:
                candidates = harvest(f, candidates_dir, model=model)
                for c in candidates:
                    write_candidate(c, candidates_dir)
                total_extracted += len(candidates)
                # Mark as processed
                with processed_file.open("a", encoding="utf-8") as pf:
                    pf.write(f"{f}\n")
            except Exception as e:
                console.print(f"[red]✗ Failed {f.name}: {e}[/red]")

        console.print(
            f"\n[green]✓ Done. Extracted {total_extracted} candidates.[/green]"
        )
        console.print("[dim]Run [bold]turnzero review[/bold] to approve them.[/dim]\n")
        return

    if not conversation:
        err_console.print("[red]Error: Provide a conversation file or use --all.[/red]")
        raise typer.Exit(1)

    if not conversation.exists():
        err_console.print(f"[red]File not found: {conversation}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Harvesting from {conversation.name}...[/bold]\n")

    try:
        from turnzero.harvest import load_conversation

        text = load_conversation(conversation)
        raw_yaml = extract_with_llm(text, model=model, backend=backend)
        candidates = parse_candidates(raw_yaml)

        if not candidates:
            console.print("[yellow]No Expert Prior candidates identified.[/yellow]")
            return

        for c in candidates:
            path = write_candidate(c, candidates_dir)
            console.print(f"[green]✓ Candidate written:[/green] {path.name}")

        console.print(
            "\n[dim]Run [bold]turnzero review[/bold] to approve them.[/dim]\n"
        )

    except Exception as e:
        err_console.print(f"[red]Extraction failed: {e}[/red]")
        raise typer.Exit(1)


def review() -> None:
    """Review Expert Prior candidates and low-confidence library blocks.

    1. Surfaces low-confidence blocks (confidence < 0.7) already in the library.
    2. Shows harvested candidates from data/candidates/ for approval.
    """
    from turnzero.blocks import load_all_blocks
    from turnzero.index import build as _build

    data_dir = _data_dir()
    candidates_dir = data_dir / "candidates"
    blocks_dir = _blocks_dir()

    # ── 1. Low-confidence library blocks ────────────────────────────────────────
    try:
        all_blocks = load_all_blocks(blocks_dir)
        low_conf = [
            b
            for b in all_blocks.values()
            if b.confidence < LOW_CONFIDENCE_THRESHOLD and not b.archived
        ]
        if low_conf:
            console.print(
                f"\n[yellow]⚠  Found {len(low_conf)} low-confidence block(s) in your library.[/yellow]"
            )
            console.print(
                "[dim]These were auto-submitted and haven't been verified yet.[/dim]\n"
            )

            for block in sorted(low_conf, key=lambda b: b.confidence):
                console.rule(
                    f"[bold yellow]Review Library Block: {block.slug}[/bold yellow]"
                )
                console.print(
                    f"[dim]Tier: {block.tier} | Confidence: {block.confidence:.2f} | Level: {block.verification_level}[/dim]\n"
                )

                # Show content preview
                if block.constraints:
                    console.print("[bold]Constraints:[/bold]")
                    for c in block.constraints[:3]:
                        console.print(f"  • {c}")

                choice = (
                    typer.prompt(
                        "\n  [v]erify (set confidence 1.0) / [a]rchive / [s]kip / [d]elete",
                        default="s",
                    )
                    .strip()
                    .lower()
                )

                found_path = (
                    blocks_dir / block.tier / block.domain / f"{block.slug}.yaml"
                )
                if not found_path.exists():
                    # Fallback for flat structure or bundled
                    found_path = next(blocks_dir.rglob(f"{block.slug}.yaml"), None)  # type: ignore[assignment]

                if choice in ("v", "verify") and found_path:
                    import yaml as _yaml

                    raw = _yaml.safe_load(found_path.read_text())
                    raw["confidence"] = 1.0
                    raw["verification_level"] = "curated"
                    found_path.write_text(
                        _yaml.dump(raw, sort_keys=False, allow_unicode=True)
                    )
                    console.print(
                        f"  [green]✓ {block.slug} promoted to curated (1.0).[/green]\n"
                    )
                elif choice in ("a", "archive") and found_path:
                    import yaml as _yaml

                    raw = _yaml.safe_load(found_path.read_text())
                    raw["archived"] = True
                    found_path.write_text(
                        _yaml.dump(raw, sort_keys=False, allow_unicode=True)
                    )
                    console.print(
                        f"  [yellow]✓ {block.slug} archived (excluded from retrieval).[/yellow]\n"
                    )
                elif choice in ("d", "delete") and found_path:
                    if typer.confirm(
                        f"  Are you sure you want to PERMANENTLY delete {block.slug}?"
                    ):
                        found_path.unlink()
                        console.print(f"  [red]✗ {block.slug} deleted.[/red]\n")
                else:
                    console.print("  [dim]Skipped.[/dim]\n")

    except FileNotFoundError:
        pass

    # ── 2. Harvested candidates ──────────────────────────────────────────────
    if not candidates_dir.exists() or not list(candidates_dir.glob("*.yaml")):
        console.print("[dim]No new harvested candidates to review.[/dim]")
        # If we made changes to the library, we still need to rebuild
        if any(typer.confirm("Rebuild index now?", default=True) for _ in [1]):
            _build(blocks_dir, _index_path(), data_dir=data_dir)
        return

    pending = sorted(candidates_dir.glob("*.yaml"))
    console.print(f"\n[bold]📋 {len(pending)} new candidate(s) to review[/bold]\n")

    approved = 0
    rejected = 0

    for path in pending:
        import yaml as _yaml

        try:
            candidate = _yaml.safe_load(path.read_text())
        except Exception as e:
            err_console.print(f"[red]Error loading {path.name}: {e}[/red]")
            continue

        console.rule(f"[bold]{candidate.get('id', path.name)}[/bold]")
        console.print(
            f"[dim]domain: {candidate.get('domain')}  intent: {candidate.get('intent')}[/dim]\n"
        )

        if candidate.get("constraints"):
            console.print("[bold]Constraints:[/bold]")
            for c in candidate["constraints"]:
                console.print(f"  • {c}")

        if candidate.get("anti_patterns"):
            console.print("\n[bold]Anti-patterns:[/bold]")
            for a in candidate["anti_patterns"]:
                console.print(f"  • {a}")

        console.print()
        action = typer.prompt("  [a]pprove / [r]eject / [s]kip", default="a").lower()

        if action == "a":
            # Automatically route 'persona' domain to the personal tier
            tier = (
                "personal"
                if candidate.get("domain") in ("persona", "global")
                else "local"
            )
            dest_dir = blocks_dir / tier / candidate.get("domain", "unknown")
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / f"{candidate['id']}.yaml"
            path.rename(dest_path)
            console.print(f"  [green]✓ Approved and moved to {dest_path}[/green]\n")
            approved += 1
        elif action == "r":
            path.unlink()
            console.print("  [red]✗ Rejected and deleted.[/red]\n")
            rejected += 1
        else:
            console.print("  [dim]Skipped.[/dim]\n")

    if approved > 0:
        console.print(f"[green]✓ Approved {approved} new Expert Priors.[/green]")
        if typer.confirm("Rebuild index now?", default=True):
            _build(blocks_dir, _index_path(), data_dir=data_dir)
    elif rejected > 0:
        console.print(f"[dim]Rejected {rejected} candidates.[/dim]")
