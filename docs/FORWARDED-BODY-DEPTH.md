# Forwarded body depth — bounded full-body preservation

Scope: `hermes_trailhead/reach_backend.py` (`_normalize_items`, new
`MAX_TOTAL_BODY_CHARS`, `_upstream_signals`). No new connector, wrapper,
transport, credential path, session, cursor follower or pagination abstraction
was added: the maintained upstream `agent-reach` still produces the body, and
Trailhead now forwards what it already received instead of cutting it at 4000
characters.

## The defect this closes

`_normalize_items` clipped **every** item's `text` to `MAX_TEXT_CHARS = 4000`.
For discovery that is correct — a snippet is a lead. For `BODY_READ_ACTIONS`
(`read`, `thread`, `comments`) the text *is* the artifact the caller asked for,
so the result was partial by construction: `docs/ACTION-ARTIFACT-EVIDENCE.md` §5
recorded `v2ex read` at exactly 4000 chars with `text_truncated: true`, the reply
set never reached, and §9.2 named the same bound for `github read`. Optional
pagination on the CLI would not have helped: there was nothing further to page
through, because the tail had already been discarded.

## Contract

| Bound | Value | Applies to |
|---|---|---|
| `MAX_TEXT_CHARS` | 4 000 | discovery/metadata `text` only (`search`, `jobs`, `hot`, `quote`, …) |
| `MAX_TOTAL_BODY_CHARS` | 250 000 chars | **shared across all items** of one `read`/`thread`/`comments` result |
| `MAX_OUTPUT_BYTES` | 4 000 000 bytes | unchanged: the default runner still stops the producer at this many bytes of stdout |

`MAX_TOTAL_BODY_CHARS = MAX_OUTPUT_BYTES // 16`. The division is not arbitrary:
the budget must not let re-serialisation smuggle past the capture cap that the
runner already enforces. The expensive JSON form is `ensure_ascii=True`, where a
non-BMP codepoint (any emoji) becomes a surrogate pair — `\ud83d\ude42`, **12
bytes per character** — not the 6 bytes of a control character and not the 4
bytes of its UTF-8 form. At `// 16`, 250 000 forwarded body characters cost at
most 3 MB, leaving ~1 MB of the cap for per-item metadata, which carries its own
character bounds (`MAX_VALUE_CHARS` titles/authors/dates, `MAX_URL_CHARS` URLs,
`raw` ≤ 2000 encoded chars).

This is a **forwarding bound, not an envelope-size guarantee**. An envelope whose
50 items all carry maximum-length non-BMP metadata *and* a full non-BMP body can
still exceed 4 MB under `ensure_ascii=True`; metadata is char-bounded per field,
not byte-accounted. What is guaranteed is the part this change controls: the
body alone cannot cost more than 3 MB, and no capture larger than the existing
4 MB stdout cap was added.

Allocation is first-come, in upstream item order. A body that fits is preserved
whole. When the shared budget runs out mid-body, the cut is local and flagged.
When it is already spent, later items are withheld with reason
`body_budget_exhausted` and a limitation line — never forwarded as an "empty
read" and never mislabelled `empty_body`.

## Per-item metadata

Body-read items gain one explicit object (discovery items keep their exact
previous shape):

```json
"body": {
  "upstream_chars": 7956,
  "returned_chars": 7956,
  "local_truncated": false,
  "upstream_truncated": null,
  "upstream_complete": null
}
```

- `upstream_chars` — characters upstream actually returned for this item (what
  arrived over the pipe, not what the page holds).
- `returned_chars` — characters forwarded to the caller.
- `local_truncated` — true only when Trailhead's own budget cut this body.
- `upstream_truncated` — repeats an envelope-level boolean when one is present,
  else `null` (unknown). It is never inferred.
- `upstream_complete` — **always `null`** here. Completeness is unknown: no
  end-of-artifact signal is validated on this path, and "Trailhead clipped
  nothing" is not evidence that the upstream string was the whole artifact.
  Nothing in this change upgrades a read to a completeness claim.

## Upstream continuation/truncation signals

`result.upstream` (only on body reads; `null` elsewhere):

```json
{
  "truncated": null,
  "continuation": {"state": "unknown", "source": "absent", "next_offset": null},
  "note": "Pinned Agent Reach 1.6.0 (schema_version 1) carries no continuation, truncation or page-cursor field. Continuation is therefore unknown, not complete, and there is no cursor to follow."
}
```

The field mapping was checked against the pinned upstream before it was written,
not guessed: `agent_reach/runtime/result.py` at 1.6.0 / commit `14c2134` builds
exactly `{schema_version, ok, channel, action, backend, items, meta, error}` with
`meta = {elapsed_ms, attempts}`, and `make_item` produces exactly
`title/url/author/published_at/text/raw`. There is **no** upstream truncation or
continuation field on this pin.

An earlier draft of this change also probed guessed `pagination` /
`meta.pagination` shapes. That was removed: the pinned envelope has neither, and
reading them meant a `more: false` (or a zero-valued cursor) could be reported as
`"exhausted"` — a completeness-adjacent claim built on a field upstream never
sent. The contract is now the pinned one:

- `continuation.state` is always `"unknown"` with `source: "absent"`;
  `next_offset` is always `null`. No cursor is parsed, echoed or followed, so a
  malformed or ambiguous cursor cannot be mistaken for an exhausted set.
- `truncated` is echoed **only** when the envelope really carries a top-level
  bool; otherwise it is `null` (unknown).

## Shell classification

`classify_page_shell` now receives the **entire** upstream body instead of a
4000-char slice. A shell is a short page (`_BLOCKED_SHELL_MAX_CHARS = 2000`,
`_SHELL_MAX_CHARS = 800`, loading-interstitial window ≤ 400), so length is the
evidence that keeps real prose out of the `blocked` / `missing_page` verdicts.
Classifying a truncated prefix threw that evidence away; the whole-body call
restores it, and a genuine short shell (the recorded BOSS loading gate) is still
withheld as `blocked` → `content_unusable`.

## Verification

```
.venv/bin/python -m py_compile hermes_trailhead/*.py          # clean
.venv/bin/python -m pytest -q tests/test_reach_body_depth.py  # 19 passed
.venv/bin/python -m pytest -q                                 # 1092 passed
```

`tests/test_reach_body_depth.py` pins, with a stub executable and an injected
runner (no network, no real install):

- 11 500-char ASCII body and a ~9 000-char CJK+emoji body arrive byte-identical
  past the old bound, with matching `body` metadata;
- shared-budget behaviour: full first body, second body cut and flagged, third
  withheld as `body_budget_exhausted` with the limitation lines present;
- escape-worst-case output: 250 000 forwarded emoji (12 bytes each under
  `ensure_ascii=True`) serialise under `MAX_OUTPUT_BYTES` in compact, pretty,
  ASCII-escaped and non-escaped JSON forms;
- 50 items at `MAX_VALUE_CHARS`/`MAX_URL_CHARS` metadata plus a full emoji body
  stay under the cap in all four JSON forms (metadata is char-bounded, not
  byte-accounted, so this pins the realistic worst case, not every adversarial
  one);
- discovery text keeps the 4000-char bound and gains no `body` key;
- a `"Page not found"` prefix that *is* `missing_page` on its own does not
  condemn a 6 000-char article; the real BOSS gate is still withheld;
- malformed items (`None`, ints, lists, dicts as `text`, non-string `url`,
  non-string `title`) never raise, never inflate the envelope, and never turn a
  missing body into a forwarded read;
- continuation is `unknown` for absent, pagination-shaped, malformed and
  zero-valued cursor fields alike (never `"exhausted"`); an explicit
  `truncated` bool is echoed, and the runner is called exactly once per action.

## Small live evidence

One public read, optional upstream, no credentials, no ASR, public-only route
(`--backend v2ex-api`, isolated temp HOME). Captured 2026-10-28 against repo
HEAD `4882be1` + this uncommitted change, pinned Agent Reach 1.6.0.

| action | result |
|---|---|
| `v2ex read https://www.v2ex.com/t/1` | `ok`, 1 item, `returned_text_chars: 7956`, `text_truncated: false`, `body.upstream_chars/returned_chars: 7956/7956`, `local_truncated: false`, `upstream_complete: null`, `upstream: {truncated: null, continuation: {state: unknown, source: absent}}`, wire 17 196 bytes |
| `v2ex hot` (limit 2) | `ok`, 2 items, text 557 / 250 chars, **no** `body` key, `upstream: null` |

The read's tail is the topic's 2025–2026 reply stream (`targaze: 2025-10-30
打卡` … `@meetxie: 打卡`) — exactly the region the 4000-char bound used to
discard. 7956 chars still fits the budget with no local cut, so this record says
nothing about how a 250 000+ char artifact behaves; that path is covered only by
the synthetic tests above.

Reproduce:

```bash
cd <repo>
AGENT_REACH_BIN="$TMPDIR/agent-reach-eval-venv/bin/agent-reach" TRAILHEAD_DISABLE_ASR=1 \
  .venv/bin/python "$TMPDIR/forwarded-body-live.py"
# record: $TMPDIR/forwarded-body-live.json
```

## What this does not establish

- Whole-artifact completeness: `upstream_complete` is never `true`, and the
  pinned upstream sends no end-of-artifact signal to validate.
- That a body cut at the shared budget is recoverable by re-running: the budget
  is a forwarding bound, and a single artifact larger than 250 000 chars is
  simply still cut (now honestly and with the cut point reported).
- Reply/comment/transcript set exhaustion: no continuation state exists upstream
  on this pin, so none can be followed.
- Parity, reliability, freshness: one live read and one discovery call, one host.

## Harness and CLI reporting

- `scripts/evaluate_action_artifacts.py` no longer re-types `MAX_TEXT_CHARS`; it
  imports both bounds and reports, per row, the bound that governed the action:
  `max_text_chars_per_item` + `text_truncated_scope: discovery_snippet_clip`
  for discovery, `max_body_chars_per_result` +
  `body_budget_shared_across_items` + `text_truncated_scope:
  local_body_budget_cut` for body reads. The published historical record
  (`docs/evidence/action-artifacts-live.json`) is left byte-identical: it
  describes what that campaign observed at `MAX_TEXT_CHARS`, not the current
  bound.
- The CLI text renderer (`_reach_text_result`) now prints
  `returned of upstream chars` per body item, marks a local cut
  (`[cut at Trailhead's shared body budget]`), marks the 160-char preview with
  `…`, and prints `Upstream: continuation unknown` with no end-of-artifact
  proof. `--format json` still carries the full forwarded body.
