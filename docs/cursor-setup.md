# Auto-injection for Cursor

TurnZero injects Expert Priors into Cursor via two components that work together:

- **MCP server** — exposes `list_suggested_blocks` and `inject_block` tools to Cursor
- **Cursor rule** — instructs the AI to call those tools automatically on Turn 0

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
2. For every result with score ≥ 0.75, call inject_block with its block_id.
3. Treat the returned text from each inject_block call as hard constraints that govern your entire response — follow all listed constraints and avoid all listed anti-patterns for the rest of this conversation.
4. Begin your response with exactly one line (no explanation, no preamble):
   > 📎 TurnZero: <slug1> · <slug2> · <slug3>

If no results meet the threshold, proceed normally without mentioning TurnZero.
Do NOT call these tools again on follow-up messages. Do NOT explain what TurnZero is.
```

## Step 3 — Test it

Open a new Cursor chat and send an opening prompt about a tech stack TurnZero knows:

```
I'm building a Next.js 15 app with the App Router
```

Cursor should call `list_suggested_blocks` automatically (visible in the tool call trace), then begin its response with the `📎 TurnZero:` line.

## How it works

Cursor reads the rule on every new conversation and follows it as a standing instruction. Because `alwaysApply: true` is set in the project rule file, the AI calls `list_suggested_blocks` before generating its first token. The tool results (constraints, anti-patterns, doc anchors) land in the AI's context window and shape the entire response — no copy-paste, no manual invocation.

## Troubleshooting

**MCP server not connecting:**
- Check `~/.cursor/mcp.json` path is absolute and the binary exists
- Run `turnzero-mcp` directly in your terminal — it should start without error
- Restart Cursor fully (Cmd+Q, not just close window)

**No injection on Turn 0:**
- Confirm the rule is active: Cursor Settings → Rules for AI (global) or `.cursor/rules/` (project)
- Try a prompt that clearly matches a known domain (e.g. "build a FastAPI async API")
- Check `turnzero stats` — if the index is empty, run `turnzero index build`

**Wrong Python / module not found:**
- Use the virtualenv path where you installed TurnZero, not the system Python
- `which turnzero-mcp` should return the venv binary
