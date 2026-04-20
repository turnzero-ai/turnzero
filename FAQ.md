# TurnZero — FAQ

---

**Won't GPT-5 / Claude 4 / the next model make this obsolete?**

Larger models get better at general reasoning, but they still start every session knowing nothing about *your* stack's specific gotchas, your domain's jurisdiction-specific rules, or the correction you made three sessions ago. The gap shifts — it doesn't close. And as models get better at following injected context, TurnZero's injections get *more* effective, not less.

---

**Why not just use AI-native memory — Claude Projects, ChatGPT Memory, Cursor Rules?**

AI memory remembers *you*. TurnZero remembers your *domain*. Native memory is personal and siloed to one client. TurnZero's library is portable across every MCP-compatible client, shareable across a team, and structured around the specific constraints that cause AI mistakes — not general preferences. The two are complementary: native memory for who you are, TurnZero for what your domain requires.

---

**Is my data private? Does TurnZero send my prompts anywhere?**

Raw prompt text is never stored. When you run `list_suggested_blocks`, your prompt is embedded locally (via ollama, sentence-transformers, or OpenAI — your choice), the embedding is compared against a local index, and the raw text is discarded immediately. The `harvest` command, which reads past session transcripts, is an explicit opt-in step — nothing is read automatically, and transcripts never leave your machine. The default MCP injection path never touches session content at all.

---

**What's the difference between TurnZero and `.cursorrules` / custom instructions?**

`.cursorrules` and custom instructions are static — you write them once and they inject regardless of context. TurnZero is dynamic: it embeds your opening prompt and retrieves only the blocks most relevant to *this* session. A FastAPI question pulls async patterns. A Next.js 15 question pulls App Router constraints. A medical question pulls the right clinical thresholds. Static rules bloat every session; TurnZero targets the injection.

---

**Do I need ollama? What if I don't want to install anything extra?**

No. TurnZero has three embedding backends and falls back automatically: ollama (local, free, private) → sentence-transformers (`pip install 'turnzero[local]'`) → OpenAI API (set `OPENAI_API_KEY`). If you already have an OpenAI key, there is nothing extra to install. If you want full local/private operation, `ollama pull nomic-embed-text` is a one-time step.

---

**Does it work with ChatGPT or Gemini?**

Not yet. TurnZero uses the MCP (Model Context Protocol) standard, which Claude Code, Cursor, and Claude Desktop support. ChatGPT and Gemini don't expose an MCP interface. For clients without MCP, you can use `turnzero inject "<prompt>"` to get the formatted injection text and paste it manually — not seamless, but it works. MCP adoption is growing; more clients are expected to add support.

---

**How is this different from RAG?**

RAG retrieves documents to answer a question *mid-response*. TurnZero retrieves *constraints* to shape the response *before it starts*. The goal isn't to find an answer — it's to prevent the model from making the wrong assumptions in the first place. The blocks aren't documents; they're compact, high-signal priors: what to use, what to avoid, and which API behaviors will silently break things. One corrects after the fact; the other prevents the mistake entirely.

---

**How does the library grow? Who writes the Expert Priors?**

The highest-signal source is mid-session corrections: when the AI gets something wrong and you correct it, that correction is exactly what TurnZero should inject next time. During a session, the AI can call `submit_candidate` to write a new prior directly, which gets added to your local library immediately with `auto_approve=True`. The 121 blocks shipped in the library came from real sessions where the model made domain-specific mistakes. You can also write blocks manually in YAML — the schema is in the README.

---

**What if there are no relevant priors for my domain?**

TurnZero still works — it just injects nothing, which is the right answer when there's no signal. There's a three-layer gate: minimum prompt length, implementation-intent detection, and a 0.75 cosine similarity threshold. Marginal matches are filtered out. The library grows from your sessions, so the first time you use a new domain you start from zero; by the tenth session, you've built a useful prior set.
