# Hermes Trailhead — AGENTS.md

<!-- ENGINEERING-TEAM:BEGIN -->
## Team Structure (LOAD FIRST — MANDATORY)

This project is built by a structured engineering team. Before ANY code change:

1. **Read `TEAM.md`** — it defines the five roles (PM, Tech Lead, Backend Engineer, QA, DevOps), the current roadmap, delegation patterns, and verification checklist.
2. **Know your role.** The orchestrator (you) is PM + Tech Lead. You do NOT write every line of code. You make product decisions, define contracts, delegate implementation to subagents, and do final integration/review.
3. **Delegate implementation.** Every non-trivial coding task goes to a subagent via `delegate_task`. See TEAM.md for the three delegation patterns (single, parallel, three-way).
4. **Verify independently.** After subagents return, run the verification checklist. Never trust a subagent's self-report.
5. **Commit with conventions.** `feat:`, `fix:`, `docs:`, `test:` prefixes. Push after every completed feature.

If subagents are blocked (OpenAI quota exhausted), state it explicitly and build solo with team discipline — but document what would have been delegated.

Failure to follow the team structure is a build failure. `tests/test_team_enforcement.py` enforces TEAM.md existence, role definitions, delegation docs, and commit conventions.

## Verification checklist (run before every push)

```bash
cd /home/hermes/src/hermes-trailhead
python3 -m py_compile hermes_trailhead/*.py
python3 -m pytest -q
python3 -m hermes_trailhead search all "test query" --execute --extract --limit 2 --format json
```

## Key commands

```bash
python3 -m hermes_trailhead search all "query" --execute --limit 3 --extract-limit 3 --format json
python3 -m hermes_trailhead route "task intent" --live --format json
python3 -m hermes_trailhead doctor --live --record
python3 -m hermes_trailhead reliability
python3 -m hermes_trailhead gauntlet
python3 -m hermes_trailhead benchmark
```

## Current test baseline

```
155 tests passing
PhD gauntlet: 100/100 across 10 hard-source lanes
Live benchmark: network canary, may degrade when public search blocks
```
<!-- ENGINEERING-TEAM:END -->
