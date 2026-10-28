# Action artifact evidence — 40 pinned actions, public lane

**Status: one harness, one host, seven completed rounds between 14:57 and 15:13 UTC on
2026-10-28; the published record is round 7. Nothing here is a superiority,
completeness, reliability or authenticated-parity claim.** The point of the campaign is
narrower: for each of the 40 pinned actions, record whether an artifact was produced
and what the artifact actually contained, instead of counting returned items.

Machine-readable record: [`evidence/action-artifacts-live.json`](evidence/action-artifacts-live.json).
Harness: [`scripts/evaluate_action_artifacts.py`](../scripts/evaluate_action_artifacts.py).
Contract tests: [`tests/test_action_artifacts.py`](../tests/test_action_artifacts.py) (22 tests, no network).

## 1. What was frozen, and when

The manifest was written to scratch **before the first call** of every round, and its
hash is identical in all seven rounds:

| field | value |
| --- | --- |
| manifest sha256 | `19cf1ba40334f017b8c851a5f6e266b94cdb88c67ec1e0dc42d055ebec279144` |
| frozen rows | 40 (14 channels) |
| frozen before calls | true |
| requested limit | 2 items per action |
| reference | Panniantong/Agent-Reach `1.6.0`, commit `14c213405669414492bda0f8d52cc6531d062c45` (pinned) |

The harness now writes an `evaluator` block (script path, script sha256, manifest
version) at the top level of the summary, **outside** the frozen manifest. This
published round and rounds 1–6 predate that field, so no record in this campaign
identifies the code that judged it: the shared manifest hash `19cf1ba4…` is
evidence of the same input, not of the same evaluator.

Each row's `requested_outcome` is a paraphrase of the pinned registry's own help text
for that action (`agent-reach channels`), and its units are structural:

- `items_min` / `item_field_all` — the listing exists and every returned row has an
  identity and a URL (metadata region);
- `body_text` — at least one item carries non-empty body text (body region);
- `no_shell_marker` — the first 400 characters of body text do not match a frozen,
  multilingual error/anti-bot/empty-shell marker list (body region);
- `target_match` — the returned URL is the frozen target (metadata region);
- `raw_fields` / `raw_fields_any` — structured `raw` fields exist (structured-field
  region).

No unit is a character count, a keyword list harvested from a first response, or a
returned-item count. `whole_artifact: true` marks read-type actions whose help text
promises the whole thing (README, subtitle, topic + replies, job description, page
text, transcript); for those the verdict can never be `complete` unless the
end/continuation is known to be exhausted — which this payload never reports.

Targets are the **same real targets as the prior action-sweep raw record**
(`trailhead-40-action-live.json`, 2026-10-28T12:31Z), reused verbatim so a failure this
round is comparable to that record. Detail-read targets are marked with the
search/listing they came from. No target was invented.

## 2. Conditions

| condition | value |
| --- | --- |
| auth consent | `false` — 12 consent actions `gated_not_run`, no authenticated call issued |
| quota consent | `false` — 2 quota actions `gated_not_run`, no quota-consuming call issued |
| `TRAILHEAD_DISABLE_ASR` | `true` (zero ASR calls) |
| upstream HOME | isolated empty throwaway HOME, redirected XDG/APPDATA (26/26 public rows `home_mode: isolated-temp`) |
| routes | forced public routes: 16 `public_api` + 10 `public_web` of 26 public rows |
| per-action wall deadline | 20.0 s |
| whole-run wall deadline | 720.0 s (never reached) |
| concurrency | 2 workers |
| sandbox | none — environment isolation only, not a filesystem/process sandbox |
| run window (published round) | 2026-10-28T15:13:33Z → 2026-10-28T15:13:52Z |
| host | Linux-7.0.0-1013-oracle-aarch64-with-glibc2.43, 4 CPUs, Python 3.11.15 |
| tree | HEAD `42cd70ce237183e867eda6bb54dadb732a8f2567`; `reach_backend.py` unmodified; `extract.py` carried an uncommitted concurrent GitHub-read-deadline change (not exercised by this forwarding path) |

## 3. Ledger (published round, programmatic)

| dimension | count |
| --- | --- |
| channels / actions | 14 / 40 |
| public actions executed | 26 of 26 |
| auth-gated (`consent`) | 12 — all `gated_not_run` |
| quota-gated | 2 — all `gated_not_run` |
| rows with an artifact to inspect | 17 |
| rows with no artifact (upstream/harness error) | 9 |
| rows stopped by the wall deadline | 0 |
| artifact verdicts | complete 14, incomplete 3, unverified 9, not_run 14 |
| required units on inspected rows | 53 present / 53 required |
| artifact kinds | body 15, metadata-only 2, none 23 |
| whole-artifact rows inspected | 3 |
| whole-artifact completeness proven | **0** |

`complete` here means "every required unit of the *bounded* request was present" for a
listing or metadata row. It never means "the whole artifact". Structural completeness
is not artifact completeness: `53 present / 53 required` counts the frozen structural
units (items exist, each item has identity + URL, *some* non-empty body, no shell
marker), so it is not "53 correct deliverables" and not an artifact certificate —
`boss read` satisfies every one of its units with a 54-character loading page (§5,
§9.1). Whole-artifact completeness was proven for **0 of 3** inspected read-type rows.

## 4. Per-action ledger (published round)

`items` is the forwarded item count and is recorded only as context; `body` is the
longest item body in characters; `trunc` counts items whose text was clipped by
Trailhead's 4000-character bound (the `text_truncated` flag the forwarding layer sets).

| action | gate | status | verdict | items | body | trunc | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `github search` | public | inspected | complete | 2 | 61 | 0 |  |
| `github read` | public | failed | unverified | 0 | 0 | 0 | RATE_LIMITED |
| `twitter search` | public | failed | unverified | 0 | 0 | 0 | UPSTREAM_BROKEN |
| `twitter profile` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `twitter tweets` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `twitter thread` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `youtube read` | public | failed | unverified | 0 | 0 | 0 | PLATFORM_BLOCKED |
| `youtube search` | public | inspected | complete | 2 | 125 | 0 |  |
| `youtube subtitle` | public | failed | unverified | 0 | 0 | 0 | PLATFORM_BLOCKED |
| `youtube transcribe` | quota | gated_not_run | not_run | 0 | 0 | 0 | asr_disabled |
| `reddit search` | public | inspected | complete | 2 | 999 | 0 |  |
| `reddit read` | public | failed | unverified | 0 | 0 | 0 | content_unusable ({"withheld_items": 1, "reasons": ["blocked"]}) |
| `reddit subreddit` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `facebook search` | public | inspected | complete | 2 | 223 | 0 |  |
| `facebook profile` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `instagram search` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `instagram profile` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `instagram posts` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `bilibili search` | public | failed | unverified | 0 | 0 | 0 | NEED_SETUP |
| `bilibili read` | public | failed | unverified | 0 | 0 | 0 | UPSTREAM_BROKEN |
| `bilibili hot` | public | inspected | complete | 2 | 61 | 0 |  |
| `bilibili subtitle` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `xiaohongshu search` | public | inspected | complete | 2 | 920 | 0 |  |
| `xiaohongshu read` | public | failed | unverified | 0 | 0 | 0 | content_unusable ({"withheld_items": 1, "reasons": ["missing_page"]}) |
| `xiaohongshu comments` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `linkedin jobs` | public | inspected | complete | 2 | 2555 | 0 |  |
| `linkedin read` | public | failed | unverified | 0 | 0 | 0 | UPSTREAM_BROKEN |
| `boss search` | public | inspected | complete | 1 | 79 | 0 |  |
| `boss read` | public | inspected | incomplete | 1 | 54 | 0 | end_of_artifact_not_proven |
| `v2ex hot` | public | inspected | complete | 2 | 557 | 0 |  |
| `v2ex node` | public | inspected | complete | 2 | 512 | 0 |  |
| `v2ex read` | public | inspected | incomplete | 1 | 4000 | 1 | artifact_truncated_at_output_bound |
| `v2ex user` | public | inspected | complete | 1 | 0 | 0 | metadata-only artifact |
| `xueqiu quote` | public | inspected | complete | 1 | 21 | 0 |  |
| `xueqiu search` | public | inspected | complete | 1 | 0 | 0 | metadata-only artifact |
| `xueqiu hot_posts` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `xueqiu hot_stocks` | consent | gated_not_run | not_run | 0 | 0 | 0 | auth_required |
| `xiaoyuzhou transcribe` | quota | gated_not_run | not_run | 0 | 0 | 0 | asr_disabled |
| `web search` | public | inspected | complete | 2 | 2779 | 0 |  |
| `web read` | public | inspected | incomplete | 1 | 3312 | 0 | end_of_artifact_not_proven |

## 5. What the artifacts actually were

**Bounded listing and metadata rows (14 `complete`).** The search/listing rows
returned the requested identity + URL pairs with non-empty snippets — `reddit search`
(999 chars), `web search` (2779), `linkedin jobs` (2555), `xiaohongshu search` (920),
`youtube search` (125), `facebook search` (223), `boss search` (79) and `github search`
(61). `v2ex hot` / `v2ex node` returned topic rows with bodies (557 and 512 chars), and
`bilibili hot` carried 2 video ids and URLs with a 61-character snippet.
Structured rows carried their `raw` fields: `xueqiu quote` returned the quote string
`贵州茅台 1330.75 (-1.85%)` plus `symbol`/`current`/`time`; `xueqiu search` returned
`symbol`+`name` with no body (a stock lookup, which is what the action's help says it
is — not a post search); `v2ex user` returned `username` plus
`bio`/`tagline`/`location`/`website`.

**Whole-artifact reads (3 inspected, 0 proven).**

| action | what came back | why it is not complete |
| --- | --- | --- |
| `boss read` | 54 chars, sha256 `f7dba9e2db1ed96f…`: `B O S S  正在加载中...  © copyright BOSS直聘 京ICP备14013441号-5` | not the job description at all — a loading/challenge interstitial returned as `ok: true` with one item |
| `v2ex read` | topic body, 4000 chars, sha256 `e8a687aaa49d1b54…` | clipped at Trailhead's 4000-char bound (`trunc=1`); the reply set the action promises is never reached |
| `web read` | 3312 chars of the asyncio page, sha256 `3828fca9e4da0ca7…` | forwarding carries no continuation/end-of-page state, so the page end is unknown (`dynamic_or_collapsed_sections_not_inspected`) |

`github read` failed this round with `RATE_LIMITED`. In rounds 2 and 6 of the same
campaign it did return the README, clipped at 4000 chars with `text_truncated: true`;
that is the same `MAX_TEXT_CHARS` bound seen on `v2ex read`, not a different finding.

**Rows with no artifact (9).** These are preserved errors, not absences:
`github read` `RATE_LIMITED` ("GitHub API rate limit (60/hour without a token)"),
`twitter search` `UPSTREAM_BROKEN` ("Public web returned no usable content in the
requested scope"), `youtube read` and `youtube subtitle` `PLATFORM_BLOCKED`
("Sign in to confirm you're not a bot"), `reddit read` `content_unusable` (1 withheld
item, reason `blocked`), `bilibili search` `NEED_SETUP` ("bili is not installed"),
`bilibili read` `UPSTREAM_BROKEN` (HTTP 412), `xiaohongshu read` `content_unusable`
(1 withheld item, reason `missing_page`), `linkedin read` `UPSTREAM_BROKEN`
(HTTP 403).

For the two `content_unusable` rows the product withheld the body before forwarding, so
no artifact existed to evaluate — their units are `unverified`, not "absent". The prior
12:31Z raw record had forwarded a 342-character blocked Reddit body and a 112-character
"页面不见了" Xiaohongshu body as `returned_items`; this run did not. The behavior
differs between the two records; the cause was not investigated here.

## 6. Gates: 12 auth + 2 quota, zero spawns, zero spend

Every gated row was exercised with a spy runner that would return a payload if an
action process were ever started, and the backend was given the already-validated
registry so the probe cannot spend a discovery subprocess:

| result | rows |
| --- | --- |
| `auth_required`, `runner_calls: 0`, no action argv | 12 consent actions |
| `asr_disabled`, `runner_calls: 0`, no action argv | 2 quota actions (`youtube transcribe`, `xiaoyuzhou transcribe`) |

`gated_rows_refused_without_action_process = 14` of 14. The harness reads no account,
cookie, session or token anywhere, and the child environment it builds receives no
credential variable. Quota spend: zero.

## 7. Round log — the same frozen manifest, seven rounds

All rounds share manifest `19cf1ba40334f017…`. No round is discarded or pooled; the
published record is the last one, chosen by protocol (last of the campaign), not by
outcome. Each round's full record is kept next to the frozen manifest in the scratch
directory as `evidence-runN-superseded.json` (rounds 1–6); only round 7 is published.

| round | UTC window | inspected | failed | units present/required (inspected) | complete/incomplete/unverified | failure codes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 14:57:45–14:58:09 | 18 | 8 | 58/58 | 18/0/8 | NEED_SETUP 1; PLATFORM_BLOCKED 2; UPSTREAM_BROKEN 3; content_unusable 2 |
| 2 | 14:58:53–14:59:13 | 18 | 8 | 58/58 | 14/4/8 | NEED_SETUP 1; PLATFORM_BLOCKED 2; UPSTREAM_BROKEN 3; content_unusable 2 |
| 3 | 15:00:47–15:01:11 | 11 | 15 | 33/33 | 9/2/15 | NEED_SETUP 1; PLATFORM_BLOCKED 2; RATE_LIMITED 1; TIMEOUT 1; UPSTREAM_BROKEN 8; content_unusable 2 |
| 4 | 15:06:34–15:06:58 | 17 | 9 | 53/53 | 14/3/9 | NEED_SETUP 1; PLATFORM_BLOCKED 2; RATE_LIMITED 1; UPSTREAM_BROKEN 3; content_unusable 2 |
| 5 | 15:11:06–15:11:25 | 17 | 9 | 53/53 | 14/3/9 | NEED_SETUP 1; PLATFORM_BLOCKED 2; RATE_LIMITED 1; UPSTREAM_BROKEN 3; content_unusable 2 |
| 6 | 15:11:48–15:12:06 | 18 | 8 | 58/58 | 14/4/8 | NEED_SETUP 1; PLATFORM_BLOCKED 2; UPSTREAM_BROKEN 3; content_unusable 2 |
| 7 | 15:13:33–15:13:52 | 17 | 9 | 53/53 | 14/3/9 | NEED_SETUP 1; PLATFORM_BLOCKED 2; RATE_LIMITED 1; UPSTREAM_BROKEN 3; content_unusable 2 |

Round 1's verdicts were computed before the harness copied `whole_artifact` into the
row, so it reported read rows as `complete`; that harness defect was fixed before
round 2 and the manifest was not touched (same sha). Round 3 hit a degraded public-web
moment: all five Exa-based searches returned "Exa returned no recognizable search
results", `github read` hit `RATE_LIMITED`, and `v2ex read` timed out. Round 7
recovered the Exa rows without any code or manifest change. **Seven rounds minutes
apart on one host are a variance observation, not a success rate and not reliability.**

## 8. What this does not establish

- Whole-artifact completeness of any read: 0 of 3 inspected read-type rows could be shown complete.
- Comment/reply/transcript completeness anywhere: no continuation state is forwarded, so no set is known to be exhausted.
- Authenticated parity: the 12 consent actions were not run; only their gate was verified.
- Quota/transcription behavior: the 2 quota actions were not run; zero spend, no transcript.
- Reliability, freshness, latency or resource parity: seven rounds, one host, one afternoon.
- Content quality or relevance of any body (no human adjudication).
- That Trailhead beats Agent Reach on anything: no cross-tool comparison was run here, and 28 of the 40 actions are Agent Reach's own code forwarded.

## 9. Observed issues (status at the published round; later fixes noted)

1. **`boss read` accepts a loading/challenge interstitial as a successful read.**
   Target `https://www.zhipin.com/job_detail/c1039e39ba83b73e0nd639i_FFJR.html?_security_check=1_1783322651289`.
   Result: `ok: true`, 1 item, title `请稍候 - BOSS直聘`, body (verbatim, 54 chars)
   `B O S S` / `正在加载中...` / `© copyright BOSS直聘 京ICP备14013441号-5`
   (sha256 `f7dba9e2db1ed96f187a40e79a57f26050c2736304bc2c31155bd4fb8286ace4`,
   identical in rounds 4–7), with `raw.completeness_verified: false` and a plausible
   `published_at`, so nothing in the item shape flags it.
   `extract.classify_page_shell` (used by `reach_backend._normalize_items`) does not
   classify this as a shell, so no `content_unusable` guard fires and the caller gets no
   job description. Repro: public-mode
   `AgentReachBackend(exe, timeout=20).execute("boss", "read", {"target": url})`;
   the artifact body is the loading page above.

   **Status after the campaign (`4ce43ce`).** The paragraph above is the historical
   round-7 result and is not edited. `extract.classify_page_shell` now reports
   `blocked` for this body: the exact recorded 54-character body (multiline sha256
   `f7dba9e2…`) classifies as a gate and `_is_usable_page_text` is false. Replaying
   the one live reader capture from the recheck (`f23b7084…`, sha256 matched to that
   read's own `document_sha256`), a native `read` now returns `status: blocked` with
   an explicit access-gate error instead of a readable 435-character document, and
   the real `AgentReachBackend` — given the pinned envelope (ok, 1 item, this exact
   body and title) by an injected runner — returns `ok: false`, `content_unusable`,
   reasons `["blocked"]`, 0 forwarded items. That is one live public read plus
   exact-body replay, **not** a re-run of this campaign: the Agent Reach executable
   was not on `reach_backend`'s discovery path on this host, so the forwarding path
   was not exercised live, and no number in §3/§4/§7 is re-measured or changed. The
   fix makes the failure honest; it does not obtain the job description. Evidence:
   [`evidence/loading-shell-fix.json`](evidence/loading-shell-fix.json),
   `tests/test_loading_shell_regression.py` (32 tests, 1037 repo-wide).
2. **`v2ex read` (and `github read` when it succeeds) is clipped at
   `MAX_TEXT_CHARS = 4000`** with `text_truncated: true`, so a topic's replies and a
   README's tail are unreachable through this path. The flag is honest; the artifact is
   partial by construction.
3. **Public-web search availability is unstable minute-to-minute.** Round 3 returned
   `UPSTREAM_BROKEN` ("Exa returned no recognizable search results") for all five
   Exa-based searches; rounds 2, 4, 6 and 7 succeeded. No product change was made; this
   is an upstream availability observation.
4. **`github read` hit `RATE_LIMITED`** ("GitHub API rate limit (60/hour without a
   token)") in rounds 4, 5 and 7; repeated rounds consume the anonymous budget.
5. **Platform gates, not code defects:** `youtube read`/`subtitle` (`PLATFORM_BLOCKED`,
   bot check), `bilibili search` (`NEED_SETUP`, `bili` not installed), `bilibili read`
   (HTTP 412), `linkedin read` (HTTP 403), `reddit read` (blocked body),
   `xiaohongshu read` (missing page). Recorded with the upstream code, message and
   attempt ladder; no retry loop was run.

## 10. Reproduce

```bash
cd <repo>
git rev-parse HEAD                       # 42cd70ce237183e867eda6bb54dadb732a8f2567
export TRAILHEAD_DISABLE_ASR=1           # no media/paid path in a public campaign
.venv/bin/python -m pytest tests/test_action_artifacts.py -q   # 22 passed, no network

# pinned Agent Reach 1.6.0 from its own dist-info (version + direct_url commit)
.venv/bin/python scripts/evaluate_action_artifacts.py \
  --agent-reach "$TMPDIR/agent-reach-eval-venv/bin/agent-reach" \
  --scratch "$TMPDIR/action-artifacts-live" \
  --out docs/evidence/action-artifacts-live.json \
  --timeout 20 --deadline 720 --workers 2
```

`--freeze-only` writes the frozen manifest and exits without any call. Raw payloads
(each action's full forwarded result) stay in the scratch directory; the published JSON
carries sanitized previews, body digests, unit evidence and error records only.
