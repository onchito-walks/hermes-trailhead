# Public per-tool resource + artifact campaign — executed record (P1 + P3)

Status: **executed once, on one host, in one UTC window, against one frozen
manifest.** This page reports what those 60 invocations returned. It does not
mark public work exhausted, does not mark the superiority plan done, and does not
name a faster or better tool. Machine-readable record:
[`evidence/public-resource.json`](evidence/public-resource.json); corrected offline
reassessment of the same raw payloads:
[`evidence/public-resource-reassessment.json`](evidence/public-resource-reassessment.json);
frozen inputs:
[`evidence/public-remaining-manifest.json`](evidence/public-remaining-manifest.json).

Procedure it implements: [PUBLIC-REMAINING-ACCEPTANCE.md](PUBLIC-REMAINING-ACCEPTANCE.md)
§2 (frozen manifest), §3 (P1 artifact completeness), §5 (P3 per-tool resources).

## 1. Frozen inputs, recorded before the first measured run

| Item | Value |
|---|---|
| Manifest | `docs/evidence/public-remaining-manifest.json` |
| Manifest canonical `manifest_sha256` | `f92830f49ba591839cc98eddb5a1a7cbaeace57e1f9d502790532fab5f3e89ea` |
| Manifest file sha256 | `84bc20086e721d094344472771e45665533ee15eb6f8a0086d1de41126f506b9` |
| Frozen at (UTC) | `2026-10-28T14:54:37Z` |
| Frozen by | the same engineer who wrote the harness (`--frozen-by` recorded "independent reviewer" before QA-04 removed that default). Independence from the two tools under test holds; an independent review of the manifest is **not** established. |
| Cases | 3: `public-docs-python-typing`, `public-github-requests-readme`, `public-v2ex-node-python-zh` |
| Case source | the three matched cases already frozen in `scripts/evaluate_public_acceptance.py` (docs / GitHub / V2EX), argv read from `hermes_trailhead.comparative` at freeze time |
| Evaluator | `scripts/evaluate_public_resources.py`, `EVALUATOR_VERSION = 2` |
| Tree commit | `42cd70ce237183e867eda6bb54dadb732a8f2567` |
| Campaign window (UTC) | `2026-10-28T14:56:40Z` → `2026-10-28T14:57:16Z` (36 s) |
| Invocations | 60 = 3 cases × 2 tools × 2 states × 5 rounds (planned 60, completed 60) |

The manifest hash is recomputed and compared on every run; a mismatch aborts the
campaign. `--freeze` refuses to overwrite a frozen manifest, so the cases, units
and `min_distinct` values below were fixed before any output was seen. The frozen
file is left byte-identical — editing it would break `f92830f4…` and destroy the
campaign's provenance — so the corrected `Frozen by` provenance lives in this page,
not in the manifest. Its own text still reads "independent reviewer (monchobotjr
subagent; not an author of the harness or of the tools under test)"; only the
"not an author of the harness" part is wrong.

**Worktree disclosure (it was not clean).** At measurement time the tree was
`HEAD 42cd70ce` with uncommitted concurrent work from other lanes, including a
modified `hermes_trailhead/extract.py` that is in Trailhead's read path. That
digest is a snapshot taken at 14:56–14:57 UTC: 136 insertions, sha256
`3b09e1796189ca1d99b31212087239fb98026e2f91332f303ee8c2219a4e10ee`. The file then
changed at 15:26 UTC (`eed08a2b…`, 282 insertions / 17 deletions) and again in
`4ce43ce`, so it does not describe the current file. The numbers therefore
describe *that worktree*, not commit `42cd70ce` alone. §3 step 1 of the runbook
asks for a clean tree; that
condition was **not** met and is recorded here rather than glossed over.

## 2. Procedure as executed

- **One tool per invocation.** Each measured invocation ran a wrapper that starts
  exactly one child (the tool) and reports that child's
  `resource.getrusage(RUSAGE_CHILDREN)`: wall, user+sys CPU, peak RSS. No
  comparator process, no combined number.
- **Equal deadline.** A 25 s killable *process-group* deadline for both tools; the
  same `--timeout 25` is also inside each tool's own argv. Zero timeouts occurred,
  so no kill path was exercised in this campaign.
- **5 runs per case/tool/state, interleaved.** Every round ran Trailhead then
  Agent Reach inside each state (TH cold, AR cold, TH warm, AR warm), so a network
  change could not land on one side only.
- **Cold vs warm.** Each (case, tool, round) got its own empty tree; `cold` is the
  first run in it and `warm` the second run in the same tree. No tree is shared
  between rounds, and no recorded response is replayed.
- **Isolation.** Both tools ran in throwaway homes built by
  `comparative.build_sandbox` (empty `HOME`, `HERMES_HOME`, `XDG_*`, `TMPDIR`).
  `TRAILHEAD_DISABLE_ASR=1` was asserted for every child, and the child env was
  checked against an allowlist that fails closed on any credential/proxy-shaped
  key. No credential, cookie or session was supplied; paid calls 0, auth calls 0,
  quota calls 0.
- **Raw payloads kept.** Every run's stdout/stderr/rusage is in the scratch tree
  (`…/cache/scratch/public-resource-campaign/<case>/<tool>-<state>-r<round>.*`),
  capped at 4 MiB per run (no run hit the cap). Artifact assessment reads those
  bytes, never a re-typed summary.

Host (name withheld): Linux `7.0.0-1013-oracle`, aarch64, 4 CPUs, 24,547,476 kB
RAM, load average 1.04/0.92/0.91 at start, Python 3.11.15, one network moment.
Trailhead: this worktree. Agent Reach: `agent-reach` 1.6.0, installed from the
GitHub archive pinned at commit `14c213405669414492bda0f8d52cc6531d062c45`,
executable sha256 `bf25f7bd524f8aa289f502708b88366fb14733c51b7e14294f193f8f0925fae6`
(pinned venv, not a bare PATH resolve, not PyPI).

## 3. Per-tool resources (P3) — each row is one tool's own process

Medians with min–max over the 5 invocations in that row; wall includes each
tool's interpreter startup, and peak RSS includes that tool's interpreter.

### Table A — per case / tool / state

| case | tool | state | ok/attempts | wall s (median [min–max]) | CPU s (median [min–max]) | peak RSS kB (median [min–max]) | stdout B (median) |
|---|---|---|---|---|---|---|---|
| docs-python-typing | trailhead | cold | 5/5 | 0.52 [0.52–0.57] | 0.459 [0.454–0.475] | 37060 [36952–37104] | 22837 |
| docs-python-typing | trailhead | warm | 5/5 | 0.52 [0.52–0.56] | 0.457 [0.454–0.489] | 37068 [36996–37108] | 22837 |
| docs-python-typing | agent_reach | cold | 5/5 | 1.32 [1.07–1.87] | 0.221 [0.218–0.261] | 37000 [36868–37128] | 181295 |
| docs-python-typing | agent_reach | warm | 5/5 | 1.22 [1.17–1.47] | 0.228 [0.221–0.253] | 37380 [37368–37512] | 181294 |
| github-requests-readme | trailhead | cold | 5/5 | 0.22 [0.21–0.61] | 0.156 [0.150–0.160] | 29104 [28892–29104] | 5171 |
| github-requests-readme | trailhead | warm | 5/5 | 0.21 [0.21–0.22] | 0.157 [0.153–0.176] | 28976 [28956–29096] | 5171 |
| github-requests-readme | agent_reach | cold | 5/5 | 0.32 [0.32–0.37] | 0.279 [0.271–0.289] | 35592 [35464–35592] | 3791 |
| github-requests-readme | agent_reach | warm | 4/5 | 0.27 [0.27–0.32] | 0.234 [0.219–0.245] | 35528 [35188–35636] | 3834 |
| v2ex-node-python-zh | trailhead | cold | 5/5 | 0.56 [0.52–0.67] | 0.172 [0.170–0.184] | 30352 [29488–30940] | 10630 |
| v2ex-node-python-zh | trailhead | warm | 5/5 | 0.61 [0.52–0.67] | 0.176 [0.169–0.195] | 30092 [29440–30728] | 10630 |
| v2ex-node-python-zh | agent_reach | cold | 5/5 | 0.32 [0.32–0.36] | 0.222 [0.215–0.243] | 39204 [35864–39484] | 58594 |
| v2ex-node-python-zh | agent_reach | warm | 5/5 | 0.32 [0.32–0.32] | 0.224 [0.215–0.226] | 39780 [39460–40120] | 58594 |

Per-tool totals (all cases pooled, never across tools): Trailhead cold wall
median 0.52 s / RSS median 30,352 kB; Trailhead warm 0.52 s / 30,092 kB;
Agent Reach cold 0.32 s / 36,996 kB; Agent Reach warm 0.32 s / 37,380 kB.

### Table D — setup / download cost, reported separately from call cost

| environment | distributions | on-disk size |
|---|---|---|
| Trailhead `.venv` (dev venv, includes test extras) | 27 | 118.7 MB |
| Agent Reach `agent-reach-eval-venv` | 14 | 37.6 MB |

Install duration was not re-measured (both were already installed). A dev venv is
**not** a like-for-like runtime footprint, so these two sizes are not a
comparison of what a user installs to get each tool's call path.

## 4. Artifact assessment (P1) — markers, not completeness

Verdict vocabulary is `markers_present | incomplete | unverified`. A verdict of
`markers_present` means *every required marker was found in that run, truncation
was explicitly reported false, and the continuation was known to be exhausted (or
the case declares none)*. It is an observation about markers on that run. **No run
in this campaign is reported as a complete artifact**; the word is not part of the
vocabulary and `completeness_claim` is `none` in every row.

### Table B — required units over the 5 cold + 5 warm runs

| case | tool | required units present / declared | verdicts (10 runs) |
|---|---|---|---|
| docs-python-typing | trailhead | 50/50 | incomplete 10 |
| docs-python-typing | agent_reach | 50/50 | incomplete 10 |
| github-requests-readme | trailhead | 38/40 | markers_present 9, incomplete 1 |
| github-requests-readme | agent_reach | 27/40 | incomplete 10 |
| v2ex-node-python-zh | trailhead | 30/30 | markers_present 10 |
| v2ex-node-python-zh | agent_reach | 30/30 | incomplete 10 |

Totals **as published** by evaluator v2 before the QA fixes: 60 invocations,
19 `markers_present`, 41 `incomplete`, 0 `unverified`; required-unit presence
225/240. The corrected offline reassessment of the same 60 archived payloads
([`public-resource-reassessment.json`](evidence/public-resource-reassessment.json),
same raw bytes, current evaluator, no invocation) gives 19 `markers_present`,
40 `incomplete`, 1 `unverified`, and **225 required units present of 236 assessed
(240 declared; 4 unassessed)**, required units only — optional units are not in
this count. The four unassessed units belong to the `RATE_LIMITED` run in Table C,
which no one ever judged: 225 was right, `240` was the wrong denominator. No
measured row was re-run or rewritten.

Why the gates fired where they did:

- **docs (both tools, 10/10 each): `incomplete`.** All five required entries were
  present in all 10 runs, but Trailhead reported 120,318 characters available and
  returned a 20,000-character window with `truncated: true` and
  `pagination.more: true`, so a whole-artifact unit was truncated and the
  continuation was not exhausted. Agent Reach returned 176,426 characters (a
  different extractor, so not the same document length) in a single payload that
  carries no truncation flag at all, so truncation stays *unverified* rather than
  assumed false. Markers present did not upgrade either side.
- **github (Agent Reach, 10/10 `incomplete`):** `readme_intro` ("A simple, yet
  elegant, HTTP library") and the license marker were absent from the `text` of all
  10 runs — its README payload is 2,894 characters and does not carry that opening
  line or a license sentence. The install command and one usage call were present,
  and the repository identity matched in the structured `title` field, not in body
  text.
- **v2ex (Agent Reach, 10/10 `incomplete`):** all required markers were found, but
  the 10 topic URLs live in the structured `url` fields (`region:
  metadata_field`), the payload declares no truncation, and a node listing is a
  first page with no continuation state — so it cannot be recorded as exhausted.
- **v2ex (Trailhead, 10/10 `markers_present`):** node identity, ≥3 distinct Chinese
  titles and ≥3 distinct topic URLs in body text, `truncated: false`,
  `pagination.more: false`.

### Table C — non-`ok` and anomalous runs

- `public-github-requests-readme` / trailhead / warm r5: body only 215 characters —
  the run returned the repository metadata summary ("GitHub repository: psf/requests
  … License: Apache License 2.0") with `extraction_status: ok`,
  `truncated: false` and pagination exhausted, but no README body text. The
  required install/usage units were absent, so the verdict was `incomplete`. This
  is the case where a "not truncated" flag alone would have been misleading; the
  unit check caught it.
- `public-github-requests-readme` / agent_reach / warm r5: exit 1,
  `RATE_LIMITED` — "GitHub API rate limit (60/hour without a token)" after the
  campaign's 10th GitHub read. Recorded as a failed attempt, not repaired,
  interpolated or retried inside this campaign.

No timeouts, no `blocked`, no `auth_required`, no `missing_page` in this window.

## 5. What these numbers do and do not support

- They are **per tool**: each row was measured in its own process by a wrapper that
  started exactly one child, so Trailhead's CPU/RSS and Agent Reach's CPU/RSS are
  separate quantities. No combined-tool RSS exists in this record and none is
  claimed.
- They are **one host, one 36-second window, three cases**. A reader may compare
  two rows to see what happened here; nothing in this record ranks the tools, and
  `claims.winner` is `none`.
- Wall clock is dominated by network for one side and by work for the other on
  these particular cases, so the wall medians are not a "speed" result. The table
  exists so the denominators and spread are visible (median plus min–max, five
  runs, cold and warm separately).
- Marker presence counts are not completeness rates. 225 of 236 assessed required
  markers (240 declared; §4) is not a completeness percentage; 19 of 60 runs
  reached `markers_present`, which is a gated observation about markers, not an
  artifact certificate.
- Cold/warm here means a fresh sandbox tree versus a second run in the same tree.
  Origin/CDN caches, and each backend's own caching, are not controlled.

## 6. Not measured by this campaign

- **P2 multi-day reliability** — no second day, no 5-day window, no ≥30-minute
  warm gap. Every number above is from one 36-second window.
- Consent (`gate: consent`, 12 actions) and quota (`gate: quota`: `youtube
  transcribe`, `xiaoyuzhou transcribe`) lanes — not run, zero quota spent.
- The GitHub **issue/PR** lane (P5) — no manifest case for it here; `agent-reach
  github read` forwarding is `native-partial` and says nothing about comment
  coverage.
- Account lifecycle (login/status/expiry/logout) — out of scope, no credentials.
- The other public actions (only these 3 of the public surface are exercised).
- Human-reviewed relevance, and any claim that a tool is better, faster, cheaper
  or complete.

## 7. Reproduce

```bash
cd <repo>
git rev-parse HEAD                       # 42cd70ce… ; worktree must be clean for a
                                         # like-for-like re-run of §1's disclosure

# frozen manifest — verify (do not re-freeze inside an existing campaign)
.venv/bin/python scripts/evaluate_public_resources.py --verify-only

# campaign (60 invocations; ~35 s observed, 25 min worst case at the deadline)
export TRAILHEAD_DISABLE_ASR=1
.venv/bin/python scripts/evaluate_public_resources.py \
  --manifest docs/evidence/public-remaining-manifest.json \
  --agent-reach "$TMPDIR/agent-reach-eval-venv/bin/agent-reach" \
  --scratch "$TMPDIR/public-resource-campaign" \
  --out docs/evidence/public-resource.json \
  --rounds 5 --timeout 25

.venv/bin/python -m pytest tests/test_public_resources.py -q
```

## 8. Reviewer notes

- **Evaluator change after the first run.** After the first campaign
  (`…/scratch/public-resource-campaign-run1`, same manifest hash, archived and
  **not pooled** with the published numbers) the evaluator was raised from v1 to
  v2 so that `regex_distinct` units search metadata as well as body and record
  `region: metadata_field`. Reason: Agent Reach returns V2EX topic links in the
  structured `url` field, and v1 recorded those units `absent`, which mis-described
  what was returned. The archived 60 payloads were re-assessed offline under both
  versions: **0 verdicts changed** — engineer-reported; that comparison's output was
  not retained, so it is not independently checkable. The only unit-state change
  was Agent Reach's `topic_urls` (`absent` → `present`, region `metadata_field`) in
  all 10 runs, which stays `incomplete` because of the unknown
  truncation/continuation. The published table is from the second campaign,
  measured under v2. A retained reassessment does exist for the later QA fixes of
  §4: the same 60 payloads re-judged by the corrected evaluator change exactly 1
  verdict (`incomplete` → `unverified` on the `RATE_LIMITED` row) and 0 marker
  units.
- The published JSON contains no absolute path, hostname or user name; the raw
  payloads stay in scratch and are not committed.
- **Frozen expectation that proved too strong.** The docs case was frozen with
  `pagination_expectation.continuation: "none"`, but the page is larger than
  Trailhead's 20,000-character read window, so continuation was in fact
  `pending`. The manifest was not edited after the run (that would be a new
  campaign); the truncation gate caught the same defect independently
  (`truncated: true` on a `whole_artifact` unit). A future manifest for this case
  should freeze `continuation: "cursor"`.
- Nothing here is committed: these four paths are new files in the worktree
  (`scripts/evaluate_public_resources.py`, `tests/test_public_resources.py`,
  `docs/PUBLIC-RESOURCE-EVIDENCE.md`, `docs/evidence/public-resource.json` plus the
  frozen manifest) and the shared files were left untouched.
