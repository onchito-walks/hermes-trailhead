# Campaign QA — independent audit of the two new public harnesses

Status: **audit complete for the two harnesses and the records they produced.**
Two measurement defects were real and are fixed in this change; one product-level
overstatement and three documentation claims are reported for their owners rather
than edited here. No live campaign was re-run, no frozen manifest was re-frozen,
and `hermes_trailhead/extract.py` was not modified (another lane owned it and was
editing it throughout this audit — see §4).

Audited tree: `HEAD 42cd70ce237183e867eda6bb54dadb732a8f2567` plus the untracked
new files below. `extract.py` was modified by a concurrent lane during the audit
and changed twice while this page was being written (`eed08a2b…` at 15:26 UTC,
282 insertions / 17 deletions); all statements about it are therefore about a
snapshot, not a fixed commit.

Files this audit owns:

| file | role |
|---|---|
| `scripts/evaluate_public_resources.py` | public per-tool resource + artifact harness (P1/P3) |
| `scripts/evaluate_action_artifacts.py` | 40-action artifact harness |
| `tests/test_public_resources.py`, `tests/test_action_artifacts.py` | their contract tests |
| this page | QA record |

## 1. Short answer

- **Process-level measurement holds.** One child process per measured invocation,
  that child's own `RUSAGE_CHILDREN` wall/CPU/peak-RSS, one equal killable
  25 s process-group deadline, an env allowlist that fails closed, and
  `TRAILHEAD_DISABLE_ASR=1` asserted for every child. There is no combined-tool
  number anywhere in the record, and no `complete` artifact claim in the public
  campaign.
- **Two defects did reach the published numbers**, both in the direction of
  overstating what was observed:
  1. a *tool failure* was published as an *artifact incompleteness*
     (`incomplete` + four `absent` required units) — fixed;
  2. the required-unit presence denominator quietly excluded units that were
     never assessed, so `225/240` read as a rate when the honest denominator is
     `236` — denominator now explicit, fixed.
- One false-success path existed in the measurement wrapper (`status: ok` with
  every metric `null`) — fixed, and it did **not** occur in the published run.
- The action harness had no `absent`-vs-`unverified` misreport in its published
  round, but had a latent one in `row_verdict` plus a fragile zero-spawn filter
  and no evaluator identity in its record. All three are fixed; none changes the
  published action numbers.
- **The largest single overstatement is not in either harness**: `read`
  returned a 215-character repository *metadata stub* for
  `https://github.com/psf/requests` with `extraction_status: ok`,
  `truncated: false`, `pagination.more: false`. That is `extract.py`'s contract,
  reported in §4 (QR-01), not repairable from a harness.

## 2. What was actually executed (not read and assumed)

| check | method | result |
|---|---|---|
| Frozen public manifest integrity | recomputed canonical SHA-256 and file SHA-256 | `f92830f4…` matches `manifest.manifest_sha256` in the published JSON; file `84bc2008…` matches `PUBLIC-RESOURCE-EVIDENCE.md` §1 |
| Invocation count / plan | counted `runs` in the published JSON | 60 = 3 cases × 2 tools × 2 states × 5 rounds = planned 60 |
| Per-case/tool/state table (Table A) | recomputed median / min / max / ok-count / stdout median from `runs` | **0 mismatches** against the 12 published rows |
| Required-unit table (Table B) | recomputed per case/tool | **0 mismatches** (50/50, 38/40, 30/30, 50/50, 27/40, 30/30) |
| Raw artefacts exist | counted scratch files | 60 stdout + 60 stderr + 60 rusage; 30 sandbox trees (3 cases × 5 rounds × 2 tools) |
| "Warm" is a second run in the same tree | read `comparative.build_sandbox` (mkdir `exist_ok`, no wipe) and listed the trees | cold and warm share one tree per (case, tool, round); no tree is shared between rounds |
| Wrapper starts exactly one child | read `WRAPPER_SRC` | one `Popen`, one `wait`; `child_count: 1` in all 60 rusage records |
| Equal deadline | read frozen argv + wrapper + design block | `--timeout 25` inside both tools' argv and a 25 s killable group deadline; 0 timeouts in the record |
| Zero-credential public lane | read `build_sandbox` + `check_env`; inspected the env actually used | allowlist only (`PATH/LANG/HOME/…`), fails closed, ASR asserted |
| Action manifest vs pinned inventory | ran `build_manifest()` assertions | 40 rows, 14 channels, gates 26/12/2, digest `19cf1ba4…` == published |
| Action per-action table | parsed all rows of `ACTION-ARTIFACT-EVIDENCE.md` §4 and compared to the JSON | 36 comparable rows parsed, **0 mismatches** (items, body chars, trunc, verdict) |
| Action conditions | recomputed from `rows` | `home_mode: isolated-temp` 26/26 public; routes 16 `public_api` + 10 `public_web`; coverage `upstream` 28/40 |
| Action gate claims | recomputed from `gate_probe` | 14/14 refused, `runner_calls: 0`, no action argv |
| Published sanitisation | regex scan of both evidence JSONs | 0 absolute-path hits, no `sk-`/`Bearer ` |
| Test claims | collected and ran | action file had exactly 19 tests as documented (now 22); 1033 tests pass repo-wide |
| `boss read` digest claim | re-hashed the raw body | `f7dba9e2db1ed96f…` matches §9.1 verbatim |

## 3. Defects fixed in this change

### QA-01 — a tool failure was published as artifact incompleteness (public harness) — **high**

*Observation.* `read_payload` sets `parsed: true` for any JSON object, including
an error envelope. `assess_units` then searched an empty body, so every required
marker came back `absent`, and `case_verdict` returned `incomplete` with
`required_unit_absent:…`.

*Evidence (published record).* `public-github-requests-readme` / `agent_reach` /
warm r5: `status: exit:1`, `error_code: RATE_LIMITED`, `items: 0`,
`body_chars: 0`, `required: 0/4`, `verdict: incomplete`,
`reasons: ["required_unit_absent:repo_identity,readme_install,readme_usage,readme_intro", …]`.
The raw stdout is
`$TMPDIR/public-resource-campaign/public-github-requests-readme/agent_reach-warm-r5.stdout.json`
(`ok: false`, `items: []`, two attempt records, `RATE_LIMITED`).

*Why it matters.* It converts "the tool was rate-limited" into a claim about an
artifact that never existed, and it inflates the `absent` count. A comparison
reader cannot tell the two apart from `verdict` alone.

*Change.* `has_artifact(payload)` (parsed **and** not `ok: false`) now gates both
`assess_units` and `case_verdict`; such a run yields `unverified`, units stay
`unverified` with the tool's own status/error in `reason`, and the row carries
`required_total`, `required_present: 0`, `required_assessed: 0`.

*Test.* `test_tool_error_envelope_is_unverified_not_incomplete`.

### QA-02 — presence denominator hid units that were never assessed (public harness) — **medium**

*Observation.* `required_total` was only emitted on the parsed path, so a row with
no artifact contributed `None` to both numerator and denominator. `_summarize`
silently dropped those units, and the published `225/240` denominator contains
four units (the rate-limited run) that no one ever judged.

*Change.* Every row now records `required_total`/`required_present`/`required_assessed`;
`required_unit_presence` reports `present`, `total` (declared), `assessed`,
`unassessed`, with the comment that a ratio over `total` is a lower bound.

*Verified by replay.* Re-running the fixed evaluator over the archived 60 raw
stdout files yields `present 225 / assessed 236 / declared 240 / unassessed 4`;
per tool: Trailhead 118/120, Agent Reach 107 of 116 assessed (120 declared).
Only the rate-limited row changes verdict (see §5).

*Test.* `test_presence_denominator_reports_unassessed_units`.

### QA-03 — a wrapper that wrote no measurement was reported as `ok` (public harness) — **medium**

*Observation.* If the wrapper was killed after `timeout_s + 30` (or died), the
rusage JSON did not exist, every metric was `None`, and the status chain fell
through to `status: "ok"` because `error`, `timed_out` and `exit_code` were all
absent. The published record is not affected (all 60 rusage files exist), but the
branch would have published an unmeasured run as a success.

*Change.* Missing/torn rusage record now yields `status: "harness_error"` with the
wrapper's stderr preserved in the row.

*Test.* `test_a_wrapper_that_writes_no_measurement_is_not_a_success`.

### QA-04 — `--frozen-by` pre-filled an independence claim (public harness) — **low**

*Observation.* The CLI default was `"independent reviewer"`. The frozen manifest
of this campaign therefore says *"independent reviewer (monchobotjr subagent; not
an author of the harness or the tools under test)"* while the same subagent wrote
the harness. A default must not manufacture provenance.

*Change.* `DEFAULT_FROZEN_BY = "unspecified"`, documented in the constant, plus a
stderr warning when `--freeze` runs without `--frozen-by`.

*Deliberately not changed:* `docs/evidence/public-remaining-manifest.json`. It is
the campaign's frozen input; editing it would break `f92830f4…` and destroy the
only provenance the campaign has. The correction belongs in the prose record
(§6, handoff item H-1).

*Test.* `test_frozen_by_default_is_not_an_independence_claim`.

### QA-05 — an uninspectable required unit was labelled "not present" (action harness) — **low**

*Observation.* `row_verdict` mapped every required unit whose status was not
`present` into `required_unit_not_present`, including `unverified` ones (e.g.
`body_not_error_shell` when a metadata-only artifact has no body). The verdict
`incomplete` is the conservative answer; the *reason* was wrong. The published
round has no such row (`units_by_status` shows 0 `absent`, 40 `unverified`, all on
failed rows), so no published number moves.

*Change.* Reasons are split: `required_unit_not_present:…` only for inspected-and-
missing units, `required_unit_unverified:…` for units that could not be inspected
(both may appear, `; `-joined). Verdict semantics unchanged.

*Test.* `test_uninspectable_required_unit_is_not_reported_as_absent`.

### QA-06 — zero-spawn filter depended on one exact argv shape (action harness) — **low**

*Observation.* `[c for c in spy.calls if c[1:] != ["channels"]]` only recognises
discovery as exactly `[<exe>, "channels"]`. A flagged discovery call
(`[<exe>, "channels", "--json"]`) would have been reported as an action process,
i.e. the harness would claim its own gate leaked when it did not.

*Change.* `_action_calls()` treats any argv whose first argument is `channels` as
discovery.

*Test.* `test_gate_spawn_count_ignores_discovery_argv`.

### QA-07 — the record could not identify the evaluator that judged it (action harness) — **low**

*Observation.* The manifest digest covers what was requested, not the code that
judged it. The campaign's own round log proves the gap: round 1 was judged by a
harness that did not copy `whole_artifact` into the row and reported read rows as
`complete`; rounds 2–7 share the same manifest hash `19cf1ba4…` with different
evaluator behaviour. Nothing in the JSON says which code produced a given round.

*Change.* `evaluator_identity()` (script path, script SHA-256, manifest version,
shell window, unit kinds) is written to the top level of the summary, **outside**
the manifest, so the frozen digest is untouched.

*Test.* `test_summary_records_the_evaluator_that_judged_the_rows`.

## 4. Defects found and **not** fixed here (owners / frozen artefacts)

### QR-01 — `read` returns a repository metadata stub as an ok, non-truncated read — **high (product, `extract.py`)**

`public-github-requests-readme` / `trailhead` / warm r5 returned 215 characters:

```
GitHub repository: psf/requests
A simple, yet elegant, HTTP library.
Homepage: https://requests.readthedocs.io/en/latest
```

with `extraction_status: "ok"`, `content_length: 215`, `truncated: false`,
`pagination: {more: false, total_available_chars: 215, …}`. The README never
arrived; the payload says the artifact is complete. The harness contained the
damage at the unit level (install/usage `absent` → `incomplete`), and the evidence
page discloses the row in Table C, but the tool-level contract is wrong: a
metadata-only fallback is reported with the same success flags as a real read.
Same class as the `boss read` loading page (action harness §9.1). Owner:
`extract.py` lane. The harness did its job here; do not "fix" it by relaxing the
unit.

### QR-02 — reviewer-independence wording in `PUBLIC-RESOURCE-EVIDENCE.md` §1 — **medium (doc)**

The page and the manifest both assert independence ("subagent not an author of
the harness or of the tools under test"). The harness in this tree was written by
that same subagent. Independence is **not established**. Do not edit the frozen
manifest; correct the prose (H-1).

### QR-03 — `225/240` denominator — **medium (doc)**

`PUBLIC-RESOURCE-EVIDENCE.md` §4 and §5 present `225/240` required markers
present. Four of those 240 belong to the rate-limited run and were never
assessed. Honest phrasing: *225 present of 236 assessed (240 declared; 4
unassessed on one rate-limited run)*. The number 225 is right; the denominator
overstates coverage by implying all 240 were judged (H-2).

### QR-04 — the disclosed `extract.py` digest is stale — **low (doc)**

§1 discloses `sha256 3b09e1…` and "136 insertions". The file was `eed08a2b…` at
282 insertions / 17 deletions by 15:26 UTC and changed again in `4ce43ce`. The
disclosure is a point-in-time statement and must be dated as such, or re-taken at
handoff (H-3).

### QR-05 — "0 verdicts changed" re-assessment is unverifiable — **low (claim)**

§8 states that the archived 60 payloads were re-assessed offline under evaluator
v1 and v2 with "0 verdicts changed". No output of that comparison exists in the
repo or in scratch, and v1 is no longer in the tree, so the claim cannot be
checked. Keep only with the comparison output attached; otherwise mark it
engineer-reported (H-4).

### QR-06 — mid-capture socket timeout discards fetched pages (`extract.py`) — **low**

`_github_paginated_list` returns a partial capture marked `deadline_exhausted`
when *its own* `_GithubReadTimeout` fires, but a socket/HTTP timeout raised by
`_github_api_json` mid-capture propagates and the already-fetched pages are lost
(`_github_section` reports "not captured"). This under-reports rather than
inflates, and it is inconsistent with the documented aggregate-deadline contract.
Owner: `extract.py` lane. The deadline tests (7) pass; this path is simply not
one of them.

### QR-07 — "53/53 required units present" is structural, not a quality claim — **low (doc risk)**

The action units are deliberately structural (`item_field_all`, `body_text` =
*any* non-empty body, `no_shell_marker`). `boss read` satisfies them with a
54-character loading page (disclosed in §5/§9.1), so 53/53 means "the frozen
structural units were present", not "53 deliverables were correct". The wording
is defensible as written because the doc explains the boss row; any future
summary must not quote 53/53 without that sentence. No code change: a length gate
would require a new frozen manifest, i.e. a new campaign.

## 5. Corrected campaign numbers (re-derived, not re-measured)

Replay command (offline; reads the archived stdout only, no network):

```bash
cd <repo>
.venv/bin/python - <<'PY'
import importlib.util, json
from pathlib import Path
from collections import Counter
repo = Path(".").resolve()
spec = importlib.util.spec_from_file_location("epr", repo/"scripts/evaluate_public_resources.py")
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
mf = json.loads((repo/"docs/evidence/public-remaining-manifest.json").read_text())
cases = {c["case_id"]: c for c in mf["cases"]}
ev = json.loads((repo/"docs/evidence/public-resource.json").read_text())
scratch = Path("$TMPDIR/public-resource-campaign")
verdicts, present, declared, assessed = Counter(), 0, 0, 0
for r in ev["runs"]:
    raw = (scratch/r["case_id"]/f"{r['tool']}-{r['state']}-r{r['round']}.stdout.json").read_text()
    payload = M.read_payload(r["tool"], raw)
    case = cases[r["case_id"]]
    v = M.case_verdict(M.assess_units(case["artifact_units"], payload), payload,
                       case["pagination_expectation"])
    verdicts[v["verdict"]] += 1
    present += v["required_present"]; declared += v["required_total"]; assessed += v["required_assessed"]
print(dict(verdicts), present, assessed, declared)
PY
```

The output of this replay is retained as
`docs/evidence/public-resource-reassessment.json` (60 rows with per-row raw sha256,
published vs reassessed verdict, evaluator sha256 and the raw-set digest).

| measure | published record | fixed evaluator over the same 60 raw payloads |
|---|---|---|
| verdicts | `markers_present 19`, `incomplete 41`, `unverified 0` | `markers_present 19`, `incomplete 40`, `unverified 1` |
| rows changed | — | 1 of 60 (the `RATE_LIMITED` row: `incomplete` → `unverified`, 0/4 → 0/4 present, 0 assessed) |
| required units | 225 / 240 | 225 present, **236 assessed**, 240 declared, 4 unassessed |
| Trailhead units | 118 / 120 | 118 present of 120 assessed |
| Agent Reach units | 107 / 120 | 107 present of 116 assessed (120 declared) |

The action campaign needs no numeric correction: the published round has a
measured artifact for every inspected row, all 9 failed rows are already
`unverified`, and `whole_artifact_proven` is 0 of 3 inspected read rows. Its
numbers were re-derived from the JSON and matched the doc (§2).

## 6. Handoff list (exact doc edits, owner applies)

- **H-1** `PUBLIC-RESOURCE-EVIDENCE.md` §1: replace
  *"Frozen by | independent reviewer (subagent not an author of the harness or of
  the tools under test)"* with
  *"Frozen by | the same engineer who wrote the harness (`--frozen-by` recorded
  as 'independent reviewer' before QA-04 changed the default); reviewer
  independence is **not** established for this campaign."*
- **H-2** §4 totals and §5 bullet: `225/240` → *"225 present of 236 assessed
  (240 declared; the four required units of the one `RATE_LIMITED` run were never
  assessed and are reported `unverified` by the fixed evaluator)"*.
- **H-3** §1: date-stamp the `extract.py` disclosure ("at measurement time
  14:56–14:57 UTC, sha256 `3b09e1…`, 136 insertions") and note that the file has
  since changed (`eed08a2b…`, 282/17 at 15:26 UTC).
- **H-4** §8 reviewer note: either attach the v1-vs-v2 re-assessment output or
  downgrade "0 verdicts changed" to "engineer reported, output not retained".
- **H-5** `ACTION-ARTIFACT-EVIDENCE.md` §1: add one line that the published
  record now carries `evaluator.sha256` and that rounds 1–6 predate it, so the
  round log's "same manifest hash" is not evidence of the same evaluator.
- **H-6** §3 of the action page: keep "53/53 required units on inspected rows"
  but add "(structural units; see §5 and §9.1 — `boss read` satisfies them with a
  54-character loading page)".

Status: H-1…H-6 applied 2026-10-28 in the pages named above. The frozen manifest and
both published JSON records were not edited; the corrected reassessment is retained
as `docs/evidence/public-resource-reassessment.json` (60 rows, 1 verdict changed).
The `boss read` loading-gate defect behind QR-07's example was fixed separately at
`4ce43ce`; the action page records that as post-campaign evidence, not as a
re-measurement.

## 7. Maintenance observations (no refactor in this change)

Both scripts are large single files (1278 and 1218 lines). Concrete duplication
that will cost the next editor time:

- **Sanitising/normalising is implemented twice**, and differently:
  `evaluate_public_resources._scrub` (path + e-mail regex, hard 400-char cut) vs
  `evaluate_action_artifacts._scrub`/`_sanitize`/`_clip` (path regex then
  `reach_backend.redact_secrets`). The public harness therefore does **not** run
  secret redaction. Its published payloads are page text (the action harness
  forwards upstream items), so the risk is low today, but a third harness should
  import one helper, not copy a third variant.
- **Two verdict vocabularies that disagree on the word "complete"**: the public
  harness forbids it (`FORBIDDEN_VERDICTS`) and emits `markers_present`; the
  action harness emits `complete` for a satisfied *bounded* request. Both are
  defensible in their own scope and both are documented, but they are the same
  word with different meanings — a reader crossing pages will trip. If a shared
  module ever appears, rename the bounded one (`bounded_units_present`) rather
  than teaching the reader two definitions.
- **`read_payload` duplicates schema knowledge** that `hermes_trailhead.extract`
  and `reach_backend` already own (trailhead `content`/`pagination`, Agent Reach
  `items[].text|title|url`). A schema change in either product module silently
  turns into `absent`/`unverified` rows here. A cheap guard would be a sentinel
  test that fails when a real payload stops yielding a non-empty body, but the
  current per-run `body_chars`/`metadata_chars` already makes that visible in the
  record, so this audit does not add it.

No refactor is recommended now: the cost of churn exceeds the duplication, and
both records are already published against these exact files.

## 8. Test status

```text
tests/test_public_resources.py    30 passed   (was 26; +4 for QA-01…QA-04)
tests/test_action_artifacts.py    22 passed   (was 19; +3 for QA-05…QA-07)
tests/test_github_read_deadline.py 7 passed
whole suite                     1033 passed
```

## 9. What this audit does not establish

- It is **not** a re-measurement: no invocation was re-run, so latency, RSS,
  availability and origin behaviour are exactly the numbers already published.
- It is **not** a second reviewer's judgement of relevance, quality or
  superiority: no human read the bodies, and neither harness ranks anything.
- It does **not** repair QR-01 (the metadata-stub read) or QR-06 (the
  partial-capture discard); those are `extract.py` contract defects with their own
  regression tests (`tests/test_github_read_deadline.py`,
  `tests/test_loading_shell_regression.py` in the other lane).
- It does **not** make the public campaign independent: the manifest was frozen
  by the harness author, and the correction above is a wording fix, not a new
  review.
