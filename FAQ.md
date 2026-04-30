# TurnZero — FAQ

---

**Won't GPT-5 / Claude 4 / the next model make this obsolete?**

Larger models get better at general reasoning, but they still start every session knowing nothing about *your* stack's specific gotchas, your domain's jurisdiction-specific rules, or the correction you made three sessions ago. The gap shifts — it doesn't close. And as models get better at following injected context, TurnZero's injections get *more* effective, not less.

---

**Why not just use AI-native memory — Claude Projects, ChatGPT Memory, Cursor Rules?**

AI memory remembers *you*. TurnZero remembers your *domain*. Native memory is personal and siloed to one client. TurnZero's library is portable across every MCP-compatible client, shareable across a team, and structured around the specific constraints that cause AI mistakes — not general preferences. The two are complementary: native memory for who you are, TurnZero for what your domain requires.

---

**Is my data private? Does TurnZero send my prompts anywhere?**

Raw prompt text is never stored by TurnZero. When you run `list_suggested_blocks`, your prompt is embedded either locally via ollama or remotely via OpenAI's embeddings API if you choose that backend. In both cases, TurnZero discards the raw text immediately after embedding and compares only the embedding against a local index. The `harvest` command, which reads past session transcripts, is an explicit opt-in step — nothing is read automatically, and transcripts never leave your machine. The default MCP injection path never touches session content at all.

---

**What's the difference between TurnZero and `.cursorrules` / custom instructions?**

`.cursorrules` and custom instructions are static — you write them once and they inject regardless of context. TurnZero is dynamic: it applies your Personal Priors once at session start, then retrieves Expert Priors only when they are relevant to the current task. A FastAPI question pulls async patterns. A Next.js 15 question pulls App Router constraints. A medical question pulls the right clinical thresholds. Static rules bloat every session; TurnZero targets the injection.

---

**Do I need ollama? What if I don't want to install anything extra?**

No. TurnZero has two embedding backends and falls back automatically: ollama (local, free, private) → OpenAI API (set `OPENAI_API_KEY`). If you already have an OpenAI key, there is nothing extra to install. If you want full local/private operation, `ollama pull nomic-embed-text` is a one-time step.

---

**Does it work with ChatGPT or Gemini?**

Not yet. TurnZero uses the MCP (Model Context Protocol) standard, which Claude Code, Cursor, and Claude Desktop support. ChatGPT and Gemini don't expose an MCP interface. For clients without MCP, use `turnzero query "<prompt>"` or `turnzero preview "<prompt>"` to find the relevant blocks, then `turnzero show <slug>` or `turnzero inject <slug>` to print the formatted prior text and paste it manually. Not seamless, but it works. MCP adoption is growing; more clients are expected to add support.

---

**How is this different from RAG?**

RAG retrieves documents to answer a question *mid-response*. TurnZero retrieves *constraints* to shape the response *before it starts*. The goal isn't to find an answer — it's to prevent the model from making the wrong assumptions in the first place. The blocks aren't documents; they're compact, high-signal priors: what to use, what to avoid, and which API behaviors will silently break things. One corrects after the fact; the other prevents the mistake entirely.

---

**How does the library grow? Who writes the Expert Priors?**

The highest-signal source is mid-session corrections: when the AI gets something wrong and you correct it, that correction is exactly what TurnZero should inject next time. During a session, the AI can call `submit_candidate` to write a new prior directly, which enters your local library with a confidence score based on detail; you can verify or prune these via `turnzero review`. The 143 blocks shipped in the library came from real sessions where the model made domain-specific mistakes. You can also write blocks manually in YAML — the schema is in the README.

---

**What if there are no relevant priors for my domain?**

TurnZero still works — it just injects nothing, which is the right answer when there's no signal. There's a three-layer gate: minimum prompt length, implementation-intent detection, and a 0.70 cosine similarity threshold. Marginal matches are filtered out. The library grows from your sessions, so the first time you use a new domain you start from zero; by the tenth session, you've built a useful prior set. To inspect what TurnZero would do, run `turnzero preview "<prompt>"`.

---

**Why is there a token budget for Personal and Expert Priors?**

TurnZero implements a strict budget split (2,500 tokens for Identity, 5,000 tokens total) to maintain **Hierarchical Contextual Anchoring**. Research into LLM "Attention Sinks" (Xiao et al., 2024) and "Lost in the Middle" (Liu et al., 2023) phenomena shows that AI accuracy degrades as the ratio of "Instruction context" to "Task context" shifts. If instructions are too large, they crowd out the model's effective "thinking space" for the immediate task. By keeping priors sparse and high-signal, we improve predictability and reduce errors.

---

**What is 'Project Scoping' and why is it used?**

Project Scoping allows TurnZero to distinguish between your **Universal Identity** (global preferences like "be concise" or git workflows) and your **Pinned Style** (project-specific rules like indentation or framework-specific patterns). This prevents **Contextual Drift**, where a preference from one project accidentally poisons the context of another. By increasing the Signal-to-Noise Ratio (SNR), the AI becomes more accurate because it doesn't have to reconcile contradictory rules from unrelated workspaces.

---

**Is there scientific backing for the context size TurnZero uses?**

Yes. The 5,000-token limit is designed to optimize for the model's **latent instruction following** capabilities without triggering performance decay. We follow a **Mandate-Constraint-Rationale** hierarchy: we don't just tell the model *what* to do; we provide a logical rationale (*why*), which has been shown to significantly improve LLM adherence and reduce hallucination of constraints for tools not in use.
