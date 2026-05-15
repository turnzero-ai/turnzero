# TurnZero — Roadmap

**Mission:** Eliminate cold-start friction in every AI session by injecting expert knowledge before Turn 0.

## Vision: Three Concentric Circles

```
Circle 1 — Personal (live today)
  Your library grows automatically from your own sessions. Personal Priors establish a Portable AI Identity
  that follows you across every project and AI client.
  - [x] Auto-learning via `submit_candidate` MCP tool
  - [x] Always-On Personal Priors (injected unconditionally at session start)
  - [x] Multi-tier storage architecture (`personal`, `local`, `community`)

Circle 2 — Community (Phase 4)
  Corrections route to everyone on the same stack. Every "remember this" enriches all users.

Circle 3 — Enterprise (Phase 5)
  Teams build proprietary knowledge bases scoped to their stack and standards.
```

**Flywheel:** session → correction → `submit_candidate` → review → registry → Turn 0.

**Positioning:** Infrastructure, not a feature. Like npm, not a plugin.

---

## Phase 3: Distribution & Ecosystem
*Goal: Remove every remaining friction point. Any user, any setup.*

- [x] **Ollama setup automation** — `turnzero setup` proactively pulls `nomic-embed-text` and offers to start the server if missing (v0.8.0+).
- [x] **ONNX embedding backend** — In-process local embedding via `onnxruntime` + `tokenizers`, no daemon required (v0.11.2+).
- [x] **Index model versioning** — `model_id` header in index prevents silent score corruption.
- [x] **Multi-client auto-detection** — `turnzero setup` wires Claude Code, Cursor, Claude Desktop, Gemini CLI, and Codex.
- [x] **Setup upgrade safety** — `turnzero setup` merges blocks instead of overwriting community/team tiers (v0.11.2+).
- [x] **Privacy disclosure** — `harvest` requires explicit opt-in before scanning local session files.
- [x] **Block discoverability** — `turnzero list`, `--domain`, `--candidates`, `--stale`; `turnzero domain add/remove/list/reset` (v0.12.0).

---

## Phase 4: The Registry
*Goal: Activate the community flywheel. Personal tool → shared knowledge network.*

- [x] **Domain filter** — Active domain whitelist in config; `turnzero domain` management; personal tier always active (v0.12.0).
- [ ] **Semantic deduplication** — Detect and merge blocks covering the same topic to reduce library noise.
- [ ] **Embedding prefixes** — Add `search_query:` and `search_document:` prefixes for nomic-embed-text-v1.5 to improve retrieval accuracy.
- [ ] **Block versioning / deprecation** — `deprecated_by` field on block schema; old versions decay in ranking.
- [ ] **Hosted block registry** — Versioned YAML + pre-computed embeddings, no local model required for sync.
- [ ] **`turnzero sync`** — Pull community blocks + index from registry.
- [ ] **Community submission flow** — `submit_candidate` → registry PR → merged → synced to all users.
- [ ] **Correction prevention rate** — Instrument sessions to measure whether injected priors actually prevented mid-session corrections.
- [ ] **Per-turn domain shift** — Optional re-call of `list_suggested_blocks` when domain context shifts mid-session.

---

## Phase 5: Enterprise
- [ ] Private registry (team namespaces, SSO, audit logs).
- [ ] Local-only embedding for air-gapped networks.
- [ ] HNSW index for large-scale libraries.
- [ ] Block slug conflict resolution across tiers (local > community > team priority).
- [ ] **GraphRAG** — `requires` / `conflicts_with` edges between blocks for contradictory logic detection.

---

## Maintenance & Done
- [x] v0.14.1 — Fix: bundled index rebuilt with ONNX (v0.14.0 shipped Ollama index by mistake).
- [x] v0.14.0 — Code quality sprint: layered architecture enforced (CLI → services → repos), canonical file structure across 14 modules, DDD cleanup (AutoApprovePolicy, pure domain analytics, stats_svc owns ROI infrastructure), god function decomposition (setup → 7 helpers, list_suggested_blocks → 3 functions), QueryContext dataclass, CachedLoader, EmbeddingBackend protocol, ConfigManager, SessionLifecycle. 396 tests.
- [x] v0.13.2 — Hotfix: telemetry anonymous_id always from `~/.turnzero/` (ignores `TURNZERO_DATA_DIR` override); `TURNZERO_DEBUG=1` event logging; maintainer workflow split from public `CLAUDE.md`; hook template moved to `turnzero/templates/`. 382 tests.
- [x] v0.13.1 — Community block: `python-db-query-return-type-annotations`; `contribute --web` flag restored as optional.
- [x] v0.13.0 — Community flywheel: `turnzero contribute`; benchmark fix (`inject_all=True` detection); Gemini chitchat suppression via FastMCP instructions; full refactor/quality sprint (types.py, signals.py, errors.py). 380 tests.
- [x] v0.12.0 — Retention sprint: `turnzero list` (GRW-1), `turnzero domain` management (RET-8), correction nudge (ONB-3), stats trajectory (RET-6), setup interactive finale (RET-7), day-2 nudge (RET-9), async telemetry fix.
- [x] v0.11.5 — Verify: prioritized ONNX backend in diagnostics.
- [x] v0.11.4 — Docs: synchronized versions; README: restored Ollama documentation.
- [x] v0.11.2 — Setup: merge blocks instead of overwrite (WF-4); Harvest: privacy disclosure and opt-in (SEC-4).
- [x] v0.11.0 — Security: CandidateSafetyValidator quarantines malicious priors (SEC-3); `query --explain` diagnostics (RET-4); upgrade nudge in stats (RET-5).
- [x] v0.10.1 — Token transparency: PRIOR_METADATA in inject output, prior content + MCP overhead rows in stats (RET-3).
- [x] v0.10.0 — Structural session dedup (WF-1/2/3); setup live injection demo (RET-1); overmatching keyword-overlap gate (RET-2).
- [x] v0.9.0 — DDD architecture refactor; mtime block cache; feedback system.
- [x] v0.8.14 — Agentic benchmark harness; chitchat skip rule improved; AGENTS.md added for Codex.
- [x] v0.8.12 — Fast setup via bundled index; no Ollama required on first install.
- [x] v0.8.8 — Security hardening: auto-approve guard (SEC-1), path traversal protection (SEC-2).
- [x] v0.8.6 — Anonymous telemetry (PostHog EU, opt-out), incremental indexing, atomic index writes.
- [x] v0.6.0 — Session deduplication and persistent project affinity.
- [x] v0.2.0 — MCP-first architecture, `submit_candidate` learning loop.
- [x] v0.1.0 — Core engine, hybrid retrieval, three-layer injection gate.

---

**Long-term:** Every MCP-compatible AI client ships with TurnZero support as default infrastructure. Users don't configure it. The library grows from their sessions. Cold start is solved.
