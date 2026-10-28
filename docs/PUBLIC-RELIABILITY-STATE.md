# Public reliability (P2) — day 1 cold and warm observed

Latest verified update: warm actually ran **2026-10-28T17:00:06Z–17:00:10Z**,
using the six persisted cold homes, after the required real 30-minute gap.
[evidence/public-reliability-day1-warm.json](evidence/public-reliability-day1-warm.json)
records six calls: all status `ok`, four `incomplete`, two `markers_present`.
Product git objects were identical to the cold run; only docs/tests/harness HEAD
changed. Across cold and warm, 12 calls were observed on **one** calendar day;
this is not five-day reliability or completeness. Days October 29–November 1
remain unobserved. The original cold-phase snapshot below is retained as history;
its pending-warm language is superseded by this actual observation.

Runtime limitation: goal-mode rejected `kanban_schedule`; no timer was created.
Day 2 needs an orchestrator wake of this same card on October 29 at 16:00 UTC,
then a new dated cold session and a warm round at least 30 minutes after it ends.

Status: **one cold phase executed; the campaign is not complete and nothing here
is a reliability claim.** Day 1 has 6 of 6 planned cold invocations recorded and
the warm phase is still pending. Days 2–5 of the required five consecutive
calendar days have **not been observed** and are listed as gaps below, not
interpolated.

Machine-readable record for this phase:
[`evidence/public-reliability-day1-cold.json`](evidence/public-reliability-day1-cold.json).
Frozen manifest (unchanged, shared with P1/P3):
[`evidence/public-remaining-manifest.json`](evidence/public-remaining-manifest.json)
— `manifest_sha256` `f92830f49ba59183…`, byte-identical to the P1/P3 freeze.
Rules: [PUBLIC-REMAINING-ACCEPTANCE.md](PUBLIC-REMAINING-ACCEPTANCE.md) §4.

## 1. What was frozen before the first measured call

| Field | Value |
| --- | --- |
| Session tag | `p2-2026-10-28` |
| UTC day | 2026-10-28 |
| Declared UTC window | **16:00–18:00** (declared via CLI, `declared_source: cli`) |
| States | `cold` then `warm`, 30 min minimum gap (P2 §4) |
| Observations per case/tool/state | 1 (3 cases × 2 tools = **6 calls per phase**) |
| Manifest | `docs/evidence/public-remaining-manifest.json`, unchanged |
| Tools | Trailhead at `HEAD`, Agent Reach pinned venv executable (version + commit + exe SHA in the record) |
| ASR | `TRAILHEAD_DISABLE_ASR=1`, asserted per child |
| Auth / quota / paid | none — public lane only |
| State | `.git/trailhead-reliability-p2/p2-2026-10-28/` (private, never committed) |

The window was declared in the same invocation that made the first measured
call, i.e. before any observation existed. The cold phase started at
**16:29:44Z**, inside the window, so the phase is recorded as `late: false`.

## 2. Day 1 cold — actual result

Started `2026-10-28T16:29:44Z`, ended `2026-10-28T16:30:05Z`. All six calls
returned HTTP-level success (`status: ok`); the verdict column is the frozen P1
assessment, not a success rate.

| Case | Tool | Status | Verdict | Required units present | Truncation | Continuation |
| --- | --- | --- | --- | --- | --- | --- |
| `public-docs-python-typing` | trailhead | ok | incomplete | 5 / 5 | **true** | pending |
| `public-docs-python-typing` | agent_reach | ok | incomplete | 5 / 5 | unknown | unknown |
| `public-github-requests-readme` | trailhead | ok | markers_present | 4 / 4 | false | exhausted |
| `public-github-requests-readme` | agent_reach | ok | incomplete | 3 / 4 | unknown | unknown |
| `public-v2ex-node-python-zh` | trailhead | ok | markers_present | 3 / 3 | false | exhausted |
| `public-v2ex-node-python-zh` | agent_reach | ok | incomplete | 3 / 3 | unknown | unknown |

Reading this honestly:

- "6 of 6 calls returned `ok`" is a statement about **one** round on **one**
  day. It is not a reliability rate, and one day cannot produce one.
- `markers_present` means every required marker was found **and** truncation was
  explicitly false **and** the continuation was known to be exhausted. It is not
  a completeness certificate.
- The docs case is `incomplete` for both tools for different reasons: Trailhead
  reports `truncated: true`, Agent Reach reports no truncation flag at all. The
  GitHub README is missing `readme_intro` on Agent Reach. V2EX on Agent Reach is
  gated only by its unknown truncation/continuation, not by a missing marker.
- No winner, ranking, "better" or "faster" statement follows, and per-tool
  resources from a single 6-call phase are not a distribution.

## 3. Day 1 warm — pending, not run

The warm round reuses the **same** sandbox homes the cold round built (the
private state directory holds them), so "warm" here means the same empty homes
half an hour later, not a new throwaway tree.

- **Earliest permitted start: `2026-10-28T17:00:05Z`** (cold end + 30 min).
- The gate rejects an earlier start **before any call**; this was verified live
  at 16:30:21Z (`refusing warm: premature warm … no call was made`, exit 2, no
  `raw/warm` directory created).
- The gate also refuses, before any call: a recorded cold rerun, a warm rerun, a
  different manifest hash, a changed tool/version fingerprint, a partial cold
  (e.g. 5 of 6 rows), and a home that is missing, incomplete or a symlink.

Exact command for the warm round (`--show-next` prints the same block):

```bash
cd <repo>
export TRAILHEAD_DISABLE_ASR=1
.venv/bin/python scripts/evaluate_public_resources.py \
  --phase warm --session p2-2026-10-28 \
  --state-dir .git/trailhead-reliability-p2 \
  --manifest docs/evidence/public-remaining-manifest.json \
  --agent-reach "$TMPDIR/agent-reach-eval-venv/bin/agent-reach" \
  --out docs/evidence/public-reliability-day1-warm.json --timeout 25
```

If the warm round starts after 18:00Z it is still recorded, but labelled
`late: true` rather than silently pooled with an in-window run.

## 4. Coverage: what is observed and what is a gap

Required by §4: five consecutive calendar days, two rounds per day.

| Calendar day (UTC) | State |
| --- | --- |
| 2026-10-28 | cold observed; warm pending |
| 2026-10-29 | **gap — not observed** |
| 2026-10-30 | **gap — not observed** |
| 2026-10-31 | **gap — not observed** |
| 2026-11-01 | **gap — not observed** |

`coverage.multi_day_complete` is `false` in the record, and the day list is
literal calendar dates. A day that is missed stays a gap: it is not
interpolated, and a later retry on another day is a new observation, not a
repair of the missed one.

## 5. How the resumable state works

```
.git/trailhead-reliability-p2/p2-2026-10-28/
  session.json                 frozen window, manifest hash, tool fingerprint,
                               cold observations, (later) warm observations
  homes/<case>/<tool>/         exact sandbox trees cold built; warm reuses them
  raw/<phase>/                 raw stdout/stderr/rusage per invocation
```

- Cold persists a row after every call. A crash therefore leaves a **visible**
  partial phase; the gates refuse to top that up, and a 5-of-6 cold is published
  as a partial phase and a gap, never completed by a rerun.
- The state directory is inside `.git`, so it is not tracked, not committed and
  not published. Only the sanitized evidence JSON is.
- The evidence file contains no absolute host path; the only name in it is the
  manifest's own pre-existing `frozen_by` string, unchanged from the P1/P3 freeze.

## 6. Not measured

The warm round, days 2–5, consent-gated lanes, quota/ASR lanes, and the GitHub
issue/PR lane under this runbook. No "always works", "reliable", "complete" or
"5-day" claim is made anywhere in this document or the record it describes.
