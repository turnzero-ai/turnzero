# Auto-injection for Cursor

TurnZero injects Expert Priors into Cursor via two components that work together:

- **MCP server** — exposes `list_suggested_blocks` and `inject_block` tools to Cursor
- **Cursor rule** — instructs the AI to call those tools automatically at session start and on later non-trivial prompts when newly relevant Expert Priors may help

Cursor begins its response with:
```
> 📎 TurnZero: nextjs15-approuter-build · supabase-auth-pkce-build
```

## Prerequisites

- TurnZero installed: `pip install turnzero`
- Index built: `turnzero index build`
- Cursor 0.40+ (MCP support required)

## Step 1 — Register the MCP server

Create or edit `~/.cursor/mcp.json` (global — works across all your projects):

```json
{
  "mcpServers": {
    "turnzero": {
      "command": "/path/to/.venv/bin/turnzero-mcp"
    }
  }
}
```

Replace `/path/to/.venv/bin/turnzero-mcp` with the actual path to your TurnZero virtualenv. Find it with:

```bash
pip show turnzero | grep Location
# then: <Location>/../bin/turnzero-mcp
```

Restart Cursor after saving. Confirm the server is connected: **Cursor Settings → MCP** should show `turnzero` with a green dot.

## Step 2 — Add the Cursor rule

**For this project only** (if `.cursor/rules/turnzero.mdc` is already in the repo, skip this step — it's included automatically).

**For all your projects** — add TurnZero as a global Cursor rule:

1. Open **Cursor Settings → Rules for AI**
2. Add the following:

```
On the very first user message of every conversation, you MUST:

1. Call list_suggested_blocks (TurnZero MCP server) with the user's opening message as prompt.
2. Inject the returned Personal Priors once for this session.
3. For every relevant Expert Prior returned, call inject_block with its block_id.
4. Treat the returned text from each inject_block call as hard constraints that govern your response — follow all listed constraints and avoid all listed anti-patterns.
5. Begin your response with exactly one line (no explanation, no preamble):
   > 📎 TurnZero: <slug1> · <slug2> · <slug3>

On later non-trivial user messages, call list_suggested_blocks again only to check for newly relevant Expert Priors. Do not re-inject Personal Priors or priors already used in this session.
If no results meet the threshold, proceed normally without mentioning TurnZero.
Do NOT explain what TurnZero is.
```

## Step 3 — Test it

Open a new Cursor chat and send an opening prompt about a tech stack TurnZero knows:

```
I'm building a Next.js 15 app with the App Router
```

Cursor should call `list_suggested_blocks` automatically (visible in the tool call trace), then begin its response with the `📎 TurnZero:` line.

To test follow-up behavior, continue the same chat with a materially different non-trivial prompt. Cursor should only inject newly relevant Expert Priors and should not repeat Personal Priors or blocks already used in the session.

## How it works

Cursor reads the rule on every new conversation and follows it as a standing instruction. On session start, TurnZero applies Personal Priors once and injects any Expert Priors that match the opening task. On later non-trivial prompts, Cursor checks again only for newly relevant Expert Priors. The tool results (constraints, anti-patterns, doc anchors) land in the AI's context window and shape the response — no copy-paste, no manual invocation.

## Troubleshooting

**MCP server not connecting:**
- Check `~/.cursor/mcp.json` path is absolute and the binary exists
- Run `turnzero-mcp` directly in your terminal — it should start without error
- Restart Cursor fully (Cmd+Q, not just close window)

**No injection on session start:**
- Confirm the rule is active: Cursor Settings → Rules for AI (global) or `.cursor/rules/` (project)
- Try a prompt that clearly matches a known domain (e.g. "build a FastAPI async API")
- Check `turnzero stats` — if the index is empty, run `turnzero index build`
- Verify the threshold matches (0.70)

**Wrong Python / module not found:**
- Use the virtualenv path where you installed TurnZero, not the system Python
- `which turnzero-mcp` should return the venv binary
