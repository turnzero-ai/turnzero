# TurnZero — Roadmap

**Mission:** Eliminate cold-start friction in every AI session by injecting expert knowledge before Turn 0.

## Vision: Three Concentric Circles

```
Circle 1 — Personal (live today)
  Your library grows automatically from your own sessions. Any domain. Zero curation.

Circle 2 — Community (Phase 4)
  Corrections route to everyone on the same stack. Every "remember this" enriches all users.

Circle 3 — Enterprise (Phase 5)
  Teams build proprietary knowledge bases. Can't be in public registry — competitive moat.
```

**Flywheel:** session → correction → `submit_candidate` → registry → injected at Turn 0 for everyone.

**Positioning:** Infrastructure, not a feature. Like npm, not a plugin. AI companies won't build this — provider-neutral context is anti-competitive for them. The moat is community standard, not the retrieval algorithm.

---

## Phase 3: Distribution & Ecosystem (v0.3.0)
*Goal: Remove every remaining friction point. Any user, any setup.*

- [ ] **Ollama setup automation** — Update `turnzero setup` to proactively pull `nomic-embed-text` and offer to start the server if missing.
- [ ] **ONNX embedding research** — Explore/test ONNX-based local embeddings (~150MB, zero-dep) to replace the 2GB Ollama requirement while maintaining 100% privacy.
- [x] **Index model versioning** — Add `model_id` header to index to prevent silent score corruption.
- [ ] **Multi-client auto-detection** — `turnzero setup` wires Claude Code, Cursor, and Claude Desktop.
- [ ] **Setup upgrade safety** — Ensure `turnzero setup` doesn't overwrite community/team tiers on upgrade.
- [ ] **Privacy disclosure** — Document that `harvest` stores local transcript data; user opt-in.

---

## Phase 4: The Registry (Months 3–6)
*Goal: Activate the community flywheel. Personal tool → shared knowledge network.*

- [ ] **Domain router** — Layer 1 env-based filter eliminates 90%+ of candidates before vector math.
- [ ] **Semantic deduplication** — Detect and merge blocks with cosine similarity > 0.92 covering the same topic.
- [ ] **Block versioning / deprecation** — `deprecated_by` field on block schema; old versions score-decay.
- [x] **Outcome feedback loop** — Clean session boosts block confidence; correction decays it (v0.5.0 baseline).
- [ ] **Hosted block registry** — Static nginx on Hetzner, versioned YAML + pre-computed embeddings.
- [ ] **`turnzero sync`** — Pull community blocks + index, no local model required.
- [ ] **Community submission flow** — `submit_candidate` → registry PR → merged → synced.

---

## Phase 5: Enterprise (Months 6–12)
- [ ] Private registry (team namespaces, SSO, audit logs).
- [ ] Local-only embedding for air-gapped networks.
- [ ] HNSW index for 10,000+ blocks.
- [ ] Block slug conflict resolution across tiers (local > community > team priority).
- [ ] **GraphRAG** — `requires` / `conflicts_with` edges between blocks for contradictory logic detection.

---

## Maintenance & Done
- [x] v0.5.1 — Confidence scoring (TD-005), centralized logic, verification tiers, archived blocks.
- [x] v0.2.7 — Runtime contract hardening, mandatory local Ollama for stability.
- [x] v0.2.6 — Confidence scoring live, library poisoning mitigation.
- [x] v0.2.5 — Domain-agnostic gate, integration tests, Codex support.
- [x] v0.2.0 — MCP-first architecture, `submit_candidate` learning loop.
- [x] v0.1.0 — Core engine, hybrid retrieval, three-layer injection gate.

---

**Long-term:** Every MCP-compatible AI client ships with TurnZero support as default infrastructure. Users don't configure it. The library grows from their sessions. Cold start is solved.
