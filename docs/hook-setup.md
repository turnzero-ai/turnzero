# Claude Code hook (optional)

> **Most users don't need this.** `turnzero setup` registers the MCP server — the AI calls `list_suggested_blocks` automatically on Turn 0. The hook is an extra guarantee for Claude Code users who want injection to fire regardless of model behaviour.
>
> Install with: `turnzero setup --with-hook`

The hook fires before Claude responds to your first message in each session. It embeds your opening prompt, finds matching Expert Priors, and injects them silently — guaranteed, regardless of model behaviour.

Claude begins its response with:
```
> 📎 TurnZero applied: nextjs15-approuter-build · supabase-auth-pkce-build
```

## Prerequisites

- TurnZero installed and index built (`turnzero index build`)
- Claude Code CLI installed

## Step 1 — Create the hook script

Create `~/.claude/turnzero-hook.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations
import json, os, signal, sys
from pathlib import Path

DATA_DIR = Path("/path/to/turnzero/data")   # <-- update this
MIN_PROMPT_LEN = 15
TIMEOUT_SECS = 5

def _bail(_signum=None, _frame=None): sys.exit(0)
signal.signal(signal.SIGALRM, _bail)
signal.alarm(TIMEOUT_SECS)

try:
    data = json.loads(sys.stdin.read())
    transcript = data.get("transcript", [])
    if any(m.get("role") == "assistant" for m in transcript):
        sys.exit(0)  # not Turn 0, skip
    prompt = data.get("prompt", "").strip()
    if len(prompt) < MIN_PROMPT_LEN:
        sys.exit(0)

    os.environ["TURNZERO_DATA_DIR"] = str(DATA_DIR)
    from turnzero.blocks import load_all_blocks
    from turnzero.retrieval import load_index, query as _query

    blocks = load_all_blocks(DATA_DIR / "blocks")
    index = load_index(DATA_DIR / "index.jsonl")
    results = _query(prompt, index, blocks, top_k=3, threshold=0.75, context_weight=4000, strict_intent=True)
    if not results:
        sys.exit(0)

    names = " · ".join(b.slug for b, _ in results)
    print(f"[TurnZero] Auto-injecting {len(results)} Expert Prior(s): {names}\n")
    for block, _score in results:
        print(block.to_injection_text())
        print()
    print(
        "INSTRUCTION: You have been given Expert Priors above by TurnZero. "
        "Start your response with exactly one line acknowledging them, formatted as:\n"
        f"  > 📎 TurnZero applied: {names}\n"
        "Then continue with your normal response. Do not explain what TurnZero is."
    )
except Exception:
    sys.exit(0)
```

Update `DATA_DIR` to your actual TurnZero data directory (e.g. `/Users/you/turnzero/data`).

## Step 2 — Register the hook

Add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/turnzero/.venv/bin/python /Users/you/.claude/turnzero-hook.py",
            "timeout": 6
          }
        ]
      }
    ]
  }
}
```

Replace `/path/to/turnzero/.venv/bin/python` with your actual venv Python path.

## Step 3 — Test it

Open a new Claude Code session and send an opening prompt about a tech stack TurnZero knows:

```
I'm building a FastAPI async API with PostgreSQL
```

Claude should begin its response with the `📎 TurnZero applied:` attribution line.

## How it works

- The hook receives the full session transcript as JSON on stdin
- It checks whether any assistant message exists — if yes, it's not Turn 0 and exits silently
- It embeds the prompt locally (via ollama) and queries the index
- If matches are found above the threshold, it prints the Expert Prior text to stdout
- Claude Code injects that stdout as context before sending to the AI
- A hard 5-second timeout ensures the hook never blocks the user

## Troubleshooting

**No injection, no attribution line:**
- Confirm ollama is running: `ollama list`
- Confirm the index exists: `turnzero stats`
- Test the hook directly: `echo '{"prompt":"build a Next.js app","transcript":[]}' | /path/to/.venv/bin/python ~/.claude/turnzero-hook.py`

**Wrong Python / stale module:**
- Use `pip install -e .` (editable install) so the hook always picks up the latest source
