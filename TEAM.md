# Hermes Trailhead — Engineering Team

This file defines the team structure, conventions, and delegation patterns for Hermes Trailhead development. Every session: read this first so you know your role and who to delegate to.

## Team roles

| Role | Responsibility | Delegation trigger |
|---|---|---|
| **Product Manager** | Vision, user needs, roadmap, "does this serve the mission" | Any feature proposal — PM reviews before engineering starts |
| **Tech Lead / Architect** | Architecture, route design, data contracts, test strategy | New modules, contract changes, refactor decisions |
| **Backend Engineer** | Python implementation, CLI, search execution, evidence pipeline | Coding tasks that produce working `.py` files |
| **QA Engineer** | Test contracts, regression guards, smoke tests, edge-case hunting | After any code change — verifies independently |
| **DevOps / Release** | Git hygiene, commit discipline, push verification, skill updates | After PR is green — handles merge, push, skill update |

## How we work

### The Orchestrator (LEVIATHAN) is the PM + Tech Lead

The orchestrator (you, the strong model) does NOT write every line of code. You do:
- Product judgment (does this feature help Hermes return better evidence?)
- Architecture (where does this module go? what's the contract?)
- Delegation (who does what)
- Integration and final review
- Git commits and pushes

### Subagents are the Engineers + QA

Every non-trivial coding task goes to a subagent. The subagent:
- Gets a clear, bounded goal with context
- Gets the exact files/specs they need to work on
- Returns a self-report + verifiable output
- Does NOT decide product direction or architecture

### After subagents return

The orchestrator:
1. Reads the actual files written (never trusts "done" from a subagent)
2. Runs `python3 -m py_compile hermes_trailhead/*.py`
3. Runs `python3 -m pytest -q`
4. Runs a live smoke test
5. Commits and pushes if everything passes
6. Updates the Hermes skill if conventions changed

## Current P0 roadmap (June 15, 2026)

### P0a — Evidence extraction follow-through

After `search --execute`, optionally extract/read top hits and report:
- Extraction attempted / succeeded / failed
- Usable text length
- Source type
- Why the hit is or isn't worth using

New module: `hermes_trailhead/extract.py`
New dataclasses: `ExtractionResult`, `ExtractedHit`
New CLI flag: `--extract` on `search`

### P0b — Source-quality scoring

Rank hits by likely usefulness:
- Favor: maintainer/official/canonical, practitioner firsthand, current, GitHub issues/PRs
- Penalize: SEO farms, empty platform shells, duplicate snippets, dead links, generic listicles

New module: `hermes_trailhead/scoring.py`
New dataclasses: `SourceScore`, `ScoredHit`
Integrated into `search --execute --extract` output

### P1 — Live route scoring ✅ (2026-06-15)
### P1 — Historical reliability tracking ✅ (2026-06-15)
### P2 — Benchmarks by user outcome ✅ (2026-06-15)

### P3 — PhD hard-source gauntlet ✅ (2026-06-23)

Deterministic product contract: `python3 -m hermes_trailhead gauntlet`.
Covers web, docs, GitHub, Reddit, X, YouTube transcripts, TikTok/Instagram discovery-only lanes, forums, and PDFs. Separates product/evidence quality from volatile live access. Current baseline: 100/100.

Aggregate: 77/100 across 6 benchmark tasks (4 pass, 2 partial, 0 fail).

## Delegation patterns

### Single engineer task
```
delegate_task(
    goal="Implement extraction follow-through in hermes_trailhead/extract.py",
    context="Working in /home/hermes/src/hermes-trailhead. Read hermes_trailhead/search.py first. ...",
    toolsets=["terminal", "file"]
)
```

### Parallel: engineer + QA
```
delegate_task(tasks=[
    {"goal": "Implement scoring engine", "context": "...", "toolsets": ["terminal", "file"]},
    {"goal": "Write tests + review extraction module", "context": "...", "toolsets": ["terminal", "file"]}
])
```

### Three-way: implement + test + docs
```
delegate_task(tasks=[
    {"goal": "Build extraction module", ...},
    {"goal": "Write test contracts for extraction", ...},
    {"goal": "Update docs and skill", ...}
])
```

## Commit conventions

```
feat: extraction follow-through for search --execute
fix: TikTok/Instagram execution caveat propagation
test: extraction contract regression tests
docs: TEAM.md engineering conventions
```

## Verification checklist (every PR)

```bash
cd /home/hermes/src/hermes-trailhead
python3 -m py_compile hermes_trailhead/*.py
python3 -m pytest -q
python3 -m hermes_trailhead gauntlet
python3 -m hermes_trailhead search all "test query" --execute --limit 2 --format json
# Extraction is default. Use --score to add quality ranking.
# Use --no-extract to skip extraction (discovery links only).
```

## Key files

| File | Owned by | Never touch without |
|---|---|---|
| `hermes_trailhead/search.py` | Tech Lead | Contract change approved |
| `hermes_trailhead/router.py` | Tech Lead | Route design review |
| `hermes_trailhead/channels.py` | Tech Lead | New channel approval |
| `hermes_trailhead/extract.py` | Backend Eng | P0a spec |
| `hermes_trailhead/scoring.py` | Backend Eng | P0b spec |
| `tests/test_search.py` | QA | After any search.py change |
| `tests/test_contracts.py` | QA | After any contract change |
| `README.md` | PM | Product language approval |
| `docs/` | PM + Tech Lead | Documentation review |
| `~/.hermes/skills/research/hermes-trailhead/SKILL.md` | DevOps | After conventions change |

## This file is the entry point

Every Hermes session that touches Trailhead: read this file first. It tells you:
1. What the team structure is
2. What the current P0 priorities are
3. How to delegate work
4. Where the code lives
5. How to verify before pushing
