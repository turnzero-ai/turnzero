"""Proxy CLI sub-app — turnzero proxy serve/install/uninstall/status/setup."""

from __future__ import annotations

import secrets

import typer
from rich.console import Console

console = Console(stderr=True)

proxy_app = typer.Typer(
    name="proxy",
    help="Local HTTP proxy for compliance-free prior injection.",
    no_args_is_help=True,
)

proxy_setup_app = typer.Typer(
    name="setup",
    help="Configure IDE clients to route through the TurnZero proxy.",
    no_args_is_help=True,
)
proxy_app.add_typer(proxy_setup_app)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@proxy_app.command("serve")
def serve(
    port: int = typer.Option(9981, "--port", "-p", help="Port to listen on."),
    secret: str = typer.Option(
        ...,
        "--secret",
        envvar="TURNZERO_PROXY_SECRET",
        help="Shared secret — clients must send X-TurnZero-Secret: <secret>.",
    ),
) -> None:
    """Start the TurnZero proxy. Provider auto-detected from request model/key."""
    import uvicorn

    from turnzero.proxy.server import build_app

    app = build_app(secret=secret)
    console.print(
        f"\n[bold]TurnZero Proxy[/bold] → [cyan]http://127.0.0.1:{port}/v1[/cyan]\n"
        f"[dim]Point your IDE API base URL here.[/dim]\n"
        f"[dim]Set request header: X-TurnZero-Secret: {secret}[/dim]\n"
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@proxy_app.command("install")
def install(
    port: int = typer.Option(9981, "--port", "-p", help="Port for the daemon."),
    reset_secret: bool = typer.Option(
        False, "--reset-secret", help="Generate a new secret even if one already exists."
    ),
) -> None:
    """Install the proxy as a login daemon and configure detected IDE clients."""
    from turnzero.config import get_data_dir, load_config, save_config
    from turnzero.proxy import daemon

    data_dir = get_data_dir()
    cfg = load_config(data_dir)
    proxy_cfg: dict[str, object] = cfg.setdefault("proxy", {})

    # Generate secret once; persist so client setup commands read same value
    if not proxy_cfg.get("secret") or reset_secret:
        proxy_cfg["secret"] = secrets.token_urlsafe(32)
    proxy_cfg["port"] = port
    save_config(data_dir, cfg)

    secret = str(proxy_cfg["secret"])

    console.print(f"\n[bold]Installing TurnZero proxy daemon[/bold] (port {port})…")
    try:
        daemon.install(secret=secret, port=port)
    except RuntimeError as e:
        console.print(f"[red]Daemon install failed:[/red] {e}")
        raise typer.Exit(1)

    console.print("[green]✓[/green] Daemon installed — proxy starts automatically on login.")
    console.print(f"  [dim]Secret:[/dim] {secret}")
    console.print(f"  [dim]Port:[/dim]   {port}")

    # Auto-run client setup for detected clients
    console.print()
    _run_client_setup(port=port, secret=secret, silent_if_absent=True)


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


@proxy_app.command("uninstall")
def uninstall() -> None:
    """Stop and remove the proxy daemon."""
    from turnzero.proxy import daemon

    p = daemon.installed_path()
    if p is None:
        console.print("[yellow]Proxy daemon not installed.[/yellow]")
        return

    try:
        daemon.uninstall()
    except RuntimeError as e:
        console.print(f"[red]Uninstall failed:[/red] {e}")
        raise typer.Exit(1)

    console.print("[green]✓[/green] Proxy daemon removed.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@proxy_app.command("status")
def status() -> None:
    """Show proxy daemon status."""
    from turnzero.config import get_data_dir, load_config
    from turnzero.proxy import daemon

    running = daemon.status()
    installed = daemon.installed_path()

    if installed:
        state = "[green]running[/green]" if running else "[yellow]stopped[/yellow]"
        console.print(f"Proxy daemon: {state}")
        console.print(f"  [dim]Config:[/dim] {installed}")

        data_dir = get_data_dir()
        cfg = load_config(data_dir)
        proxy_cfg = cfg.get("proxy", {})
        if proxy_cfg.get("secret"):
            console.print(f"  [dim]Secret:[/dim] {proxy_cfg['secret']}")
        if proxy_cfg.get("port"):
            console.print(f"  [dim]Port:[/dim]   {proxy_cfg['port']}")
    else:
        console.print("Proxy daemon: [dim]not installed[/dim]")
        console.print("  Run [cyan]turnzero proxy install[/cyan] to set up.")


# ---------------------------------------------------------------------------
# setup sub-commands
# ---------------------------------------------------------------------------


def _proxy_cfg() -> tuple[int, str]:
    """Load port + secret from config. Raise if not installed yet."""
    from turnzero.config import get_data_dir, load_config

    data_dir = get_data_dir()
    cfg = load_config(data_dir)
    proxy_cfg = cfg.get("proxy", {})
    secret = proxy_cfg.get("secret")
    port = int(proxy_cfg.get("port", 9981))
    if not secret:
        console.print(
            "[yellow]No proxy secret found.[/yellow] "
            "Run [cyan]turnzero proxy install[/cyan] first."
        )
        raise typer.Exit(1)
    return port, secret


def _run_client_setup(port: int, secret: str, silent_if_absent: bool = False) -> None:
    """Run setup for all detected clients."""
    from turnzero.proxy.clients import (
        continue_installed,
        cursor_installed,
        cursor_instructions,
        patch_continue,
        windsurf_installed,
        windsurf_instructions,
    )

    any_found = False

    if cursor_installed():
        any_found = True
        console.print("[bold]Cursor detected[/bold]")
        cursor_instructions(port=port, secret=secret)

    if windsurf_installed():
        any_found = True
        console.print("[bold]Windsurf detected[/bold]")
        windsurf_instructions(port=port, secret=secret)

    if continue_installed():
        any_found = True
        console.print("[bold]Continue.dev detected[/bold] — patching config…")
        patch_continue(port=port, secret=secret)
        console.print("[green]✓[/green] ~/.continue/config.json updated.")

    if not any_found and not silent_if_absent:
        console.print("[dim]No supported IDE clients detected.[/dim]")


@proxy_setup_app.command("cursor")
def setup_cursor() -> None:
    """Print Cursor proxy setup instructions."""
    from turnzero.proxy.clients import cursor_installed, cursor_instructions

    port, secret = _proxy_cfg()
    if not cursor_installed():
        console.print("[yellow]Cursor not detected on this machine.[/yellow]")
        console.print("[dim]Instructions shown anyway:[/dim]")
    cursor_instructions(port=port, secret=secret)


@proxy_setup_app.command("windsurf")
def setup_windsurf() -> None:
    """Print Windsurf proxy setup instructions."""
    from turnzero.proxy.clients import windsurf_installed, windsurf_instructions

    port, secret = _proxy_cfg()
    if not windsurf_installed():
        console.print("[yellow]Windsurf not detected on this machine.[/yellow]")
        console.print("[dim]Instructions shown anyway:[/dim]")
    windsurf_instructions(port=port, secret=secret)


@proxy_setup_app.command("continue")
def setup_continue() -> None:
    """Patch ~/.continue/config.json with TurnZero proxy model entry."""
    from turnzero.proxy.clients import patch_continue

    port, secret = _proxy_cfg()
    patch_continue(port=port, secret=secret)
    console.print("[green]✓[/green] ~/.continue/config.json updated.")
    console.print(
        "  [dim]Set your API key in the 'apiKey' field for the TurnZero Proxy model.[/dim]"
    )
