# Public remaining acceptance — frozen procedures, first executions recorded

Latest execution addendum (2026-10-28T16:45Z):
[P5 GitHub discussion campaign](GITHUB-DISCUSSION-ACCEPTANCE.md) now records
eight bounded calls on a separate frozen manifest. Both tools returned comment
bodies; Trailhead additionally exposed IDs and bounded-capture disclosures.
Literal-format marker totals are not a fair comparative score. P5 multi-day
and repeated resource distributions remain unmeasured. P2 day-one cold has
[started](PUBLIC-RELIABILITY-STATE.md); warm is time-gated. Historical “unrun”
statements below describe the original freeze, not these later executions.

Status: **procedures frozen 2026-10-28; the first bounded executions are now
recorded.** P1 (single-day artifact completeness) and P3 (per-tool resources) were
run once each — 60 invocations on the three frozen cases
([PUBLIC-RESOURCE-EVIDENCE.md](PUBLIC-RESOURCE-EVIDENCE.md); corrected offline
reassessment
[`evidence/public-resource-reassessment.json`](evidence/public-resource-reassessment.json))
— and the 40-action artifact campaign ran seven rounds
([ACTION-ARTIFACT-EVIDENCE.md](ACTION-ARTIFACT-EVIDENCE.md)). Still unrun: P2
multi-day reliability, the P4 consent/quota lanes, and the P5 GitHub issue/PR cases
under this runbook. No completion, coverage or superiority claim is made. The page
still exists so the rest can be executed without re-deciding the rules after seeing
output. It does not mark the [superiority plan](SUPERIORITY-ACCEPTANCE.md) done and
it does not claim public work is exhausted.

Machine-readable inputs referenced here already exist:
[`evidence/public-acceptance.json`](evidence/public-acceptance.json),
[`evidence/public-acceptance-before.json`](evidence/public-acceptance-before.json),
[`evidence/action-sweep-replay.json`](evidence/action-sweep-replay.json),
[`evidence/search-relevance.json`](evidence/search-relevance.json),
[`evidence/search-followup.json`](evidence/search-followup.json).

## 1. Lane split: available public work vs consent-requested lanes

Counts come from `reach_backend.parity_inventory()["counts"]` (14 channels,
40 actions). "Live" means a dated real call recorded in a doc; fixture/native
tests are contract evidence, not live evidence.

| Lane | Count | Current evidence | Can be run without asking anyone? |
| --- | --- | --- | --- |
| Public actions | 26 | all 26 attempted once on 2026-10-28T15:13Z: 17 inspected, 9 preserved upstream failures ([ACTION-ARTIFACT-EVIDENCE.md](ACTION-ARTIFACT-EVIDENCE.md) §3–§5) | Yes — public routes, no login, no quota |
| Public artifact cases | 3 pages, 60 per-tool invocations | 18 paired executions earlier; then 3 cases × 2 tools × 2 states × 5 rounds in one 36 s window ([PUBLIC-RESOURCE-EVIDENCE.md](PUBLIC-RESOURCE-EVIDENCE.md)) | Yes |
| Public multilingual search rows | 3 queries × 3 hits | Agent-reviewed relevance; 9 snippets recovered later ([SEARCH-RELEVANCE-EVIDENCE.md](SEARCH-RELEVANCE-EVIDENCE.md), [SEARCH-FOLLOWUP.md](SEARCH-FOLLOWUP.md)) | Yes |
| Consent actions | 12 | None run; route needs an existing upstream login (`--allow-authenticated`) | **No** — explicit operator consent and an existing login state |
| Quota actions | 2 (`youtube transcribe`, `xiaoyuzhou transcribe`) | None run; double consent + ASR veto; zero quota spent | **No** — quota budget and auth consent are separate decisions |

What the table does **not** say: one live attempt per public action is still one
attempt on one host, three pages are not "the public web", one day is not
reliability, and 17 inspected artifacts are not completeness (whole-artifact
completeness: 0 of 3). A `public` gate says a call is allowed; it does not say the
call succeeded.

A native GitHub **issue/PR** lane is integrated in this tree (§7). It has no frozen
manifest case and no result under these procedures, so it is not in the counts
above.

## 2. Frozen manifest (shared by P1–P3)

Before any measured run, an **independent reviewer** — not the person who wrote
the change under test — writes and hashes one manifest:

`docs/evidence/public-remaining-manifest.json`

The campaign actually run did **not** satisfy that: the manifest was frozen by the
engineer who wrote the harness (`--frozen-by` pre-filled "independent reviewer"
before that default was removed). Independence from the two tools under test holds;
independent review of the manifest is **not** established. The frozen file was left
byte-identical rather than edited to say so — the correction is in
[PUBLIC-RESOURCE-EVIDENCE.md](PUBLIC-RESOURCE-EVIDENCE.md) §1.

```json
{
  "schema": "trailhead.public-remaining-manifest/1",
  "frozen_at": "<UTC>",
  "frozen_by": "<reviewer>",
  "manifest_sha256": "<hash of the canonical JSON without this field>",
  "cases": [
    {
      "case_id": "public-<family>-<slug>",
      "lane": "public",
      "url_or_action": "https://... or 'github search <query>'",
      "requested_outcome": "what the caller asked for, in one sentence",
      "tool_argv": {
        "trailhead": ["python", "-m", "hermes_trailhead", "read", "<url>", "--format", "json", "--timeout", "25"],
        "agent_reach": ["<agent-reach>", "<channel>", "<action>", "...", "--", "<target>"]
      },
      "artifact_units": [
        {"id": "identity", "kind": "text_any_of", "values": ["..."], "required": true},
        {"id": "all_comments", "kind": "regex_distinct", "pattern": "...", "min_distinct": 1, "required": true, "whole_artifact": true},
        {"id": "license_field", "kind": "field_present", "field": "license", "required": false}
      ],
      "pagination_expectation": {"whole_artifact": true, "continuation": "cursor|page|none", "max_units_known": null},
      "truncation_matters": true
    }
  ]
}
```

Frozen rules:

- `artifact_units` are **requested outcomes**, not character budgets or a list of
  words that happened to be present in a first run. No unit may be added, removed,
  re-worded or re-weighted after the first measured run; a changed manifest is a
  new version and a new campaign.
- `whole_artifact: true` means the claim is "the complete artifact", so a
  truncated page, a missing continuation page or a missing reply/comment makes the
  case incomplete even if every sampled marker is present.
- `kind: field_present` records which field satisfied the unit (body, metadata,
  API field). A metadata match never counts as body text.
- `min_distinct` is a count of distinct matches, not a quality score. Repeated
  promotional copies of one URL count once.

The manifest hash, the tools' versions/commits and the host description are
recorded in every output artifact. Raw stdout/stderr stay in the scratch
directory named at run time; sanitized JSON goes under `docs/evidence/`.

## 3. P1 — artifact completeness (public, single day)

Purpose: replace "returned something" with a per-artifact verdict.

1. Reviewer checks a clean tree (`git status --porcelain` empty except this
   campaign's outputs), records `git rev-parse HEAD`, tool versions, host,
   UTC start time, and confirms no credentials are present (public lane only).
2. For each manifest case, run each tool **once per round** with the frozen
   `tool_argv`, a fixed 25 s killable timeout, and the environment-isolated tree
   for Agent Reach (`comparative.build_sandbox`; environment isolation only, not
   a filesystem sandbox). Export `TRAILHEAD_DISABLE_ASR=1` so no media/paid path
   can be reached; record that it was set.
3. Preserve the raw payload byte-for-byte in scratch. Evaluation reads that raw
   payload, never a re-typed summary.
4. Per unit, record `present | absent | unverified`, with offset ±40 characters
   of context, the region (body / metadata / structured field), and whether the
   text was truncated. `unverified` means the tool returned no artifact (error,
   blocked, auth wall) — it is not "absent".
5. Case verdict:
   - `complete` — every required unit present **and** no truncation on a
     `whole_artifact` unit **and** the continuation/pagination is known to be
     exhausted.
   - `incomplete` — a required unit absent, a required unit truncated, or a
     continuation page/reply set not exhausted.
   - `unverified` — no artifact to evaluate.
6. Count `returned characters`, `truncated: true|false`, distinct URLs/ids and
   continuation state alongside the verdict. Character count never upgrades a
   verdict.

Claim rule: report "on these N cases, X of Y required units were present; C cases
were complete". Presence counts are not completeness rates, and no cross-tool
winner follows from them.

## 4. P2 — repeated multi-day public reliability

Purpose: test whether a result survives different days, not just a different
minute.

- Same frozen manifest as P1, public cases only. Minimum campaign: **5
  consecutive calendar days**, **2 rounds per day** (first round cold — fresh
  scratch tree; second round warm — same sandbox tree, at least 30 minutes
  later). Three cases × 5 days × 2 rounds = 30 paired observations per tool.
- All runs inside one declared UTC window per day (e.g. 13:00–15:00 UTC) so the
  comparison is not spread across the day. Record the window in advance; a run
  outside it is labeled late, not silently pooled.
- Per run record: UTC timestamp, engine/attempt ladder, status (`ok`,
  `rate_limited`, `blocked`, `timeout`, `missing_page`, `auth_required`,
  `error:<code>`), item count, latency, cold/warm, origin/CDN cache headers if
  the response exposes them, and a short failure reason.
- Report per case/tool: successes / attempts, with every failure listed by date
  and reason. A missed day is reported as a gap; it is never interpolated. A
  retry the next day is a separate observation, not a repair of the failed one.
- Cold/warm are reported separately. Warm runs may reuse a sandbox tree but must
  not reuse a recorded response from a previous round unless the procedure says
  "cached" and the cache age is recorded.

Execution state for this campaign is tracked in
[PUBLIC-RELIABILITY-STATE.md](PUBLIC-RELIABILITY-STATE.md). The harness runs it
as `--phase cold|warm` with persisted private state under
`.git/trailhead-reliability-p2` (never committed); one phase is 3 cases × 2 tools
= 6 calls, and the warm phase is gated on ≥30 min after the cold phase ended.
Day 1 cold is recorded there; day 1 warm and days 2–5 are still open gaps.

Claim rule: "k of n attempts succeeded in this window". Never "always works",
never "reliable" without the denominator and window, never a 100 % claim from a
single day.

## 5. P3 — per-tool resource measurement

Purpose: make speed/memory comparable without attributing a combined process to
either tool.

- Measure **one tool per invocation**. Wrap exactly that invocation in
  `/usr/bin/time -v` (or `resource.getrusage(RUSAGE_CHILDREN)` in a wrapper that
  starts exactly one child). Never wrap a comparator that runs both tools: the
  resulting peak RSS is the comparator's, not either tool's.
- Same requested outcome, same 25 s killable timeout, same host/OS/CPU/RAM, same
  tool versions/commits, and runs adjacent in time. Record host, CPU count, RAM,
  UTC, load average and network moment; if the two tools could not be measured in
  the same window, say so and do not present the numbers as a head-to-head.
- **5 runs per case per tool per state** (cold and warm), interleaved
  (TH, AR, TH, AR, …) so a network change does not land on one side only.
  Cold = fresh sandbox/scratch directory and no warm HTTP cache; warm = second
  run in the same directory. Record which.
- Per run: wall seconds, user + sys CPU, peak RSS kB, exit code, stdout bytes,
  stderr bytes, `truncated`, and timeout flag. Report median and min/max — a
  single run is never reported as the number.
- Setup and download cost is reported **separately** from call cost: install
  commands, elapsed time, archive/venv size, distribution count, and whether test
  extras are included. A dev venv is not a like-for-like runtime footprint.
- API/paid use: count requests per case where the tool exposes it; public
  campaigns must record zero paid/auth/quota calls.

Claim rule: per-tool RSS and CPU may be compared only when each was measured in
its own process with the same case and state. Otherwise record "not attributed".
The existing combined-process number in
[PUBLIC-ACCEPTANCE-EVIDENCE.md](PUBLIC-ACCEPTANCE-EVIDENCE.md) stays
"not attributed" until P3 replaces it.

## 6. P4 — consent-requested lanes (separate from public work)

These are **not** public acceptance cases and must never be pooled with P1–P3.

| Lane | Actions | Preconditions | If preconditions are absent |
| --- | --- | --- | --- |
| Consent (`gate: consent`) | 12 actions, e.g. `twitter profile/tweets/thread`, `instagram *`, `reddit subreddit`, `xiaohongshu comments`, `bilibili subtitle`, `xueqiu hot_*` | Explicit per-run operator consent (`--allow-authenticated`) and an existing upstream login the operator created; record consent scope, not credential values | Record `gated_not_run`; never execute, never infer a result |
| Quota (`gate: quota`) | `youtube transcribe`, `xiaoyuzhou transcribe` | Quota consent **and** auth consent **and** `TRAILHEAD_DISABLE_ASR` unset; a separate spend decision; Trailhead does not meter spend | Record `gated_not_run`; no transcript, no quota spent |

Rules for these lanes:

- Acceptance means "the action ran against the operator's existing state and
  returned the requested artifact", not "the flag was accepted". Record the
  reported route/backend, artifact units, truncation and the provider/model for
  transcription.
- No credential, cookie or session content is written to the repo. Record only
  that a login state existed and its upstream source (`upstream-home-config`).
- Account lifecycle (login, status, expiration, switch, logout/revocation) is a
  separate acceptance set; a successful read does not verify lifecycle.
- A refused or unavailable lane is `not_run`, not a failure of the product and
  not a pass.

## 7. P5 — GitHub issue/PR lane (integrated; not yet run under this runbook)

A native GitHub **issue/PR** reading lane is integrated (`6100815`, `d6f5029`) and
was independently exercised on `pallets/flask#5` and PR `#112`
([`evidence/parent-github-artifact-verification.json`](evidence/parent-github-artifact-verification.json)).
It has no frozen manifest case and no P1/P2/P3 result, so nothing in this document
is its acceptance.

To accept it:

1. Add manifest cases whose `requested_outcome` is the complete issue/PR body,
   all comments/review comments (pagination included), and the state/metadata
   fields the caller asked for.
2. Run P1 (completeness), P2 (multi-day) and P3 (per-tool resources) unchanged;
   record the commit that introduced the lane.
3. Until that manifest exists, record `integrated_unmeasured`. Do not infer issue/PR
   completeness from `agent-reach github read` forwarding — it is `native-partial`
   and its comment coverage is not established.

## 8. Recording and claim rules

Every campaign writes one sanitized JSON record plus raw scratch, containing:
manifest hash, reviewer, tree commit, tool versions, host, per-run records, case
verdicts, denominators and explicit `not_run` rows. Unrun work is never omitted.

Prohibited by this runbook:

- "All public work is exhausted", "acceptance complete", "plan done".
- "Complete artifact" from marker presence alone, or from a character count.
- "Per-tool memory/latency" from a process that ran both tools.
- "Human-reviewed relevance" from agent reading; the nine recovered snippets in
  [SEARCH-FOLLOWUP.md](SEARCH-FOLLOWUP.md) are agent-read only.
- "Supported" from advertised/surfaced/fixture states.
- Pooling consent or quota lanes into a public success rate.
- Reporting a GitHub issue/PR result before the lane is integrated and measured.

Required in every report: dates and UTC window, counts with denominators, failure
reasons, truncation/pagination state, consent status, and a plain statement of
what was not measured.

## 9. Reproduce (procedures and what has been run)

```bash
cd <repo>
git rev-parse HEAD
unset TRAILHEAD_DISABLE_ASR            # suite baseline; P1/P2 still export it deliberately
.venv/bin/python -m pytest -q          # 928 passed at this freeze (2026-10-28)

# P1 base cases: reuse the frozen harness cases, do not retype argv
export TRAILHEAD_DISABLE_ASR=1         # no media/paid path in a public campaign
.venv/bin/python scripts/evaluate_public_acceptance.py \
  --agent-reach /path/to/agent-reach \
  --scratch /tmp/public-remaining \
  --repeats 3 \
  --out docs/evidence/public-remaining-p1.json

# P3: one tool per /usr/bin/time invocation, e.g. Trailhead read only
/usr/bin/time -v .venv/bin/python -m hermes_trailhead read \
  "https://docs.python.org/3/library/typing.html" --format json --timeout 25
```

The harness above covers the three existing public cases; new cases require their
own frozen manifest per §2. No multi-day campaign has been run. The single-day
P1/P3 campaign and the 40-action campaign are recorded in
[PUBLIC-RESOURCE-EVIDENCE.md](PUBLIC-RESOURCE-EVIDENCE.md) and
[ACTION-ARTIFACT-EVIDENCE.md](ACTION-ARTIFACT-EVIDENCE.md).
