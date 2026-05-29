"""Proxy CLI sub-app — turnzero proxy serve."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console(stderr=True)

proxy_app = typer.Typer(
    name="proxy",
    help="Local HTTP proxy for compliance-free prior injection.",
    no_args_is_help=True,
)


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
