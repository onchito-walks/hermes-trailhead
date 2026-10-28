# Forwarded body equality — exact preservation against the raw upstream envelope

Scope: verification only. No production code, connector, wrapper, transport or
bound was changed; nothing was committed. This record answers one question that
`docs/FORWARDED-BODY-DEPTH.md` could not, because it compared lengths to an
earlier run: **when Trailhead forwards a body read, is the forwarded string the
exact upstream string from that same call, or a re-rendered near-copy?**

Evidence: `docs/evidence/forwarded-body-equality.json` (sanitised: hashes,
lengths, <=120-char previews, no raw envelopes, no local paths).

## Method

Two public action calls, no retry, no credentials, no quota, no ASR:

| call | channel.action | target | route | child backend |
|---|---|---|---|---|
| 1 | `v2ex read` | `https://www.v2ex.com/t/1` | `public_api` | `v2ex-api` (forced) |
| 2 | `web read` | `https://docs.python.org/3/library/asyncio.html` | `public_api` | `jina` (upstream default, no forced label) |

The maintained `AgentReachBackend` was constructed with a scratch runner that
calls the existing `_default_runner` and retains the **raw JSON envelope printed
by that same subprocess**. The comparison is therefore same-call to same-call:

- left side: `json.loads(raw_stdout)["items"][0]["text"]` — bytes as upstream emitted them;
- right side: `result.to_dict()["items"][0]["text"]` — what Trailhead normalised and returned.

No second fetch, no second timestamp, no cached or historical copy is involved.

Controls observed on both calls: `allow_authenticated=False`,
`allow_quota_consuming=False`, `TRAILHEAD_DISABLE_ASR=1` (veto evaluated
in-process; the child env is a strict allowlist — `PATH`, locale, `TMPDIR`/`TEMP`
— so the flag is deliberately not forwarded), child `HOME` an isolated temporary
directory with `TRAILHEAD_AGENT_REACH_HOME` unset, operator home untouched.

## Results

| action | target | ok | child backend | chars raw -> forwarded | sha256 (raw / forwarded) | exact | chars the old bound would drop |
|---|---|---|---|---|---|---|---|
| `v2ex read` | `https://www.v2ex.com/t/1` | `true` | `v2ex-api` | 7956 -> 7956 | `1c868f594b1c427e` / `1c868f594b1c427e` | true | 3956 |
| `web read` | `https://docs.python.org/3/library/asyncio.html` | `true` | `jina` | 3312 -> 3312 | `3828fca9e4da0ca7` / `3828fca9e4da0ca7` | true | 0 (below bound, see note) |

Both artifacts are preserved whole: identical character counts, identical
`sha256`, identical 200-character tail hashes, `first_mismatch_index: null`,
`text_truncated: false`, `body.local_truncated: false`,
`body.upstream_chars == body.returned_chars == len(text)`.

V2EX: 7956 chars, tail
`…切暂时性的困难。人生没有过不去的坎 和不可战胜的困难! @ovtfkw: 打卡留恋 @FawkesV: 果然好多人 打卡 @Slarda: 2026 考古 @meetxie: 打卡` — the reply stream the old bound
discarded (3956 chars)
is present verbatim.

Web/asyncio: 3312 chars, tail
`… can be found in [Lib/asyncio/](https://github.com/python/cpython/tree/3.15/Lib/asyncio/).` — the reader's closing line, again
verbatim. This artifact is **below** the old 4000 bound, so it does not exercise
the fix; it only shows the forwarding path is byte-preserving on a smaller read.

## Checks

| # | check | result |
|---|---|---|
| 1 | forwarded text equals the raw upstream text of the same call, character for character | pass |
| 2 | character length identical (no silent clip on either side) | pass |
| 3 | sha256(forwarded text) == sha256(raw upstream text) | pass |
| 4 | equality survives whitespace normalisation (not a re-rendered near-match) | pass |
| 5 | final 200 chars exist, are non-empty, and hash-match upstream | pass |
| 6 | text_truncated is false and body.local_truncated is false | pass |
| 7 | body.upstream_chars == body.returned_chars == len(text) == raw upstream chars | pass |
| 8 | body.upstream_complete is null (unknown, never true) | pass |
| 9 | body.upstream_truncated is null and result.upstream.truncated is null | pass |
| 10 | continuation state is 'unknown' with source 'absent' and next_offset null | pass |
| 11 | raw envelope carries schema_version 1 and no 'truncated'/'continuation' field | pass |
| 12 | classify_page_shell returns None for the whole upstream body and the forwarded body | pass |
| 13 | every upstream item was forwarded (no blocked/missing/empty withdrawal) | pass |
| 14 | the old 4000-char slice of the SAME payload differs from what was forwarded (the bound would have cut this artifact) | n/a |

The one check reported `n/a` is the counterfactual contrast: it can only be
evaluated where the artifact exceeds 4000 characters, and the asyncio read is
3312. It is not counted as a pass.

## Counterfactual baseline (labelled)

The `counterfactual_old_bound` block is **not** a historical live result. It is a
deterministic `text[:4000]` slice of *today's* payload, computed to show what the
old bound would have returned:

| action | slice chars | slice sha256 | slice == forwarded | old `text_truncated` would be |
|---|---|---|---|---|
| `v2ex read` | 4000 | `5ef62ecdde29b8b8…` | False | True |
| `web read` | 3312 | `3828fca9e4da0ca7…` | True | False |

## Why the old numbers are not a contradiction

`docs/FORWARDED-BODY-DEPTH.md` recorded `7956` chars for the same V2EX topic at
`4882be1`. Today's raw upstream text is also `7956` chars,
but that earlier record stored lengths, not hashes, so the only honest
statement is: **length matches the earlier capture; today's equality claim rests
on today's hashes**, both sides taken from one call. Topic 1's body being stable
across two captures is consistent with the earlier record, not proof borrowed
from it.

## What this does not establish

- **Whole-artifact completeness.** `body.upstream_complete` is `null` on both
  rows and the pinned 1.6.0 envelope carries no `truncated` or `continuation`
  field (`has_truncated_field: false`, `has_continuation_field: false`, item
  keys exactly `author/published_at/raw/text/title/url`). Equal-to-upstream is
  not equal-to-the-whole-page; the upstream string itself is a rendering (V2EX
  API model, jina reader markdown), and the asyncio text ending on the intro's
  closing line is a reason to keep completeness unknown rather than to assert
  it either way.
- **Budget behaviour.** Both artifacts sit far below
  `MAX_TOTAL_BODY_CHARS = 250000`; the mid-body cut and
  `body_budget_exhausted` paths are covered only by the synthetic tests in
  `tests/test_reach_body_depth.py`.
- **Parity/reliability.** Two calls, one host, one capture each, zero retries —
  no rate, drift or cross-host claim.
- **That the counterfactual slice ever ran.** It is derived, not observed.

## Reproduce

```bash
cd <repo>
AGENT_REACH_BIN="$TMPDIR/agent-reach-eval-venv/bin/agent-reach" TRAILHEAD_DISABLE_ASR=1 \
  .venv/bin/python "$TMPDIR/forwarded-body-equality-probe.py"
# rows + raw envelopes: $TMPDIR/forwarded-body-equality-rows.json,
#                       $TMPDIR/forwarded-body-equality-raw/
# sanitised ledger render: $TMPDIR/forwarded-body-equality-render.py
```

Re-running makes two new public calls; it does not reproduce the hashes above
verbatim unless the upstream renderings are unchanged (V2EX reply streams grow).
