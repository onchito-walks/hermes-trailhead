# Goal: outperform Agent Reach across the whole product

Owner request: improve Trailhead in every way, not merely claim a research niche.
Status: **in progress; overall superiority is NOT established**.

Latest implementation sweep: [HARDENING-ACCEPTANCE-SWEEP.md](HARDENING-ACCEPTANCE-SWEEP.md)
records all ten dimensions, 1134 independently passing tests, real fresh-agent
multilingual CLI calls, equal-deadline cold/warm public comparisons and two
measured routing/asset-lead repairs. It supersedes older implementation/test-count
snapshots below, not historical observations or the open acceptance conditions.

Latest bounded evidence: [P5 discussion capture](GITHUB-DISCUSSION-ACCEPTANCE.md)
(2026-10-28, eight calls) verifies body hashes and all sixteen historical comment
IDs for Trailhead; both tools returned comment bodies. Marker totals are
format-dependent contract checks, not superiority scores. [P2 reliability state](PUBLIC-RELIABILITY-STATE.md)
contains the genuine day-one cold observations; no five-day result exists yet.

## Frozen reference

- Agent Reach 1.6.0, commit `14c213405669414492bda0f8d52cc6531d062c45`.
- Official project: https://github.com/Panniantong/Agent-Reach .
- `agent-reach channels` measured 14 channels / 40 actions on 2026-10-28.
- Trailhead surfaces all 40 actions: 38 read-only forwarded actions plus two
  transcription actions gated by separate auth and quota consent. ASR veto wins.
- An advertised action, a configured action, a successful fixture and repeated
  live success are different states. Never collapse them into “supported.”
- Upstream reuse is legitimate. Attribute it; do not report borrowed coverage
  as native code or imply forwarding alone beats the upstream product.

## Acceptance dimensions

Every dimension needs evidence; none is waived because Trailhead wins elsewhere.

1. **Coverage:** exercise every reference channel/action and Trailhead's extra
   TikTok lane. Record native / upstream-backed / blocked / not implemented.
   Public and authenticated variants are separate workloads.
2. **Content depth:** check requested artifacts, not response length: complete
   README, issue/PR comments, thread replies, post text, profile fields,
   subtitles, speech transcript, podcast transcript and job description.
   Record truncation, pagination and missing replies explicitly.
3. **Search quality:** use a frozen multilingual query set with expected source
   entities and human-reviewed relevance. Measure useful evidence at a fixed
   result budget; repeated promotional copies are not independent evidence.
4. **Reliability/freshness:** repeat matched live workloads at different times;
   report successes, rate limits, stale archive/cache reads and recovery. No
   universal availability claim based on HTTP 200 or an offline gauntlet.
5. **Speed/resources:** identical requested outcomes, wall-clock deadlines,
   separate cold/warm runs, comparable credentials/proxies/tool versions. Report
   setup/download time, latency distribution, peak memory, disk and API use.
6. **Onboarding/portability:** a clean Linux install, then clean macOS/Windows
   installs. Measure commands, manual interventions and time to useful result.
   A wrapper working on the development host is not clean-machine verification.
7. **Account lifecycle:** explicit user-controlled login, status, expiration,
   account switch, logout/revocation and removal. No implicit main-account
   import or security changes. Existing sessions require explicit consent.
8. **Safety/privacy:** no shell/option injection, credential leakage in output,
   accidental account reuse, hidden paid calls or credential-bearing fixtures.
   Environment isolation is NOT a filesystem/process security sandbox.
9. **Agent integration:** stable JSON/error contracts, discoverable capabilities,
   known-URL reading, single-platform actions and cross-platform sweeps. Verify
   through a new agent session, not only direct Python imports.
10. **Maintenance:** bounded dependencies/output/runtime, actionable errors,
    upstream replacement without rewrites, scoped tests and documented recovery.
    More custom code is a cost, not a competitive advantage.

## Completion rule

Do not declare “better in every way” from an aggregate score. First demonstrate
functional parity across the reference workloads, then substantiate improvements
in each dimension while identifying any regressions or unmatched conditions.
Where a dimension is qualitative, publish the criteria and reviewed artifacts.
Adoption/star counts are observed external outcomes, not something a code change
can promise. The engineering goal does not exclude broad product usability.

## Earlier baseline (superseded by the implementation checkpoint below)

Landed locally:
- Evidence usability separate from extraction transport; multilingual relevance,
  empty-profile rejection and truthful caption/audio/visual evidence fields.
- Optional upstream-backed action inventory and forwarding with attribution,
  explicit auth consent, empty public homes and forced-public-route verification.
- Public V2EX, Bilibili, Xueqiu and GitHub actions independently exercised.

Also landed locally:
- Matched-outcome comparison CLI with environment isolation, equal killable
  wall-clock budgets, cold/warm labels, ASR disabled and per-case outcomes.
  The environment isolation is not a filesystem security sandbox.
- Honest historical scorecards; exact-host classification and readable generic
  HTML extraction regressions.
- Final integrated verification: 546 tests passed. Three matched cold public
  cases returned evidence on both tools for GitHub/V2EX and blocked transcripts
  on both for YouTube; no overall superiority is established.

Still required before whole-product completion:
- Complete 40-action live parity matrix, including consented authenticated cases.
- Explicitly controlled transcription/podcast parity without automatic quota use.
- Clean-machine onboarding and account lifecycle acceptance runs.
- Repeated multilingual relevance/completeness and reliability evaluations.
- Comparable latency/resource measurements and agent-session integration tests.
- Reduce adapter/benchmark complexity where it adds no measured user value.

No task is marked complete merely because this document or a benchmark exists.

## Current implementation checkpoint — 2026-10-28

- Exact 40-action / 14-channel inventory in [ACTION-PARITY.md](ACTION-PARITY.md).
  Gates: 26 public, 12 authenticated, 2 quota. Both transcription paths now exist
  behind explicit double consent; neither has been invoked.
- Optional maintained public backend fallback now participates in normal research,
  retaining attribution in text/JSON/reports. Native known-URL `read` command has
  a stable JSON/error contract, ASR/model fallback disabled and redacted invalid URLs.
- Native extraction no longer starts key/quota-consuming ASR on its own: the
  automatic YouTube ASR fallback and the TikTok ASR tier were removed, and the two
  legacy helpers now default to refusal unless a single call passes both consent
  keywords, with `TRAILHEAD_DISABLE_ASR=1` winning even over full consent.
  [NATIVE-ASR-CONSENT.md](NATIVE-ASR-CONSENT.md) records the exact default
  behavior, the hermetic zero-effect sentinels (1145 tests) and the live public CLI
  smoke where the only media-process invocation was a caption-only `yt-dlp` call.
- Native repo-root reads fetch full public README plus labeled repo metadata;
  HTML reading retains actionable topic links. These fix measured artifact gaps,
  not merely increase response length.
- Full action sweep attempted all 26 public cases and refused 14 gated cases.
  Replay under the current normalizer: 17 returned-item rows, 6 upstream failures,
  3 withheld shell/missing-page rows. Returned items are NOT completeness/relevance
  proof. Sanitized replay ledger: [action-sweep-replay.json](evidence/action-sweep-replay.json).
- [Repeated public evidence](PUBLIC-ACCEPTANCE-EVIDENCE.md): 3 cases × 3 cold +
  3 warm rounds, 18 paired observations. English/Chinese artifact markers improved
  after fixes; presence is not full-artifact completeness or overall superiority.
- [Fresh agent CLI exercise](AGENT-SESSION-EVIDENCE.md), not just direct imports.
- [Maintenance review](MAINTENANCE-REVIEW.md): bounded live capture, POSIX process
  group cleanup, finite item limits, empty-body rejection and shell regressions.
  F7/F9/F10 are now closed by [MAINTENANCE-FOLLOWUP.md](MAINTENANCE-FOLLOWUP.md).
- [Search follow-ups](SEARCH-FOLLOWUP.md): snippet recovery (9/9 actual
  engine-returned snippets, agent-read, **no human validation**) and API-level
  ordering criteria, exposed on the CLI as `--prefer-language` / `--prefer-source`
  ([SEARCH-CLI-PREFERENCES.md](SEARCH-CLI-PREFERENCES.md)). Bounded observations
  on three queries; they do not establish relevance quality.
- Native GitHub issue/PR reads are integrated (`6100815`, `d6f5029`) and were
  independently exercised on `pallets/flask#5` and PR `#112`
  ([evidence/parent-github-artifact-verification.json](evidence/parent-github-artifact-verification.json)).
  That lane has not been walked through the frozen public manifest, so no
  acceptance result for it is recorded here; its cases must be added and run, not
  inferred from the forwarding surface.
- Parent independently verified **928 tests passing** (2026-10-28 whole-tree run:
  928 passed; run with `TRAILHEAD_DISABLE_ASR` unset — with it exported, 15
  ASR/transcription tests fail because the veto short-circuits them), compilation,
  diff-check, deterministic gauntlet (100/100) and live search/read/matched
  comparison. No pushes.

Still open: authenticated artifacts and account lifecycle (specific consent needed),
quota-backed live transcription/podcast (separate explicit budget needed), real
clean-machine macOS/Windows onboarding, human-reviewed multilingual SEARCH
relevance beyond these URL markers, multi-day reliability/freshness, comparable
per-tool runtime resource accounting beyond one window and all-artifact pagination/completeness.
Linux isolated-wheel verification is useful but is not clean-machine/cross-OS proof.
The forwarding surface borrows upstream implementation; it is not a superiority win.

Concrete, frozen procedures for the remaining work — artifact completeness,
repeated multi-day public runs, per-tool resource accounting, and the
public/consent/quota lane split — are in
[PUBLIC-REMAINING-ACCEPTANCE.md](PUBLIC-REMAINING-ACCEPTANCE.md). **Their first
executions are now recorded**: P1 (single-day artifact completeness) and P3
(per-tool resources) in [PUBLIC-RESOURCE-EVIDENCE.md](PUBLIC-RESOURCE-EVIDENCE.md)
— 60 invocations, 225 required units present of 236 assessed, corrected offline
reassessment in
[evidence/public-resource-reassessment.json](evidence/public-resource-reassessment.json)
— and the 40-action artifact campaign in
[ACTION-ARTIFACT-EVIDENCE.md](ACTION-ARTIFACT-EVIDENCE.md) (26 public actions
executed, 14 gated, whole-artifact completeness 0 of 3). The `boss read`
loading-gate false success those records disclosed was fixed at `4ce43ce`
([evidence/loading-shell-fix.json](evidence/loading-shell-fix.json)) and verified by
one live capture plus exact-body replay, not by a new campaign. Multi-day
reliability, the consent/quota lanes, and the GitHub issue/PR cases under the frozen
manifest remain unrun. None of this marks the plan complete, superior, or public
work exhausted.
