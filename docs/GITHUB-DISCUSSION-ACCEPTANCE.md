# P5 — GitHub issue/PR discussion acceptance (bounded, first execution)

Status: **one bounded P5 campaign recorded 2026-10-28T16:45Z**, 8 invocations,
`pallets/flask` issue #5 and pull request #112. No product code, harness code or
existing manifest was changed: a separate manifest was frozen and the frozen
runner consumed it unchanged. **`markers_present` here is marker presence, never
artifact completeness**, and nothing in this record ranks the two tools.

- Manifest: [`evidence/github-discussion-manifest.json`](evidence/github-discussion-manifest.json)
  — `manifest_sha256` `8167c395ec1cd508513a37f7e5a380c51e54ea4f7149dba7e835eb1212fef9b5`,
  frozen `2026-10-28T16:45:02Z`, recomputed match `true`.
- Campaign output (harness, unmodified): [`evidence/github-discussion-campaign.json`](evidence/github-discussion-campaign.json).
- Exact identifiers, counts, disclosure lines and body hashes:
  [`evidence/github-discussion-artifacts.json`](evidence/github-discussion-artifacts.json).
- Procedure: §2/§3/§5 of [PUBLIC-REMAINING-ACCEPTANCE.md](PUBLIC-REMAINING-ACCEPTANCE.md)
  (frozen manifest before the first call, one tool per invocation, 25 s killable
  process-group deadline, `TRAILHEAD_DISABLE_ASR=1`, empty sandbox homes,
  credentials refused by env allowlist).

## 1. What ran

| Item | Value |
|---|---|
| Window | `2026-10-28T16:45:05Z` → `16:45:09Z` (one window, one host) |
| Invocations | 8 planned / 8 recorded: 2 cases × 2 tools × 2 states × `--rounds 1` |
| Status | `ok: 8`, timeouts `0`, retries `0` |
| Paid / auth / quota calls | `0 / 0 / 0` (public lane, `gh` had no credentials and fell back to the public API) |
| Trailhead | commit `1ac3332`; host Linux aarch64, 4 CPU, loadavg `1.18/1.01/1.00` |
| Agent Reach | pinned `1.6.0` @ `14c21340…`, backend `github-api` after `gh → NEED_SETUP` |
| Cold / warm | cold = fresh sandbox tree, warm = second run in that same tree <1 s later — **not** the P2 30-minute gap, so this is not a reliability result |

Frozen units were taken only from evidence that existed *before* this campaign:
the `frozen_before_any_code_change` block in
[`evidence/github-artifact-depth.json`](evidence/github-artifact-depth.json) and
the independent parent reads in
[`evidence/parent-github-artifact-verification.json`](evidence/parent-github-artifact-verification.json).
They are used as expectations, not as this run's output.

Unit scope is deliberately narrow and is recorded in the manifest: the comment
units sample the comment bodies quoted in that frozen evidence (2 of 2 issue
comments, 5 of 14 PR comments). They are markers; the ID enumeration below is
the count evidence, and even that is **not** completeness.

## 2. Result

| Case | Tool | Required markers | Verdict (cold / warm) | Body chars | Comment IDs found | Capture disclosure |
|---|---|---|---|---|---|---|
| `pallets/flask#5` | trailhead | 6 / 6 | `markers_present` / `markers_present` | 714 | 2 of 2 | present |
| `pallets/flask#5` | agent_reach | 3 / 6 | `incomplete` / `incomplete` | 131 | 0 | absent |
| `pallets/flask#112` | trailhead | 11 / 11 | `markers_present` / `markers_present` | 3614 | 14 of 14 | present (+ reviews, inline) |
| `pallets/flask#112` | agent_reach | 6 / 11 | `incomplete` / `incomplete` | 2104 | 0 | absent |

Per tool over 4 invocations: trailhead 34 / 34 required markers present, agent_reach
18 / 34. **These totals are not format-neutral:** identity, state and disclosure
units match Trailhead's literal prose. A different structured field or equivalent
wording can fail those units despite supplying the information. Treat these as
Trailhead contract checks, not a fair comparative relevance/completeness score.
The independent parent checked all eight raw body hashes/counts and extracted
comment-ID lists against the sanitized ledger; all matched. Both tools actually
returned the two and fourteen comment-author blocks respectively; zero Agent
Reach IDs does **not** mean zero comment bodies. Both tools were `ok` in all four runs; the four `incomplete` verdicts are
unit and disclosure misses plus `truncation_unverified` (Agent Reach carries no
truncation field), **not** transport failures.

### 2.1 Exact identifiers observed (trailhead, identical cold and warm)

- issue #5 — `GitHub issue pallets/flask#5: Implement SQLAlchemy`,
  `State: closed | Author: justquick | Created: 2010-04-13`,
  comment ids `308703`, `308779`; body sha256 `b2191546f4d203f7e5d49ce3d42ad1677bdd63b2d71bbd4cdadf612de87c0fc7`.
- PR #112 — `GitHub pull request pallets/flask#112: JSONP`,
  `State: closed | Merged: no | ... Author: ghost`, comment ids
  `382640, 383274, 618181, 620332, 650978, 1050643, 2304151, 2308644, 3522442,
  3529766, 3535071, 4275572, 4322406, 4489650`; body sha256
  `4d537c66976b72d98ded2ea9e89408abc7c26b0e3bcdac71ec2be864eb1b0da4`.

Both hashes are byte-identical to the document hashes frozen in
`github-artifact-depth.json` **before** that change existed, in cold *and* warm:
the same document was returned four independent times, and all 16 expected
historical comment IDs are present with no extra IDs.

Disclosed pagination, verbatim:

```text
Conversation comments: captured 2 of 2 (1 page(s), per_page 100, body cap 4000 chars per item); complete for this endpoint.
Conversation comments: captured 14 of 14 (1 page(s), per_page 100, body cap 4000 chars per item); complete for this endpoint.
Reviews: captured 0 (1 page(s), per_page 100, body cap 4000 chars per item); complete for this endpoint.
Inline review comments: captured 0 of 0 (1 page(s), per_page 100, body cap 4000 chars per item); complete for this endpoint.
```

`pagination.more: false`, `next_offset: null`, `extractor_truncated: false`,
`retrieval_capped: false`, `truncated: false` on both documents, so the
continuation gate is satisfied for the `read` window — the artifact also states
in its own words that it is **not** a full issue/PR history
(`Capture note: … NOT the complete PR conversation: timeline events,
review-thread resolution, reactions, force-push history, per-commit diffs and
hidden/deleted comments are not captured.`).

### 2.2 Agent Reach, as observed

- Same `github-api` backend, one item per URL, `ok: true`, 4 / 4 runs.
- Body text is the body plus `@author: comment` blocks — **no comment IDs**, no
  capture-disclosure line, no truncation flag, no pagination field. Its
  `raw.comments` parent total (2 and 14) equals the number of author blocks it
  emitted, which is the only count evidence it gives; it never states a page
  budget or whether more exists.
- Missing required units on both cases: identity line, `State:`/`Merged:`
  metadata, the PR "not the complete conversation" scope note, and the capture
  disclosure. Those are reportable gaps in the requested artifact, and are
  reported as `absent` (a real payload was returned), never `unverified`.
- Source read of the pinned channel (no network) shows why the disclosure cannot
  appear: `github read` fetches `/issues/{n}/comments?per_page=50` once, with no
  page loop and no reviews/inline-review calls for a PR. That is a reading of
  `agent_reach/channels/github.py` at the pinned commit, not a measured failure —
  and it is why a discussion longer than 50 comments would be captured without a
  "more exists" statement.

## 3. Claims this record does and does not make

Not claimed: completeness of either artifact (marker presence only; hidden,
deleted, edited and timeline content is outside both captures); that 0 reviews
means the PR has none anywhere beyond that endpoint; a winner, speed or memory
ranking (4 runs per tool in one window, no interleaved repetition); multi-day
reliability (cold/warm here are seconds apart); authenticated or private-repo
behaviour; account lifecycle.

Claimed: on these 2 frozen cases, in this window, trailhead returned 34 / 34
required markers with an explicit capture disclosure and all 16 expected comment
IDs, and agent_reach returned 18 / 34 required markers with no comment IDs and no
capture disclosure, both `ok` at the transport level.

## 4. Harness compatibility notes (why nothing was edited)

- `scripts/evaluate_public_resources.py` builds its manifest from a fixed
  `CASE_SPECS` tuple (docs / GitHub repo README / V2EX) and `--freeze` can only
  emit those three cases. A GitHub issue/PR case therefore cannot be added
  through `--freeze` without editing the frozen script — so the manifest was
  written separately, reusing the script's own `write_manifest` / `manifest_hash`
  helpers and schema (`trailhead.public-remaining-manifest/1`).
- The campaign path is manifest-driven (`run_campaign` iterates
  `manifest["cases"]`, resolves `tool_argv`, sandbox and deadlines itself), so the
  unmodified runner executed the new manifest: `--manifest … --rounds 1
  --timeout 25`. Its `design`/`limitations` strings are fixed text from the
  3-case campaign ("3 public cases only", "V2EX node listing …", "GitHub issue/PR
  lane … not measured here"); they are **stale for this manifest** and are left
  as-is rather than patched.
- The runner always runs cold then warm, so `--rounds 1` on 2 cases costs exactly
  8 live invocations: the whole budget, no retries, no warm-up call.
- `frozen_by` records the P5 executor, not an independent reviewer — the same
  independence limitation already disclosed for the earlier campaign. The
  historical IDs used as units come from independent earlier reads, which is a
  weaker thing than an independently frozen manifest.

## 5. Reproduce

```bash
cd <repo>
git rev-parse HEAD        # 1ac3332
python3 scripts/evaluate_public_resources.py \
  --manifest docs/evidence/github-discussion-manifest.json --verify-only
export TRAILHEAD_DISABLE_ASR=1
python3 scripts/evaluate_public_resources.py \
  --manifest docs/evidence/github-discussion-manifest.json \
  --agent-reach <pinned>/bin/agent-reach \
  --scratch <scratch>/github-discussion \
  --out docs/evidence/github-discussion-campaign.json --rounds 1 --timeout 25
```

Raw stdout/stderr stay in the scratch directory; nothing outside
`docs/evidence/` and this page is part of the record.
