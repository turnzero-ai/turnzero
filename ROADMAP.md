# TurnZero — Unified Roadmap & Project State

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

## 1. Active Phase: Distribution & Ecosystem (v0.3.0)
*Goal: Remove every remaining friction point. Any user, any setup.*

- [ ] **Cloud embedding fallback** — Hosted endpoint so new users don't need ollama/API keys.
- [ ] **Index model versioning** — Add `model_id` header to index to prevent silent score corruption.
- [ ] **Pre-built index download** — Ship fresh community index so `index build` isn't required.
- [ ] **Multi-client auto-detection** — `turnzero setup` wires Claude Code, Cursor, and Claude Desktop.
- [ ] **Setup upgrade safety** — Ensure `turnzero setup` doesn't overwrite community/team tiers on upgrade.
- [ ] **Privacy disclosure** — Document that `harvest` stores local transcript data; user opt-in.

---

## 2. Technical Debt Registry (High-Priority Fragilities)
These are the core risks identified in the Architectural Review that must be addressed to ensure system integrity.

| ID | Fragility | Impact | Status |
|---|---|---|---|
| TD-001 | **Index Time-Bomb** | Silent data corruption on model change. | [ ] Open |
| TD-002 | **Onboarding Dead End** | High friction; tool does nothing without Ollama. | [ ] Open |
| TD-003 | **Gate Fragility** | Brittle heuristics cause false negatives. | [ ] Open |
| TD-004 | **CLI Monolith** | ~1,700 lines in `cli.py`; high regression risk. | [ ] Open |
| TD-005 | **Library Poisoning** | `auto_approve=True` + AI hallucination = false priors compound silently. No decay, no expiry, no detection. | [ ] Open |

---

## 3. Active Tickets & Backlog

### Priority 1: Pre-Launch Survival (users drop within first session if not fixed)

**P1-A — Zero-dep install (TD-002)**
- [x] Move `sentence-transformers` to default dependencies — fully local, zero-config, no server, no API key. Cloud embedding removed entirely (would violate "no raw prompts off-device" principle).
- [ ] Ship pre-built community index so `index build` isn't required.
- [ ] Update `turnzero setup` to check for multiple AI clients and register them.

**P1-B — Library poisoning minimum viable mitigation (TD-005)**
- [ ] Add `confidence: float` field to block schema (0.0–1.0).
- [ ] `submit_candidate` sets confidence based on correction signal strength + block specificity.
- [ ] Blocks with `confidence < 0.5` down-weighted in retrieval scoring.
- [ ] `turnzero review` surfaces blocks with `confidence < 0.7` for manual pruning (command exists, needs confidence filter).
- [ ] Block auto-archive: blocks unseen for 90 days with no positive reinforcement get `archived: true` and excluded from retrieval.

**P1-C — Gate validation on real-world prompts (TD-003)**
- [ ] Expand adversarial test set beyond current 74-block validation — test against common HN developer prompt patterns.
- [ ] Fix 6-character word heuristic: replace with refined patterns before public launch.

### Priority 2: Index Integrity
- [ ] Implement `IndexHeader` in `turnzero/index.py` to store `model_id` (TD-001).

### Priority 3: Learning Loop Reliability
- [ ] Automated harvest cron — `submit_candidate` is ~20% reliable in live sessions; nightly deterministic harvest closes the gap.

### Priority 4: Refactoring (TD-004)
- [ ] Move index-related CLI commands to `turnzero/cli/index.py`.
- [ ] Move setup-related CLI commands to `turnzero/cli/setup.py`.

### Show HN Launch Gate
**Do not launch until all of the following are true:**
- [x] Zero-dep install — `sentence-transformers` bundled, no ollama/API key required
- [x] Confidence scoring live — TD-005 mitigated; `turnzero review` surfaces low-confidence blocks
- [ ] Pre-built index ships in wheel — no `index build` required
- [ ] `pipx install turnzero && turnzero setup` tested cold on a machine with no ollama/API key
- [ ] Gate validated on real-world developer prompts — not just internal test set

---

## 4. Future Phases

### Phase 4: The Registry (Months 3–6)
*Goal: Activate the community flywheel. Personal tool → shared knowledge network.*

**Must ship before community submissions open (precision collapses without these):**
- [ ] **Domain router** — Layer 1 env-based filter (`package.json`, file extensions, domain signals) eliminates 90%+ of candidates before vector math. Critical at 300+ blocks; mandatory before community library ships.
- [ ] **Semantic deduplication** — Detect and merge blocks with cosine similarity > 0.92 covering the same topic. Prevents top-3 results being filled with near-duplicate community submissions.
- [ ] **Block versioning / deprecation** — `deprecated_by` field on block schema; old versions score-decay and are excluded from retrieval unless explicitly referenced. Prevents slug proliferation.
- [ ] **Outcome feedback loop** — Clean session boosts block confidence; correction decays it. Prerequisite for self-improving library quality at scale.
- [ ] **Validation set scaling strategy** — Extend Hit Rate@3 evaluation to 500+ blocks before registry opens; current 74-block test set doesn't cover community-scale retrieval quality.

**Registry infrastructure:**
- [ ] **Hosted block registry** — Static nginx on Hetzner, versioned YAML + pre-computed embeddings.
- [ ] **`turnzero sync`** — Pull community blocks + index, no local model required.
- [ ] **Community submission flow** — `submit_candidate` → registry PR → merged → synced.
- [ ] **Staleness tooling** — Re-verify workflow for `doc_anchors`, decay scores for unverified blocks.
- [ ] **Proof of Correction** — Every block references the session where the AI got it wrong.

### Phase 5: Enterprise (Months 6–12)
- [ ] Private registry (team namespaces, SSO, audit logs).
- [ ] Local-only embedding for air-gapped networks.
- [ ] HNSW index for 10,000+ blocks (brute-force cosine safe to ~10k; HNSW needed beyond that).
- [ ] Block slug conflict resolution across tiers (local > community > team priority).
- [ ] **GraphRAG** — `requires` / `conflicts_with` edges between blocks; selecting one block auto-boosts related, penalizes contradictory. Prevents co-injection of conflicting priors at scale.

---

## 5. Maintenance & Done
- [x] v0.2.5 — Domain-agnostic gate, integration tests, Codex support.
- [x] v0.2.2 — PyPI live, 1-click install verified, `OLLAMA_HOST` support.
- [x] v0.2.0 — MCP-first architecture, `submit_candidate` learning loop.
- [x] v0.1.0 — Core engine, hybrid retrieval, three-layer injection gate.

---

**Long-term:** Every MCP-compatible AI client ships with TurnZero support as default infrastructure. Users don't configure it. The library grows from their sessions. Cold start is solved.
