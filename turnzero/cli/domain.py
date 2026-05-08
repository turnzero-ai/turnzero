"""Domain management — enable/disable community Expert Prior domains."""

from __future__ import annotations

import typer
from rich import box
from rich.table import Table

from turnzero.cli.base import console, err_console
from turnzero.config import (
    DEFAULT_ACTIVE_DOMAINS,
    get_active_domains,
    get_data_dir,
    load_config,
    save_config,
)

domain_app = typer.Typer(
    help="Manage which Expert Prior domains are active.",
    no_args_is_help=True,
)


@domain_app.command(name="list")
def domain_list() -> None:
    """Show active and available domains."""
    from turnzero.config import get_blocks_dir, get_bundled_blocks_dir
    from turnzero.repositories.block_repo import load_all_blocks

    data_dir = get_data_dir()
    active = get_active_domains(data_dir)

    try:
        blocks_dir = get_blocks_dir()
        if not blocks_dir.exists():
            blocks_dir = get_bundled_blocks_dir()
        blocks = load_all_blocks(blocks_dir)
    except FileNotFoundError:
        blocks = {}

    from collections import Counter
    domain_counts: Counter[str] = Counter(
        b.domain for b in blocks.values() if b.tier != "personal"
    )

    if not domain_counts:
        console.print("[yellow]No community blocks found. Run: turnzero setup[/yellow]")
        raise typer.Exit(1)

    console.print()
    if active is None:
        console.print("[bold]Expert Prior Domains[/bold]  [dim](all active — no filter set)[/dim]\n")
    else:
        console.print(
            f"[bold]Expert Prior Domains[/bold]  "
            f"[dim]({len(active)} active of {len(domain_counts)} available)[/dim]\n"
        )

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("domain", style="cyan", min_width=20)
    tbl.add_column("blocks", justify="right", min_width=6)
    tbl.add_column("status", min_width=10)

    for d, count in sorted(domain_counts.items()):
        if active is None or d in active:
            status = "[green]active[/green]"
        else:
            status = "[dim]inactive[/dim]"
        tbl.add_row(d, str(count), status)

    console.print(tbl)

    if active is not None:
        console.print(
            "[dim]turnzero domain add <name>[/dim]   [dim]turnzero domain remove <name>[/dim]\n"
        )
    else:
        console.print(
            "[dim]All domains active. Use [/dim][cyan]turnzero domain add <name>[/cyan]"
            "[dim] to start a curated list.[/dim]\n"
        )


@domain_app.command()
def add(
    name: str = typer.Argument(..., help="Domain name to activate (e.g. langchain)."),
) -> None:
    """Activate a domain so its blocks are included in retrieval."""
    data_dir = get_data_dir()
    cfg = load_config(data_dir)
    current = cfg.get("active_domains")

    if current is None:
        # First explicit add: initialise from defaults so we don't wipe everything
        current = list(DEFAULT_ACTIVE_DOMAINS)

    if name in current:
        console.print(f"[dim]'{name}' is already active.[/dim]")
        return

    current = sorted({*current, name})
    cfg["active_domains"] = current
    save_config(data_dir, cfg)
    from turnzero.telemetry import track_domain_changed
    track_domain_changed("add", name, len(current))
    console.print(f"[green]✓[/green] Domain '[bold]{name}[/bold]' added. "
                  f"{len(current)} domain(s) now active.")


@domain_app.command()
def remove(
    name: str = typer.Argument(..., help="Domain name to deactivate."),
) -> None:
    """Deactivate a domain so its blocks are excluded from retrieval."""
    data_dir = get_data_dir()
    cfg = load_config(data_dir)
    current = cfg.get("active_domains")

    if current is None:
        # All active — initialise from defaults then remove
        current = list(DEFAULT_ACTIVE_DOMAINS)

    if name not in current:
        console.print(f"[dim]'{name}' is not in the active list.[/dim]")
        return

    updated = [d for d in current if d != name]
    if not updated:
        err_console.print(
            "[red]Cannot remove last domain — active_domains would be empty "
            "(no expert blocks would fire). Add another domain first.[/red]"
        )
        raise typer.Exit(1)

    cfg["active_domains"] = updated
    save_config(data_dir, cfg)
    from turnzero.telemetry import track_domain_changed
    track_domain_changed("remove", name, len(updated))
    console.print(f"[dim]✓ Domain '[bold]{name}[/bold]' removed. "
                  f"{len(updated)} domain(s) active.[/dim]")


@domain_app.command()
def reset() -> None:
    """Reset active domains to the default set."""
    data_dir = get_data_dir()
    cfg = load_config(data_dir)
    cfg["active_domains"] = list(DEFAULT_ACTIVE_DOMAINS)
    save_config(data_dir, cfg)
    from turnzero.telemetry import track_domain_changed
    track_domain_changed("reset", "", len(DEFAULT_ACTIVE_DOMAINS))
    console.print(
        f"[green]✓[/green] Active domains reset to defaults "
        f"({len(DEFAULT_ACTIVE_DOMAINS)}): "
        + "  ".join(f"[cyan]{d}[/cyan]" for d in DEFAULT_ACTIVE_DOMAINS)
    )
