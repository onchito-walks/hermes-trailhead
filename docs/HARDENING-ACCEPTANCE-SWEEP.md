# Acceptance hardening sweep — 2026-10-28

Scope: `t_d73a39b6`, implementation/QA prerequisite, **not whole-product acceptance**.
Started from `72fcc2a`; reviewed AGENTS, TEAM, SUPERIORITY-ACCEPTANCE, exact
inventory, transcription gates, routing handoff and historical acceptance runs.
No aggregate grades or winner. Historical evidence below remains tied to its
original product revision; it is not recertified by this sweep.

## Actual fixes and independent verification

1. Thin search fallback previously replaced a native result with any larger set.
   It now requires **more distinct URLs and retention of every native URL**.
   Whole-result replacement keeps upstream attribution homogeneous. An unrelated
   larger set or duplicate leads cannot displace native URLs. No new reranker,
   merge schema, dependency, option or wrapper. Tests cover all three cases.
   This preserves URLs, not necessarily richer native titles/snippets; upstream
   rows replace shared-URL rows. Exact URL equality is conservative and may retain
   a smaller native set despite a useful but different upstream set. Neither
   counts nor URL containment prove relevance. Existing public/trust/configuration,
   fixture isolation and exactly-one-fallback gates are unchanged.
2. A fresh QA agent's actual Chinese search found TikTok `/api/img/` image assets
   counted as discovery hits. Shared TikTok URL validation now rejects that path
   and descendants, preserving creator/video routes. Tavily's existing raw-result
   branch now applies the same lane validator; its regression uses a stub, not a
   paid call. Parent post-fix public CLI returned one creator URL, no image assets,
   exit 0 in 1.263 s. This is a discovery lead, **not relevant video evidence**.

Parent independently reviewed both patches and ran full suites:

- Baseline: **1130 passed in 62.47 s**, compilation passed.
- Superset increment: **1132 passed in 50.20 s**, compilation/diff-check passed.
- Asset-validator increment: **1134 passed in 59.70 s**, compilation/diff-check passed.
- Offline gauntlet passed its deterministic contracts; its 100/100 is not a live
  score or a whole-product grade.

ASR veto was unset only for fixture contract-test processes, never live calls or
configuration. No login, account import, authenticated forwarding, paid
transcription, security change, push or publication. `o.txt` was never opened,
edited, staged or removed by this task.

## Comparable live observations

Final `compare` used fresh separate tool homes, stripped credential/session/proxy
environment, ASR veto and **equal killable 20-second wall deadlines per side**.
Isolation is environment-only, **not a filesystem/process security sandbox**.
No auth cases were selected; `--include-auth` would only add unauthenticated
attempts, not authorize an account. Pinned upstream reports Agent Reach 1.6.0.

| Case | State | Trailhead ms | Agent Reach ms | Harness outcome |
|---|---|---:|---:|---|
| Python typing URL | cold | 563 | 3186 | both_evidence |
| V2EX topic | cold | 665 | 1156 | both_evidence |
| Python typing URL | immediate same-home warm | 481 | 1241 | both_evidence |
| V2EX topic | immediate same-home warm | 390 | 1001 | both_evidence |

Four paired observations / eight invocations; not a latency distribution or
completeness proof. The compare docs worker still returns its bounded 20,004-char
excerpt while native `read` supports document windows: these are not equal full-
artifact outcomes. Do not declare a speed/depth winner. Earlier search comparison
at this increment observed Trailhead 2333/7586 ms versus upstream 3204/697 ms
(first-use/reuse); this variability is not a performance conclusion either.
The initial explicitly supplied sandbox was labelled warm by the harness even
on first use; it was **not** counted as cold. Final cold omitted `--sandbox` and
its actual generated homes were reused for final warm. This immediate warm is
not a P2 delayed/multi-day reliability observation.

Sanitized final ledger: [hardening-matched-smoke.json](evidence/hardening-matched-smoke.json).
Raw final reports in Jr scratch: `t_d73a39b6-final-{cold,warm}.json`.

## Every acceptance dimension — evidence and remaining boundary

| Dimension | Exercised / reviewed evidence | Still not established |
|---|---|---|
| 1 Coverage | Fresh CLI inventory: 40 discovered capabilities, 14 channels, 26 public/12 auth/2 quota gates. Full tests exercise inventory/refusal/routing contracts. [Exact inventory](EXACT-ACTION-INVENTORY.md), historical [40-action artifacts](ACTION-ARTIFACT-EVIDENCE.md). Post-fix extra TikTok discovery smoke. | Inventory is not 40 live successes; auth and quota artifacts unrun. Historical public failures remain failures. |
| 2 Content depth | Fresh docs/forum comparison; fresh Spanish native read: document length 7195, requested window 1200, truncated true. Historical [forwarded body equality](FORWARDED-BODY-EQUALITY.md), [GitHub discussions](GITHUB-DISCUSSION-ACCEPTANCE.md); current suite covers pagination/partial capture/caps. | Full-artifact completeness across every action, unknown upstream continuation, speech/podcast content. More text is not completeness. |
| 3 Multilingual relevance | Fresh agent CLI uses frozen en/zh/es queries, three hits each: 9 leads, 5 URL-language matches, 0 docs.python.org source matches. Chinese results can lack language path markers. Preference assertions tested; no language inferred from query. | Human-adjudicated relevance, independent evidence and broad multilingual recall. A URL marker is not content-language or relevance truth. |
| 4 Reliability/freshness | Final matched public smokes and full cache/status/timeout regressions. [P2 state](PUBLIC-RELIABILITY-STATE.md) has genuine day-one cold and delayed warm only. Fresh agent wide sweep had one 25-second killed call; retry completed in 5.19 s. | Five real days, stale-source adjudication and an availability rate. Product changed since day one: future sessions must record current identity, never overwrite historical state. Existing dated schedule is not evidence of future execution. |
| 5 Speed/resources | Equal-wall-deadline compare above. Existing [per-tool resource evidence](PUBLIC-RESOURCE-EVIDENCE.md) and final run282 ledger remain revision-bound historical samples. | Comparable setup/latency/RSS/disk/API distributions on final revision. Wide native search has no aggregate deadline; outer caller budget remains necessary. This task adds no resource harness. |
| 6 Onboarding/portability | Existing [clean Linux run283](CLEAN-LINUX-RUN283.md) verifies isolated Ubuntu ARM64 userspace install/CLI, 11 narrow checks. No packaging changes in this increment. | Clean macOS/Windows and separate-machine proof; Linux run283 does not certify final changed search implementation. |
| 7 Account lifecycle | Current full suite verifies consent refusal and gates only. Management/login/switch/logout/removal excluded from adapter. No existing account inspected/imported. | User-controlled login, status, expiry, switching, logout/revocation/removal. **Specific consent is required; absent lifecycle features must not be invented or presented as passed.** |
| 8 Safety/privacy | Full suite includes shell/option injection, credential-safe errors, public route checks, process-group timeout/output bounds, separate quota/auth gates, process-wide ASR veto. New tests preserve these gates. | Environment isolation cannot prove arbitrary filesystem credentials inaccessible. No real authenticated or billable safety evaluation was authorized. |
| 9 Agent integration | New isolated QA agent actually made 13 CLI subprocess calls: help, explicit pinned inventory, Spanish native read, multilingual single-lane and wide discovery. Valid JSON/status/URLs recorded. | Not an authenticated agent workflow, human relevance review, or proof every source artifact works. |
| 10 Maintenance | Reused shared validators and fallback seam; four added regressions total, no dependency/harness/option. Full 1134 tests, compilation and diff checks. Existing [maintenance follow-up](MAINTENANCE-FOLLOWUP.md). | Existing adapter/evaluation-script size remains a cost. Registry staleness and aggregate native-search deadline remain disclosed limits; do not add another evaluator to hide them. |

Fresh-agent ledger: [hardening-agent-session.json](evidence/hardening-agent-session.json).
It records pre-asset-fix observations and base HEAD plus a worktree note; do not
reinterpret its original failed/low-value outcomes as post-fix successes.

## Handoff and specific restricted gate

This implementation phase releases the pre-created final-verification child;
completion of this card does **not** complete the whole-product root goal.
Final verification must consume current code, refresh its own required reports,
and retain all unmatched conditions above. There is no claim independent public
quality/depth work is exhausted merely because account evaluation needs consent.

For the account-lifecycle criterion specifically: Raymond must name a disposable
test account/platform and targets, then explicitly authorize which lifecycle
operations may be exercised (login/status/expiration/switch/logout/revocation/
removal). Until then that lane stays **not run**, with no credentials requested in
chat and no implicit session import. Paid transcript acceptance is a **separate**
per-target, per-call budget approval; account consent does not authorize spending.
Elapsed-time reliability, disposable macOS/Windows environments and human
relevance adjudication are separate unmet acceptance conditions, not substitute
reasons to claim the product accepted.
