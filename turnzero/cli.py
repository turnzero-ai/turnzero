"""TurnZero CLI — query, show, inject, stats, index build/verify."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="turnzero",
    help="TurnZero — AI Expert Prior injection for developer sessions.",
    no_args_is_help=True,
)
index_app = typer.Typer(help="Manage the embedding index.", no_args_is_help=True)
app.add_typer(index_app, name="index")

source_app = typer.Typer(help="Enable or disable Expert Prior sources (local/community/enterprise).", no_args_is_help=True)
app.add_typer(source_app, name="source")

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def _blocks_dir() -> Path:
    return _data_dir() / "blocks"


def _bundled_index_path() -> Path:
    """Return the pre-built index shipped inside the package (no setup needed)."""
    pkg = Path(__file__).parent / "data" / "index.jsonl"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "index.jsonl"
    if repo.exists():
        return repo
    return _index_path()


def _bundled_blocks_dir() -> Path:
    """Return the blocks directory shipped inside the package (no setup needed)."""
    pkg = Path(__file__).parent / "data" / "blocks"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent / "data" / "blocks"
    if repo.exists():
        return repo
    return _blocks_dir()


def _index_path() -> Path:
    return _data_dir() / "index.jsonl"


# ---------------------------------------------------------------------------
# Preview command — zero-setup demo
# ---------------------------------------------------------------------------

@app.command()
def preview(
    prompt: str = typer.Argument(..., help="Opening prompt to preview injection for."),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Max blocks to show."),
    threshold: float = typer.Option(0.75, "--threshold", "-t", help="Minimum similarity score."),
) -> None:
    """Preview which Expert Priors would be injected for a prompt.

    Works immediately after pip install — no setup, no ollama, no configuration.
    Uses the pre-built index bundled with the package.

    \b
    Example:
      turnzero preview "Building a REST API with FastAPI and PostgreSQL"
      turnzero preview "goroutine leaking in my HTTP handler"
    """
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index, query as _query

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
        console.print(f"\n[dim]No blocks above threshold {threshold} for this prompt.[/dim]")
        console.print("[dim]Try a more specific technical prompt, or lower --threshold.[/dim]\n")
        return

    total_weight = sum(b.context_weight for b, _ in results)
    console.print(f"\n[bold]TurnZero Preview[/bold]  [dim]({len(results)} block(s), ~{total_weight} tokens)[/dim]\n")

    for block, score in results:
        title = getattr(block, "title", None) or block.slug
        console.print(f"  [bold cyan]{title}[/bold cyan]  [dim]{block.domain}/{block.intent}  score={score:.2f}[/dim]")

        constraints = block.constraints
        anti_patterns = block.anti_patterns

        if constraints:
            console.print(f"    [green]constraints:[/green]")
            for c in constraints[:3]:
                console.print(f"      • {c}")
            if len(constraints) > 3:
                console.print(f"      [dim]… +{len(constraints) - 3} more[/dim]")

        if anti_patterns:
            console.print(f"    [red]anti-patterns:[/red]")
            for a in anti_patterns[:2]:
                console.print(f"      • {a}")
            if len(anti_patterns) > 2:
                console.print(f"      [dim]… +{len(anti_patterns) - 2} more[/dim]")

        console.print()

    console.print(
        "[dim]This is what TurnZero injects at Turn 0 of your AI session.[/dim]\n"
        "[dim]To activate: [/dim][cyan]turnzero setup[/cyan]\n"
    )


# ---------------------------------------------------------------------------
# Hook template
# ---------------------------------------------------------------------------

def _generate_hook(python_path: str, data_dir: Path) -> str:
    return f'''\
#!/usr/bin/env python3
"""TurnZero UserPromptSubmit hook — auto-inject Expert Priors at Turn 0.

Generated by `turnzero setup`. Re-run `turnzero setup --force` to regenerate.
Fires on every user message but only injects on the first turn of a session.
Silent on any error or timeout.
"""
from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

DATA_DIR = Path("{data_dir}")
STATS_FILE = DATA_DIR / "hook_stats.json"
MIN_PROMPT_LEN = 15
MIN_PROMPT_WORDS = 10
TIMEOUT_SECS = 5
VENV_PYTHON = "{python_path}"

# Ensure the venv that has turnzero installed is on sys.path
import subprocess as _sp, sys as _sys
_site = _sp.run(
    [VENV_PYTHON, "-c", "import site; print(site.getsitepackages()[0])"],
    capture_output=True, text=True,
).stdout.strip()
if _site and _site not in _sys.path:
    _sys.path.insert(0, _site)


def _bail(_signum=None, _frame=None) -> None:
    sys.exit(0)


def _load_stats() -> dict:
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {{"total_priors_injected": 0}}


def _save_stats(stats: dict) -> None:
    try:
        STATS_FILE.write_text(json.dumps(stats), encoding="utf-8")
    except Exception:
        pass


signal.signal(signal.SIGALRM, _bail)
signal.alarm(TIMEOUT_SECS)

try:
    data = json.loads(sys.stdin.read())

    transcript = data.get("transcript", [])
    if any(m.get("role") == "assistant" for m in transcript):
        sys.exit(0)

    prompt = data.get("prompt", "").strip()
    if len(prompt) < MIN_PROMPT_LEN:
        sys.exit(0)
    if len(prompt.split()) < MIN_PROMPT_WORDS:
        sys.exit(0)

    os.environ["TURNZERO_DATA_DIR"] = str(DATA_DIR)
    if not os.environ.get("OPENAI_API_KEY"):
        _key_file = Path.home() / ".turnzero" / "openai_key"
        if _key_file.exists():
            os.environ["OPENAI_API_KEY"] = _key_file.read_text().strip()

    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import is_implementation_prompt, load_index
    from turnzero.retrieval import query as _query

    if not is_implementation_prompt(prompt):
        sys.exit(0)

    blocks = load_all_blocks(DATA_DIR / "blocks")
    index = load_index(DATA_DIR / "index.jsonl")
    results = _query(
        prompt, index, blocks,
        top_k=3, threshold=0.75, context_weight=4000, strict_intent=True,
    )

    if not results:
        sys.exit(0)

    stats = _load_stats()
    stats["total_priors_injected"] = stats.get("total_priors_injected", 0) + len(results)
    stats["last_session_injected"] = len(results)
    _save_stats(stats)
    total = stats["total_priors_injected"]

    # Append structured entry to hook_log.jsonl for stats command
    import time as _time
    _log_entry = json.dumps({{
        "ts": _time.time(),
        "blocks": [b.slug for b, _ in results],
        "domains": list({{b.domain for b, _ in results}}),
        "prompt_words": len(prompt.split()),
    }})
    try:
        with open(DATA_DIR / "hook_log.jsonl", "a", encoding="utf-8") as _lf:
            _lf.write(_log_entry + "\\n")
    except Exception:
        pass

    names = " · ".join(b.slug for b, _ in results)
    print(f"[TurnZero] Auto-injecting {{len(results)}} Expert Prior(s): {{names}}\\n")
    for block, _score in results:
        print(block.to_injection_text())
        print()
    print(
        "INSTRUCTION: You have been given Expert Priors above by TurnZero. "
        "Start your response with exactly one line acknowledging them, formatted as:\\n"
        f"  > 📎 TurnZero applied: {{names}} _({{total}} total)_\\n"
        "Then continue with your normal response. Do not explain what TurnZero is."
    )

except Exception:
    sys.exit(0)
'''


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def setup(
    data_dir: Path = typer.Option(
        None, "--data-dir", "-d",
        help="Where to store blocks and index. Default: ~/.turnzero",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing MCP config."),
    with_hook: bool = typer.Option(
        False, "--with-hook",
        help="Also install the Claude Code UserPromptSubmit hook for guaranteed injection regardless of model behaviour.",
    ),
    openai_key: str = typer.Option(
        None, "--openai-key",
        help="OpenAI API key for cloud embedding fallback (stored at ~/.turnzero/openai_key).",
        envvar="OPENAI_API_KEY",
    ),
) -> None:
    """One-command setup: register MCP server and build index.

    Registers the TurnZero MCP server globally. Any MCP-compatible AI client
    (Claude Code, Cursor, Claude Desktop) will automatically call
    list_suggested_blocks on Turn 0 and inject Expert Priors.

    Use --with-hook to also install the Claude Code UserPromptSubmit hook
    for guaranteed injection regardless of model behaviour.
    """
    import json
    import shutil
    import subprocess
    import sys

    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(exist_ok=True)

    resolved = (data_dir or Path.home() / ".turnzero").expanduser().resolve()

    console.print(f"\n[bold]TurnZero Setup[/bold]\n")
    console.print(f"Data directory: [cyan]{resolved}[/cyan]\n")

    # Persist OpenAI key if provided
    if openai_key:
        key_file = resolved / "openai_key"
        resolved.mkdir(parents=True, exist_ok=True)
        key_file.write_text(openai_key.strip(), encoding="utf-8")
        key_file.chmod(0o600)
        os.environ["OPENAI_API_KEY"] = openai_key.strip()
        console.print("[green]✓[/green] OpenAI API key saved\n")
    elif (resolved / "openai_key").exists():
        os.environ["OPENAI_API_KEY"] = (resolved / "openai_key").read_text().strip()
        console.print("[dim]✓ OpenAI API key loaded from previous setup[/dim]\n")

    # ── 1. Copy blocks ────────────────────────────────────────────────────
    # pip install → blocks land at turnzero/data/blocks/ inside the wheel
    # pip install -e . (dev) → fall back to repo's data/blocks/
    pkg_blocks = Path(__file__).parent / "data" / "blocks"
    repo_blocks = Path(__file__).parent.parent / "data" / "blocks"
    source_blocks = pkg_blocks if pkg_blocks.exists() else repo_blocks
    dest_blocks = resolved / "blocks"

    if source_blocks.exists():
        if not dest_blocks.exists() or force:
            if dest_blocks.exists():
                shutil.rmtree(dest_blocks)
            shutil.copytree(source_blocks, dest_blocks)
            n = len(list(dest_blocks.glob("*.yaml")))
            console.print(f"[green]✓[/green] Copied {n} blocks → {dest_blocks}")
        else:
            n = len(list(dest_blocks.glob("*.yaml")))
            console.print(f"[dim]✓ {n} blocks already at {dest_blocks}[/dim]")
    else:
        console.print(
            "[yellow]⚠[/yellow]  Source blocks not found — "
            "copy your blocks/ directory to [cyan]{dest_blocks}[/cyan] manually."
        )

    # ── 2. Check embedding backend ────────────────────────────────────────
    console.print()
    ollama_ok = False

    # Check ollama
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        if "nomic-embed-text" in result.stdout:
            console.print("[green]✓[/green] Embedding backend: ollama + nomic-embed-text")
            ollama_ok = True
        else:
            console.print("[yellow]⚠[/yellow]  ollama found but nomic-embed-text not pulled — run: [cyan]ollama pull nomic-embed-text[/cyan]")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check sentence-transformers
    if not ollama_ok:
        try:
            import importlib
            importlib.import_module("sentence_transformers")
            console.print("[green]✓[/green] Embedding backend: sentence-transformers")
            ollama_ok = True
        except ImportError:
            pass

    # Check OpenAI
    if not ollama_ok and os.environ.get("OPENAI_API_KEY"):
        console.print("[green]✓[/green] Embedding backend: OpenAI API")
        ollama_ok = True

    # Nothing found — show clear options
    if not ollama_ok:
        console.print("[yellow]⚠[/yellow]  No embedding backend found. TurnZero needs one to work.\n")
        console.print("    [bold]Option 1[/bold] — ollama (local, no internet after setup):")
        console.print("      [cyan]ollama serve && ollama pull nomic-embed-text[/cyan]\n")
        console.print("    [bold]Option 2[/bold] — sentence-transformers (local, no server, ~500MB):")
        console.print("      [cyan]pip install 'turnzero[local]'[/cyan]\n")
        console.print("    [bold]Option 3[/bold] — OpenAI API (cloud):")
        console.print("      [cyan]turnzero setup --openai-key sk-...[/cyan]\n")
        console.print("    Re-run [cyan]turnzero setup[/cyan] after installing a backend.")

    # ── 3. Build index ────────────────────────────────────────────────────
    console.print()
    index_path = resolved / "index.jsonl"
    if ollama_ok and dest_blocks.exists():
        if not index_path.exists() or force:
            console.print("Building embedding index…")
            env = os.environ.copy()
            env["TURNZERO_DATA_DIR"] = str(resolved)
            try:
                subprocess.run(
                    [sys.executable, "-m", "turnzero.cli", "index", "build"],
                    env=env, check=True,
                )
                console.print("[green]✓[/green] Index built")
            except subprocess.CalledProcessError:
                console.print("[red]✗ Index build failed — check ollama is running[/red]")
        else:
            console.print("[dim]✓ Index already exists[/dim]")
    else:
        console.print(
            "[dim]Skipping index build. Once ollama is ready, run:[/dim]\n"
            "  [cyan]TURNZERO_DATA_DIR={resolved} turnzero index build[/cyan]"
        )

    # ── 4. Write hook script (optional) ──────────────────────────────────
    console.print()
    if with_hook:
        hook_path = claude_dir / "turnzero-hook.py"
        if not hook_path.exists() or force:
            hook_path.write_text(_generate_hook(sys.executable, resolved), encoding="utf-8")
            hook_path.chmod(0o755)
            console.print(f"[green]✓[/green] Hook written → {hook_path}")
        else:
            console.print(f"[dim]✓ Hook already exists ({hook_path}) — use --force to regenerate[/dim]")

        # ── 5. Register hook in ~/.claude/settings.json ───────────────────
        settings_path = claude_dir / "settings.json"
        settings: dict = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        hook_command = f"{sys.executable} {hook_path}"
        hook_entry = {"type": "command", "command": hook_command, "timeout": 6}
        hooks = settings.setdefault("hooks", {})
        submit_hooks = hooks.setdefault("UserPromptSubmit", [{"hooks": []}])
        hook_list = submit_hooks[0].setdefault("hooks", [])
        already = any("turnzero-hook.py" in h.get("command", "") for h in hook_list)
        if not already:
            hook_list.append(hook_entry)
            settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            console.print(f"[green]✓[/green] Hook registered in {settings_path}")
        else:
            console.print(f"[dim]✓ Hook already registered in settings.json[/dim]")
    else:
        console.print("[dim]Hook not installed (MCP server is enough for most clients — use --with-hook for Claude Code guarantee)[/dim]")

    # ── 6. Register MCP in ~/.claude.json ────────────────────────────────
    claude_json = Path.home() / ".claude.json"
    cfg: dict = {}
    if claude_json.exists():
        try:
            cfg = json.loads(claude_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    mcp_bin = str(Path(sys.executable).parent / "turnzero-mcp")
    mcp_entry = {
        "type": "stdio",
        "command": mcp_bin,
        "env": {"TURNZERO_DATA_DIR": str(resolved)},
    }
    servers = cfg.setdefault("mcpServers", {})
    if "turnzero" not in servers or force:
        servers["turnzero"] = mcp_entry
        claude_json.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        console.print(f"[green]✓[/green] MCP server registered in {claude_json}")
    else:
        console.print(f"[dim]✓ MCP server already registered in .claude.json[/dim]")

    # ── 7. Summary ────────────────────────────────────────────────────────
    console.print()
    if ollama_ok and index_path.exists():
        console.print("[bold green]✓ Setup complete![/bold green]\n")
        console.print(
            "Start a [bold]new[/bold] Claude Code session and paste this prompt to verify:\n\n"
            "  [cyan]Building a FastAPI REST API with Pydantic models and async SQLAlchemy[/cyan]\n\n"
            "TurnZero will inject Expert Priors automatically on Turn 0.\n"
            "Add [cyan]--with-hook[/cyan] for an extra guarantee on Claude Code."
        )
    else:
        console.print("[bold yellow]Partial setup complete.[/bold yellow]\n")
        console.print(
            "Once ollama is ready, re-run:\n\n"
            "  [cyan]turnzero setup --force[/cyan]"
        )


@app.command()
def query(
    prompt: str = typer.Argument(..., help="Opening prompt to find blocks for."),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Maximum blocks to return."),
    threshold: float = typer.Option(0.75, "--threshold", "-t", help="Minimum cosine similarity."),
    context_weight: int = typer.Option(4000, "--weight", help="Max total weight across injected blocks."),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Confirm each block before including."),
    strict_intent: bool = typer.Option(True, "--strict/--no-strict", help="Only return blocks matching detected intent."),
    rerank: str = typer.Option(None, "--rerank", "-r", help="Local LLM model to use for second-stage reranking (e.g. llama3.2)."),
    session: str = typer.Option("default", "--session", "-s", help="Session ID for cumulative ROI tracking."),
) -> None:
    """Suggest Expert Priors for an opening prompt."""
    from turnzero.analytics import SessionAnalytics, get_global_roi
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import classify_intent, load_index
    from turnzero.retrieval import query as _query

    try:
        blocks = load_all_blocks(_blocks_dir())
        index = load_index(_index_path())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Load session analytics
    analytics = SessionAnalytics.load(session, _data_dir())

    intent = classify_intent(prompt)
    results = _query(
        prompt, index, blocks,
        top_k=top_k, threshold=threshold, context_weight=context_weight,
        strict_intent=strict_intent,
        project_root=Path.cwd(),
        rerank_model=rerank,
    )

    if not results:
        console.print(f"[yellow]No blocks found above threshold {threshold:.2f} (intent: {intent}).[/yellow]")
        console.print("[dim]Try --no-strict or adding more blocks to data/blocks/[/dim]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Suggested Expert Priors[/bold] for: [italic]\"{prompt[:80]}\"[/italic]")
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
            preview = block.constraints[0][:90]
            console.print(f"     [dim]\"{preview}{'...' if len(block.constraints[0]) > 90 else ''}\"[/dim]")
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
    console.print(f"[{weight_color}]Total injection weight: {total_weight:,}[/{weight_color}]")

    # Value Analytics (Scientific ROI)
    roi = analytics.calculate_roi()
    global_roi = get_global_roi(_data_dir())
    
    console.print(f"\n[bold green]Scientific ROI (Correction Avoidance):[/bold green]")
    console.print(f"  [dim]• Session Saved:  ~{roi['tokens_saved']:,} tokens | ~{roi['minutes_saved']} min ({roi['turns_saved']} turns)[/dim]")
    console.print(f"  [dim]• Global Impact:  ~{global_roi['total_minutes_saved']:,} min total saved across {global_roi['total_sessions']} sessions[/dim]")

    if selected:
        ids = " ".join(b.slug for b in selected)
        console.print(f"\nRun: [bold green]turnzero inject {ids}[/bold green]")


@app.command()
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
    console.print(f"[dim]domain: {block.domain}  intent: {block.intent}  weight: {block.context_weight}[/dim]")
    console.print(f"[dim]hash: {block.hash}[/dim]")
    console.print(f"[dim]tags: {', '.join(block.tags)}[/dim]")
    console.print(f"[dim]verified: {block.last_verified}[/dim]")
    if block.provides:
        console.print(f"[dim]provides: {', '.join(block.provides)}[/dim]")
    if block.conflicts_with_tags:
        console.print(f"[dim]conflicts with tags: {', '.join(block.conflicts_with_tags)}[/dim]")
    if block.conflicts_with:
        console.print(f"[dim]conflicts with slugs: {', '.join(block.conflicts_with)}[/dim]")
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


@app.command()
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


@app.command()
def feedback(
    prompt: str = typer.Option(..., "--prompt", "-p", help="The opening prompt that was used."),
    correction: str = typer.Option(..., "--correction", "-c", help="The correction text (what the user clarified)."),
    slug: str = typer.Option(None, "--slug", "-s", help="The slug of the block that was suggested/injected (optional)."),
) -> None:
    """Log user feedback/correction when a suggestion was missed or incorrect."""
    import json
    import time

    feedback_data = {
        "timestamp": int(time.time()),
        "prompt": prompt,
        "correction": correction,
        "slug": slug,
    }

    feedback_file = _data_dir() / "feedback.jsonl"
    _data_dir().mkdir(parents=True, exist_ok=True)

    with feedback_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(feedback_data) + "\n")

    console.print(f"[green]✓ Feedback logged to {feedback_file}[/green]")
    console.print("[dim]This data will be used to improve future Expert Prior extractions.[/dim]")


@app.command()
def stats() -> None:
    """Show injection history and block library statistics."""
    import json
    import time
    from collections import Counter
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index

    data_dir = _data_dir()

    # ── Live injection log (written by hook) ─────────────────────────────
    log_path = data_dir / "hook_log.jsonl"
    entries: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    now = time.time()
    week_ago = now - 7 * 86400

    sessions_total = len(entries)
    sessions_week = sum(1 for e in entries if e.get("ts", 0) >= week_ago)
    priors_total = sum(len(e.get("blocks", [])) for e in entries)
    priors_week = sum(len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago)

    block_counts: Counter = Counter()
    domain_counts: Counter = Counter()
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
        usage.add_row("", "[dim]Start a new Claude Code session with a specific tech prompt[/dim]")
    else:
        usage.add_row("Sessions with injection", f"[bold]{sessions_total}[/bold]  [dim](+{sessions_week} this week)[/dim]")
        usage.add_row("Expert Priors applied", f"[bold]{priors_total}[/bold]  [dim](+{priors_week} this week)[/dim]")
        usage.add_row(
            "Est. turns saved",
            f"[bold green]~{est_turns}[/bold green]  [dim](~{int(est_tokens/1000)}k tokens)[/dim]",
        )
        if top_domains:
            usage.add_row("Top domains", "  ".join(f"[cyan]{d}[/cyan]" for d in top_domains))
        if top_blocks:
            usage.add_row(
                "Top priors",
                "  ".join(f"{slug.split('-')[0]}… ({n}×)" for slug, n in top_blocks),
            )

    console.print(usage)

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


# ---------------------------------------------------------------------------
@app.command()
def autolearn(
    conversations_dir: Path = typer.Option(
        Path("data/conversations"),
        "--dir", "-d",
        help="Directory to watch for new conversation logs.",
    ),
    interval: int = typer.Option(10, "--interval", "-i", help="Polling interval in seconds."),
    model: str = typer.Option("llama3.2", "--model", "-m", help="Local ollama model to use."),
) -> None:
    """Start the Auto-Learn daemon.

    Automatically extracts Expert Priors from new files in the conversations
    directory and updates the search index.
    """
    import time

    from turnzero.harvest import harvest as _harvest
    from turnzero.harvest import write_candidate
    from turnzero.index import build as _build

    if not conversations_dir.exists():
        console.print(f"[bold yellow]Creating directory:[/bold yellow] {conversations_dir}")
        conversations_dir.mkdir(parents=True, exist_ok=True)

    processed_file = _data_dir() / ".processed"
    processed: set[str] = set()
    if processed_file.exists():
        processed = set(processed_file.read_text().splitlines())

    console.print(f"[bold green]Auto-Learn daemon started.[/bold green]")
    console.print(f"[dim]Watching {conversations_dir} (interval: {interval}s, model: {model})[/dim]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        while True:
            new_files = [
                f for f in conversations_dir.iterdir()
                if f.is_file() and f.name not in processed and not f.name.startswith(".")
            ]

            if new_files:
                console.print(f"[bold blue]Found {len(new_files)} new conversation(s).[/bold blue]")
                any_written = False

                for f in new_files:
                    console.print(f"  Processing [italic]{f.name}[/italic] ...")
                    try:
                        candidates = _harvest(f, _blocks_dir(), model=model, dry_run=False)
                        for candidate in candidates:
                            write_candidate(candidate, _blocks_dir())
                            console.print(f"    [green]✓ Expert Prior extracted:[/green] {candidate['id']}")
                        processed.add(f.name)
                        any_written = True
                    except Exception as e:
                        err_console.print(f"    [red]Error processing {f.name}: {e}[/red]")

                # Persist processed list
                processed_file.write_text("\n".join(sorted(processed)))

                if any_written:
                    console.print("  Updating search index ...")
                    _build(_blocks_dir(), _index_path())
                    console.print("  [green]✓ Index updated.[/green]")

                console.print("[dim]Waiting for new files...[/dim]\n")

            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Auto-Learn daemon stopped.[/bold yellow]")


# ---------------------------------------------------------------------------
# Harvest command — mine Claude Code sessions for Expert Prior candidates
# ---------------------------------------------------------------------------

@app.command()
def harvest(
    sessions_dir: Path = typer.Option(
        None, "--sessions-dir", "-s",
        help="Override auto-discovery and scan a single directory.",
    ),
    file: Path = typer.Option(
        None, "--file", "-f",
        help="Harvest a single file (any supported format) instead of scanning sessions.",
    ),
    model: str = typer.Option("llama3.2", "--model", "-m", help="ollama model, or set OPENAI_API_KEY / ANTHROPIC_API_KEY for cloud."),
    auto_approve: bool = typer.Option(False, "--auto-approve", "-y", help="Add all candidates directly to library without review."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be found without writing."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to process per run. Run again to continue."),
    workers: int = typer.Option(None, "--workers", "-w", help="Parallel workers for LLM extraction (default: CPU count)."),
) -> None:
    """Scan your AI sessions and extract Expert Prior candidates.

    Auto-discovers sessions from Claude Code, Aider, Cursor, and Windsurf.
    Use --file to import any conversation manually.
    Works with ollama (local), OpenAI, or Anthropic — whichever key is set.

    Processes --limit sessions per run. Run again to continue with the next batch.

    \b
    Auto-discovered tools:
      Claude Code  ~/.claude/projects/**/*.jsonl
      Aider        ~/{Development,dev,code}/**/.aider.chat.history.md
      Cursor       ~/Library/Application Support/Cursor/...
      Windsurf     ~/Library/Application Support/Windsurf/...

    \b
    Supported file formats (--file or auto):
      ChatGPT      conversations.json export
      OpenAI SDK   [{role, content}] JSON
      Markdown     any User:/Assistant: or #### user markers
    """
    from turnzero.harvest import load_conversation, scan_new_sessions
    from turnzero.harvest import extract_with_llm, parse_candidates, write_candidate
    from turnzero.harvest import is_self_referential, validate_candidate
    from turnzero.index import build as _build

    data_dir = _data_dir()
    candidates_dir = data_dir / "candidates"
    processed_file = data_dir / ".sessions_processed"

    # --file mode: harvest a single explicitly provided file
    if file is not None:
        if not file.exists():
            err_console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)
        sessions = [file]
    else:
        sessions = scan_new_sessions(processed_file, sessions_dir=sessions_dir)

    if not sessions:
        console.print("[dim]No new sessions to analyse.[/dim]")
        console.print("[dim]Use --file to import a conversation manually, or start a session in a supported AI tool first.[/dim]")
        return

    total_found = len(sessions)
    batch = sessions[:limit]
    console.print(
        f"\nFound [bold]{total_found}[/bold] new session(s). "
        f"Processing [bold]{len(batch)}[/bold] this run "
        f"{'(all)' if len(batch) == total_found else f'— run again for the next batch'}.\n"
    )

    dest_dir = _blocks_dir() if auto_approve else candidates_dir
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    processed: set[str] = set()
    if processed_file.exists():
        processed = set(processed_file.read_text(encoding="utf-8").splitlines())

    import os as _os
    workers = workers or _os.cpu_count() or 4

    total_candidates = 0
    llm_fatal = False

    def _process(session_path: Path) -> tuple[Path, list, str | None, str | None]:
        """Returns (path, candidates, fatal_error, skip_reason)."""
        try:
            conversation = load_conversation(session_path)
            word_count = len(conversation.split())
            if word_count < 100:
                return session_path, [], None, f"Too short ({word_count} words)"
            if is_self_referential(conversation):
                return session_path, [], None, "self-referential session"
            raw = extract_with_llm(conversation, model=model)
            candidates = parse_candidates(raw)
            valid = []
            for c in candidates:
                err = validate_candidate(c)
                if err:
                    raise ValueError(f"invalid candidate '{c.get('id', '?')}': {err}")
                valid.append(c)
            return session_path, valid, None, None
        except RuntimeError as e:
            return session_path, [], str(e), None
        except Exception as e:
            return session_path, [], None, str(e)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {executor.submit(_process, sp): (idx, sp) for idx, sp in enumerate(batch, 1)}
        for future in as_completed(future_to_path):
            idx, session_path = future_to_path[future]
            label = f"  [{idx}/{len(batch)}] [dim]{session_path.parent.name[:28]}/{session_path.stem[:14]}[/dim]"
            sp_path, candidates, fatal, skip = future.result()

            if fatal:
                console.print(label)
                err_console.print(f"    [red]Error: {fatal}[/red]")
                llm_fatal = True
                continue

            console.print(label)

            if skip:
                console.print(f"    [dim]{skip} — skip.[/dim]")
                processed.add(str(session_path))
                continue

            if not candidates:
                console.print("    [dim]no candidates[/dim]")
            else:
                for candidate in candidates:
                    cid = str(candidate.get("id", "unknown"))
                    if dry_run:
                        console.print(f"    [blue]would extract:[/blue] {cid}")
                    else:
                        write_candidate(candidate, dest_dir)
                        clabel = "[green]✓ added:[/green]" if auto_approve else "[green]✓ candidate:[/green]"
                        console.print(f"    {clabel} {cid}")
                    total_candidates += 1

            processed.add(str(session_path))

    if llm_fatal:
        pass  # processed already excludes failed sessions

    if not dry_run:
        processed_file.write_text("\n".join(sorted(processed)), encoding="utf-8")

    remaining = total_found - len(batch)
    if total_candidates > 0 and not dry_run:
        if auto_approve:
            console.print(f"\nRebuilding index with {total_candidates} new block(s)...")
            count = _build(_blocks_dir(), _index_path())
            console.print(f"[bold green]✓ {total_candidates} block(s) added. Index now has {count} entries.[/bold green]")
        else:
            console.print(f"\n[bold green]✓ {total_candidates} candidate(s) staged for review.[/bold green]")
            console.print("Run [bold]turnzero review[/bold] to approve and add to your library.")
    elif total_candidates == 0:
        console.print("\n[dim]No new Expert Priors found in this batch.[/dim]")

    if remaining > 0:
        console.print(f"[dim]{remaining} session(s) remaining — run harvest again for the next batch.[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Review command — approve/reject harvested candidates
# ---------------------------------------------------------------------------

@app.command()
def review() -> None:
    """Review Expert Prior candidates extracted from your sessions.

    Shows each candidate and prompts for approval.
    Approved candidates are added to your block library and the index is rebuilt.
    """
    from turnzero.index import build as _build

    data_dir = _data_dir()
    candidates_dir = data_dir / "candidates"

    if not candidates_dir.exists() or not list(candidates_dir.glob("*.yaml")):
        console.print("[dim]No candidates to review. Run [bold]turnzero harvest[/bold] first.[/dim]")
        return

    pending = sorted(candidates_dir.glob("*.yaml"))
    console.print(f"\n[bold]📋 {len(pending)} candidate(s) to review[/bold]\n")

    approved = 0
    rejected = 0

    for path in pending:
        content = path.read_text(encoding="utf-8")
        console.rule(f"[bold]{path.stem}[/bold]")
        console.print(content)

        choice = typer.prompt("  Approve? [y]es / [n]o / [s]kip", default="s").strip().lower()

        if choice in ("y", "yes"):
            dest = _blocks_dir() / path.name
            dest.write_text(content, encoding="utf-8")
            path.unlink()
            console.print(f"  [green]✓ Added to library.[/green]\n")
            approved += 1
        elif choice in ("n", "no"):
            path.unlink()
            console.print(f"  [red]✗ Rejected and deleted.[/red]\n")
            rejected += 1
        else:
            console.print(f"  [dim]Skipped — still in candidates/.[/dim]\n")

    if approved > 0:
        console.print(f"Rebuilding index with {approved} new block(s)...")
        count = _build(_blocks_dir(), _index_path())
        console.print(f"[green]✓ Index updated — {count} blocks total.[/green]\n")

    console.print(f"[bold]Done.[/bold] Approved: {approved}  Rejected: {rejected}")


# ---------------------------------------------------------------------------
# Validate command (Hit Rate@K harness)
# ---------------------------------------------------------------------------

@app.command()
def validate(
    validation_file: Path = typer.Option(
        Path("tests/validation_set.json"),
        "--file", "-f",
        help="Path to validation set JSON file.",
    ),
    top_k: int = typer.Option(3, "--top-k", "-k", help="K for Hit Rate@K."),
    threshold: float = typer.Option(0.75, "--threshold", "-t", help="Minimum cosine similarity."),
    context_weight: int = typer.Option(4000, "--weight", help="Weight budget for query."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-query results."),
) -> None:
    """Run Hit Rate@K evaluation against the validation set.

    Reads tests/validation_set.json, runs each prompt through the retrieval
    pipeline, and computes Hit Rate@K.
    Exits with code 1 if Hit Rate@K is below 0.70.
    """
    import json

    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index
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
        blocks = load_all_blocks(_blocks_dir())
        index = load_index(_index_path())
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

        results = _query(prompt, index, blocks, top_k=top_k, threshold=threshold, context_weight=context_weight)
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


# ---------------------------------------------------------------------------
# Threshold tuning
# ---------------------------------------------------------------------------

@app.command("threshold-test")
def threshold_test(
    thresholds: str = typer.Option(
        "0.50,0.55,0.60,0.65,0.70,0.75",
        "--thresholds", "-t",
        help="Comma-separated thresholds to sweep.",
    ),
    validation_file: Path = typer.Option(
        Path("tests/validation_set.json"),
        "--file", "-f",
        help="Validation set for true positives.",
    ),
    negative_file: Path = typer.Option(
        None,
        "--negatives", "-n",
        help="Optional JSON file with prompts that should NOT trigger (list of strings).",
    ),
    top_k: int = typer.Option(3, "--top-k", "-k"),
    strict_intent: bool = typer.Option(True, "--strict/--no-strict"),
    min_words: int = typer.Option(
        0,
        "--min-words", "-w",
        help="Skip prompts shorter than N words (mirrors hook MIN_PROMPT_WORDS). 0 = disabled.",
    ),
    require_impl: bool = typer.Option(
        False,
        "--require-impl/--no-require-impl",
        help="Apply is_implementation_prompt() gate before similarity check (mirrors hook).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-prompt scores."),
) -> None:
    """Sweep thresholds and show precision/recall trade-off.

    For each threshold prints: true positive rate (Hit Rate@K on validation set),
    false positive rate (if --negatives provided), and a sample of what fires.
    Use this to find the sweet spot before changing the hook threshold.
    """
    import json

    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import is_implementation_prompt, load_index
    from turnzero.retrieval import query as _query

    try:
        blocks = load_all_blocks(_blocks_dir())
        index = load_index(_index_path())
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
        err_console.print("[red]--thresholds must be comma-separated floats, e.g. 0.55,0.60,0.65[/red]")
        raise typer.Exit(1)

    # --- verbose per-prompt score dump (single threshold = current hook value) ---
    if verbose:
        console.print("\n[bold]Per-prompt top scores[/bold] (all prompts, no threshold filter)\n")
        all_prompts = [(e["prompt"], True) for e in val_set] + [(p, False) for p in negatives]
        score_table = Table(box=box.SIMPLE)
        score_table.add_column("Type", width=4)
        score_table.add_column("Prompt", max_width=55)
        score_table.add_column("Top block", max_width=35)
        score_table.add_column("Score", justify="right")
        score_table.add_column("Intent hit")

        for prompt_text, is_positive in all_prompts:
            word_blocked = min_words > 0 and len(prompt_text.split()) < min_words
            impl_blocked = require_impl and not is_implementation_prompt(prompt_text)
            # Query at very low threshold to always get a score
            raw = _query(
                prompt_text, index, blocks,
                top_k=1, threshold=0.0, context_weight=99999, strict_intent=False,
            )
            if raw:
                top_block, top_score = raw[0]
                strict_raw = _query(
                    prompt_text, index, blocks,
                    top_k=1, threshold=0.0, context_weight=99999, strict_intent=strict_intent,
                )
                intent_ok = "[green]✓[/green]" if strict_raw else "[yellow]no[/yellow]"
                score_str = f"{top_score:.3f}"
                if word_blocked:
                    blocked_label = "[dim]word-blocked[/dim]"
                elif impl_blocked:
                    blocked_label = "[dim]impl-blocked[/dim]"
                else:
                    blocked_label = None
                type_str = "[green]+[/green]" if is_positive else "[red]-[/red]"
                score_table.add_row(
                    type_str, prompt_text[:55], top_block.slug[:35], score_str,
                    blocked_label if blocked_label else intent_ok,
                )
            else:
                type_str = "[green]+[/green]" if is_positive else "[red]-[/red]"
                score_table.add_row(type_str, prompt_text[:55], "[none]", "0.000", "—")

        console.print(score_table)
        console.print("[dim]+ = should fire  - = should NOT fire  Intent hit = passes strict_intent filter[/dim]\n")

    # --- threshold sweep table ---
    sweep_table = Table(title="Threshold Sweep", box=box.SIMPLE)
    sweep_table.add_column("Threshold", justify="right")
    sweep_table.add_column("TP rate (recall)", justify="right")
    sweep_table.add_column("FP rate", justify="right")
    sweep_table.add_column("Fires on", max_width=50)

    for t in t_values:
        # True positives: validation set entries that hit at least one relevant block
        tp_hits = 0
        for entry in val_set:
            if min_words > 0 and len(entry["prompt"].split()) < min_words:
                continue  # would be blocked by hook — don't count against recall
            if require_impl and not is_implementation_prompt(entry["prompt"]):
                continue  # would be blocked by impl gate
            relevant = set(entry["relevant_block_ids"])
            results = _query(
                entry["prompt"], index, blocks,
                top_k=top_k, threshold=t, context_weight=4000, strict_intent=strict_intent,
            )
            if any(b.id in relevant for b, _ in results):
                tp_hits += 1
        eligible_val = [
            e for e in val_set
            if not (min_words > 0 and len(e["prompt"].split()) < min_words)
            and not (require_impl and not is_implementation_prompt(e["prompt"]))
        ]
        recall = tp_hits / len(eligible_val) if eligible_val else 0.0

        # False positives: negative prompts that fire anything
        fp_hits = 0
        fp_examples: list[str] = []
        for neg in negatives:
            if min_words > 0 and len(neg.split()) < min_words:
                continue  # blocked by word filter — not a FP
            if require_impl and not is_implementation_prompt(neg):
                continue  # blocked by impl gate — not a FP
            results = _query(
                neg, index, blocks,
                top_k=top_k, threshold=t, context_weight=4000, strict_intent=strict_intent,
            )
            if results:
                fp_hits += 1
                fp_examples.append(f'"{neg[:30]}"→{results[0][0].slug}')
        eligible_neg = [
            n for n in negatives
            if not (min_words > 0 and len(n.split()) < min_words)
            and not (require_impl and not is_implementation_prompt(n))
        ]
        fp_rate_str = f"{fp_hits}/{len(eligible_neg)}" if negatives else "n/a"

        # Sample of what fires among non-validated positive prompts
        fires_on: list[str] = []
        for entry in val_set:
            results = _query(
                entry["prompt"], index, blocks,
                top_k=1, threshold=t, context_weight=4000, strict_intent=strict_intent,
            )
            if results:
                fires_on.append(results[0][0].slug)

        recall_color = "green" if recall >= 0.80 else ("yellow" if recall >= 0.60 else "red")
        fires_sample = ", ".join(dict.fromkeys(fires_on))[:48]  # deduplicate, truncate

        sweep_table.add_row(
            f"{t:.2f}",
            f"[{recall_color}]{recall:.0%} ({tp_hits}/{len(val_set)})[/{recall_color}]",
            fp_rate_str,
            fires_sample or "[dim]nothing[/dim]",
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


# ---------------------------------------------------------------------------
# Index subcommands
# ---------------------------------------------------------------------------

@index_app.command("build")
def index_build() -> None:
    """Embed all blocks and write the similarity index."""
    from turnzero.index import build as _build

    console.print(f"Building index from [bold]{_blocks_dir()}[/bold] ...")
    try:
        count = _build(_blocks_dir(), _index_path())
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Indexed {count} block(s) → {_index_path()}")


@index_app.command("verify")
def index_verify(
    max_age_days: int = typer.Option(90, "--days", help="Staleness threshold in days."),
) -> None:
    """Flag blocks not verified within the staleness window."""
    from turnzero.index import verify as _verify

    try:
        stale = _verify(_blocks_dir(), max_age_days)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not stale:
        console.print(f"[green]✓[/green] All blocks verified within {max_age_days} days.")
    else:
        console.print(f"[yellow]{len(stale)} stale block(s):[/yellow]")
        for block_id in stale:
            console.print(f"  • {block_id}")


# ---------------------------------------------------------------------------
# Source subcommands — enable/disable block tiers
# ---------------------------------------------------------------------------

@source_app.command("list")
def source_list() -> None:
    """Show which Expert Prior sources are enabled."""
    from turnzero.config import load_config, TIERS

    cfg = load_config(_data_dir())
    sources = cfg["sources"]
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Source", style="bold")
    table.add_column("Status")
    table.add_column("Path")
    for tier in TIERS:
        enabled = sources.get(tier, False)
        status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        path = str(_blocks_dir() / tier)
        table.add_row(tier, status, f"[dim]{path}[/dim]")
    console.print(table)


@source_app.command("enable")
def source_enable(tier: str = typer.Argument(..., help="Tier to enable: local, community, enterprise")) -> None:
    """Enable an Expert Prior source tier."""
    from turnzero.config import load_config, save_config, TIERS

    if tier not in TIERS:
        console.print(f"[red]Unknown tier '{tier}'. Choose from: {', '.join(TIERS)}[/red]")
        raise typer.Exit(1)
    cfg = load_config(_data_dir())
    cfg["sources"][tier] = True
    save_config(_data_dir(), cfg)
    console.print(f"[green]✓[/green] Source '[bold]{tier}[/bold]' enabled.")


@source_app.command("disable")
def source_disable(tier: str = typer.Argument(..., help="Tier to disable: local, community, enterprise")) -> None:
    """Disable an Expert Prior source tier."""
    from turnzero.config import load_config, save_config, TIERS

    if tier not in TIERS:
        console.print(f"[red]Unknown tier '{tier}'. Choose from: {', '.join(TIERS)}[/red]")
        raise typer.Exit(1)
    if tier == "local":
        console.print("[yellow]⚠[/yellow]  Disabling 'local' means no blocks will be injected unless community or enterprise is enabled.")
    cfg = load_config(_data_dir())
    cfg["sources"][tier] = False
    save_config(_data_dir(), cfg)
    console.print(f"[dim]✓ Source '[bold]{tier}[/bold]' disabled.[/dim]")


if __name__ == "__main__":
    app()
