"""CLI command: turnzero telemetry [on|off|status]."""

from __future__ import annotations

import typer

from turnzero.config import _data_dir, load_telemetry_config, save_telemetry_config

_HELP = "Manage anonymous usage telemetry (on / off / status)."


def telemetry(
    action: str = typer.Argument(
        "status", help="Action: on, off, or status."
    ),
) -> None:
    """Enable, disable, or check anonymous usage telemetry."""
    from rich.console import Console

    con = Console()
    data_dir = _data_dir()
    cfg = load_telemetry_config(data_dir)

    if action == "off":
        cfg["enabled"] = False
        save_telemetry_config(data_dir, cfg)
        con.print("[green]✓[/green] Telemetry disabled. No data will be sent.")
    elif action == "on":
        cfg["enabled"] = True
        save_telemetry_config(data_dir, cfg)
        con.print("[green]✓[/green] Telemetry enabled.")
    elif action == "status":
        enabled = cfg.get("enabled", True)
        anon_id = cfg.get("anonymous_id") or "(not yet generated — run 'turnzero setup')"
        status = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
        con.print(f"Telemetry: {status}")
        con.print(f"Anonymous ID: [dim]{anon_id}[/dim]")
        con.print(
            "\nWhat is collected: event names, domain names, block counts, "
            "client version, OS type."
        )
        con.print(
            "What is never collected: prompt text, prior content, "
            "file paths, API keys, or personal data."
        )
    else:
        con.print(f"[red]Unknown action '{action}'. Use: on, off, status.[/red]")
        raise typer.Exit(1)
