# TurnZero — Roadmap

**Mission:** Eliminate cold-start friction in every AI session — for any domain, any user, any client — by injecting the right expert knowledge before Turn 0.

---

## Phase 1: Core Engine ✓
*Shipped as v0.1.0.*

- [x] Curated Expert Priors across software domains
- [x] Hybrid retrieval (vector + intent/domain boosts) — Hit Rate@3 = 1.0
- [x] CLI, MCP server, Claude Code hook
- [x] Three-layer injection gate: min words + impl signal + 0.75 threshold
- [x] `turnzero setup` — one-command install

---

## Phase 2: MCP-First + AI-Driven Learning ✓
*Shipped as v0.2.0 → v0.2.3.*

- [x] MCP server as primary injection path — works with any MCP-compatible client
- [x] `submit_candidate` — AI writes Expert Priors directly mid-session
- [x] `auto_approve` — "remember this" adds block to library instantly
- [x] `get_stats` — usage and library stats from within the AI session
- [x] Domain expansion — any field, not just software
- [x] Cursor integration — MCP + global rule
- [x] PyPI publish — `pipx install turnzero` works, v0.2.2 live
- [x] 1-click install verified end-to-end — no hidden deps, no config required
- [x] `OLLAMA_HOST` env var — configurable endpoint, no hardcoded localhost
- [x] `--version` flag, honest ROI estimates, setup block count fixed

---

## Phase 3: Distribution & Ecosystem (Months 1–3)

*Goal: Remove every remaining friction point. Any user, any setup.*

- [ ] **Cloud embedding fallback** — lightweight hosted endpoint so new users don't need ollama or an API key to get started
- [ ] **Pre-built index download** — ship fresh community index so `index build` isn't required on install
- [ ] **Multi-client auto-detection** — `turnzero setup` detects Claude Code, Cursor, Claude Desktop and wires them all
- [ ] **Index model versioning** — add `model_id` header to index files so an embedding model upgrade doesn't silently corrupt scores
- [ ] **Setup upgrade safety** — `turnzero setup` must not overwrite community/team tiers on upgrade, only init on first install
- [ ] **Privacy disclosure** — README documents that `harvest` stores local transcript data; users opt in knowingly

---

## Phase 4: The Registry (Months 3–6)

*Goal: Activate the community flywheel. Personal tool → shared knowledge network.*

- [ ] **Hosted block registry** — static nginx on Hetzner, versioned YAML + pre-computed embeddings
- [ ] **`turnzero sync`** — pull community blocks + index, no local model required
- [ ] **Community submission flow** — `submit_candidate` → registry PR → merged → synced to all users
- [ ] **Staleness tooling** — re-verify workflow for `doc_anchors`, decay scores for unverified blocks
- [ ] **Proof of Correction** — every block references the session where the AI got it wrong
- [ ] **Outcome feedback loop** — clean session (no corrections) boosts block confidence; corrections decay it

---

## Phase 5: Enterprise (Months 6–12)

*Goal: The genuinely defensible moat — proprietary team knowledge that can never be in a public model.*

- [ ] Private registry (team namespaces, SSO, audit logs)
- [ ] Local-only embedding — no data leaves the network
- [ ] HNSW index for 10,000+ blocks
- [ ] Block slug conflict resolution across tiers (local > community > team priority)

---

## Long-term: Standard Context Layer

Every MCP-compatible AI client ships with TurnZero support as default infrastructure. Users don't configure it. The library grows from their sessions. Cold start is solved.
