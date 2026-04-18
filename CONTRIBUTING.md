# Contributing to TurnZero

The most valuable contribution is a new **Expert Prior** — the delta between a naive AI response and an expert one. What would a domain expert silently add before hitting send?

Expert Priors can be for any domain: software, law, medicine, finance, design, writing, research — anywhere the AI makes the same domain-specific mistakes without context.

## The fastest way to contribute: just use TurnZero

When the AI gets something wrong in your session, correct it naturally. TurnZero detects the correction and calls `submit_candidate` automatically — the Expert Prior is added to your library instantly. You can also say "remember this" or "save this" to trigger it explicitly.

If you want to share it with the community, open a PR adding the YAML file from `~/.turnzero/blocks/` to `data/blocks/`.

## Adding an Expert Prior manually

1. Fork the repo and create a branch
2. Copy an existing block from `data/blocks/` as a template
3. Fill in all fields — especially `constraints`, `anti_patterns`, and `doc_anchors`
4. Assign an intent: `build`, `debug`, `migrate`, or `review`
5. Run `turnzero index build` to rebuild the index
6. Run `pytest` — all tests must pass
7. Open a PR with one line: what mistake does this Expert Prior prevent?

## What makes a good Expert Prior

**The test:** *Would a stranger in the same stack, facing the same problem, be better off knowing this before Turn 0?*

| Good | Bad |
|---|---|
| `Do not use getServerSideProps in App Router` — API removed | "Use PyCharm" — personal preference |
| `Swiss non-compete clauses unenforceable beyond 3 years` — jurisdiction rule | "Don't commit secrets" — generic |
| `expire_on_commit=False required with AsyncSession` — raises MissingGreenlet | "Write unit tests" — generic advice |

## Block schema

```yaml
id: "domain-intent-keyword"      # e.g. nextjs15-approuter-build
slug: "nextjs15-approuter-build"
domain: "nextjs"                 # primary technology, lowercase
intent: "build"                  # build | debug | migrate | review
last_verified: "2026-04-19"
tags: [nextjs, react, approuter]
context_weight: 900              # estimated tokens when injected
constraints:
  - "Use Server Components by default; Client Components only when state/browser APIs required"
anti_patterns:
  - "Do not use getServerSideProps/getStaticProps (Pages Router only)"
doc_anchors:
  - url: "https://nextjs.org/docs/app/..."
    verified: "2026-04-19"
```

Block IDs are descriptive slugs. Never mutate an existing block — create a new version with a bumped `version` field.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## Questions

Open an issue. Tag it `question`.
