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
*Shipped as v0.2.0.*

- [x] MCP server as primary injection path — works with any MCP-compatible client
- [x] `submit_candidate` — AI writes Expert Priors directly mid-session
- [x] `auto_approve` — "remember this" adds block to library instantly
- [x] `get_stats` — usage and library stats from within the AI session
- [x] Domain expansion — any field, not just software
- [x] Cursor integration — MCP + global rule
- [x] Clear embedding backend detection and user guidance
- [ ] PyPI publish — `pip install turnzero` without cloning

---

## Phase 3: Distribution & Ecosystem (Months 1–3)

*Goal: Zero-friction onboarding and works out of the box for any user.*

Focus on eliminating the technical hurdles of local setup and expanding TurnZero's reach across the AI tooling ecosystem.

- **Frictionless Onboarding** — Pre-computed query states and cloud fallbacks for "zero-config" injection.
- **Global Discovery** — Automated client detection and cross-platform installation.
- **High-Fidelity Retrieval** — Enhanced caching and pre-built domain indexes for the most common stacks.

---

## What's next

Community and team features are in active development. We're building the infrastructure to sync and share Expert Priors securely across organizations.
