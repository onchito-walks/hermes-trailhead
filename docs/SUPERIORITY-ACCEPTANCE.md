# Goal: outperform Agent Reach across the whole product

Owner request: improve Trailhead in every way, not merely claim a research niche.
Status: **in progress; overall superiority is NOT established**.

## Frozen reference

- Agent Reach 1.6.0, commit `14c213405669414492bda0f8d52cc6531d062c45`.
- Official project: https://github.com/Panniantong/Agent-Reach .
- `agent-reach channels` measured 14 channels / 40 actions on 2026-10-28.
- Trailhead's optional forwarding adapter currently allows 38 read-only actions.
  Two key/quota-consuming transcription actions are excluded by default.
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

## Current implementation and remaining work

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
