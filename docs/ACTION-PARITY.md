# Action parity: Agent Reach 1.6.0 (pinned)

Status: **inventory complete, live parity not established.** Trailhead
advertises all 40 reference actions and can execute every one that is not
quota-gated, but only a minority have a recorded real run and no
authenticated case has been measured yet. A row in this table is not a
performance claim; it is a statement of what code exists and what evidence
backs it.

## Pinned reference

- Project: [`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach)
- Version: `1.6.0`
- Commit: `14c213405669414492bda0f8d52cc6531d062c45`
- Registry measured: 2026-10-28 (`agent-reach channels`)
- Surface: 14 channels, 40 actions

No other upstream version may be used to claim parity. The inventory is
static code (`reach_backend.PARITY_ACTIONS`); `agent-reach channels` is only
used to *validate* it, never to populate it.

## State vocabulary

Four different things are routinely conflated. This document keeps them apart:

| Word | Meaning here |
|---|---|
| **advertised** | the action exists in the pinned upstream registry |
| **surfaced** | `capabilities()` lists it with a route and a gate |
| **implemented** | Trailhead has code that can produce the artifact (`coverage`) |
| **live-verified** | a real call succeeded and the result is recorded in the docs |

`coverage` values:

- `native` — Trailhead produces the same artifact with its own code.
- `native-partial` — Trailhead produces part of it; the upstream action adds
  the rest (README/comments, exhaustive replies, ASR).
- `upstream` — only Agent Reach covers it; Trailhead forwards it.

`gate` values:

- `public` — runs without consent, on a pinned public route where one exists.
- `consent` — needs `allow_authenticated` / `--allow-authenticated` because
  upstream reaches it through a browser or session login.
- `quota` — needs `allow_quota_consuming` **and** `allow_authenticated`, and
  `TRAILHEAD_DISABLE_ASR=1` vetoes it even then.

`evidence` values:

- `live` — a dated real run against the pinned commit, recorded in
  `agent-reach-backend.md` or `SUPERIORITY-ACCEPTANCE.md`.
- `native-tests` — Trailhead's own tests cover the native lane.
- `fixture` — a contract test with a fake CLI. **This is not live evidence.**
  A green fixture suite proves argv assembly, gates, attribution, and parsing;
  it proves nothing about upstream availability or content completeness.

`gate` is the same three-word vocabulary in `capabilities()` and here:
`public`, `consent`, `quota`. `authenticated` is a *route* word
(`mode`/`provenance.route`), never a gate.

`states` (per row, machine-readable) always starts with the exact `coverage`
word — `native`, `native-partial`, or `upstream` — then appends `gated-auth` or
`gated-quota` for gated rows and `testing-fixture` when no `live` evidence
exists. A partial row therefore reads `native-partial`, not `upstream` +
`partial`.

## Matrix

All 40 rows are surfaced. `live` is a recorded run, not a passing test.
`parity_inventory()["counts"]` computes `surfaced_ratio` (40/40 = 1.00), and
`validate_parity_inventory()` fails if an allowlisted pair has no row, so the
ratio can never be inflated by a surfaced pair the table does not list.

| # | Channel | Action | Coverage | Gate | Evidence | Note |
|---|---|---|---|---|---|---|
| 1 | `github` | `search` | native | public | fixture, native-tests, live |  |
| 2 | `github` | `read` | native-partial | public | fixture, native-tests | Native repo-root reads fetch public README and labeled repository metadata; issue/PR comment completeness remains partial. |
| 3 | `twitter` | `search` | native | public | fixture, native-tests |  |
| 4 | `twitter` | `profile` | upstream | consent | fixture |  |
| 5 | `twitter` | `tweets` | upstream | consent | fixture |  |
| 6 | `twitter` | `thread` | upstream | consent | fixture |  |
| 7 | `youtube` | `read` | native | public | fixture |  |
| 8 | `youtube` | `search` | native | public | fixture |  |
| 9 | `youtube` | `subtitle` | native | public | fixture, native-tests |  |
| 10 | `youtube` | `transcribe` | native-partial | quota | fixture, native-tests | Native public captions plus opt-in-only ASR helpers in extract.py; automatic extraction never spends the transcription key/quota, and this is not the forwarding path. |
| 11 | `reddit` | `search` | native | public | fixture, native-tests, live |  |
| 12 | `reddit` | `read` | native-partial | public | fixture | Trailhead extracts public page text; exhaustive reply capture is upstream's. |
| 13 | `reddit` | `subreddit` | native-partial | consent | fixture | Trailhead lists posts via public search; upstream's node listing is the fuller artifact. |
| 14 | `facebook` | `search` | upstream | public | fixture |  |
| 15 | `facebook` | `profile` | upstream | consent | fixture |  |
| 16 | `instagram` | `search` | upstream | consent | fixture |  |
| 17 | `instagram` | `profile` | upstream | consent | fixture |  |
| 18 | `instagram` | `posts` | upstream | consent | fixture |  |
| 19 | `bilibili` | `search` | upstream | public | fixture |  |
| 20 | `bilibili` | `read` | upstream | public | fixture |  |
| 21 | `bilibili` | `hot` | upstream | public | fixture, live |  |
| 22 | `bilibili` | `subtitle` | upstream | consent | fixture |  |
| 23 | `xiaohongshu` | `search` | upstream | public | fixture |  |
| 24 | `xiaohongshu` | `read` | upstream | public | fixture |  |
| 25 | `xiaohongshu` | `comments` | upstream | consent | fixture |  |
| 26 | `linkedin` | `jobs` | upstream | public | fixture |  |
| 27 | `linkedin` | `read` | upstream | public | fixture |  |
| 28 | `boss` | `search` | upstream | public | fixture |  |
| 29 | `boss` | `read` | upstream | public | fixture |  |
| 30 | `v2ex` | `hot` | upstream | public | fixture, live |  |
| 31 | `v2ex` | `node` | upstream | public | fixture |  |
| 32 | `v2ex` | `read` | upstream | public | fixture |  |
| 33 | `v2ex` | `user` | upstream | public | fixture |  |
| 34 | `xueqiu` | `quote` | upstream | public | fixture, live |  |
| 35 | `xueqiu` | `search` | upstream | public | fixture |  |
| 36 | `xueqiu` | `hot_posts` | upstream | consent | fixture |  |
| 37 | `xueqiu` | `hot_stocks` | upstream | consent | fixture |  |
| 38 | `xiaoyuzhou` | `transcribe` | upstream | quota | fixture |  |
| 39 | `web` | `search` | native | public | fixture, native-tests |  |
| 40 | `web` | `read` | native | public | fixture, native-tests |  |

## Counts

| Dimension | Count |
|---|---|
| Channels | 14 |
| Actions | 40 |
| Surfaced | 40 |
| Surfaced / total (ratio) | 40/40 = 1.00 |
| Read-only forwarded (surfaced minus quota) | 38 |
| Native coverage | 8 |
| Native-partial coverage | 4 |
| Upstream-only coverage | 28 |
| Public gate | 26 |
| Auth-gated | 12 |
| Quota-gated | 2 |
| Live-verified | 5 |
| Fixture/native-contract only | 35 |

## Consent gates

Read-only forwarded actions use the allowlist and per-action route policy in
`reach_backend.py`. Quota actions are outside that allowlist:

```text
no flags                      -> quota_required   (nothing spawned)
--allow-quota-consuming       -> auth_required    (nothing spawned)
--allow-authenticated         -> quota_required   (nothing spawned)
both flags, ASR allowed       -> runs, route=quota, provenance.quota_consuming=true
both flags, TRAILHEAD_DISABLE_ASR=1 -> asr_disabled (nothing spawned)
```

`youtube transcribe` and `xiaoyuzhou transcribe` are the only quota actions.
Management verbs (`login`, `setup`, `browser`, `configure`, `update`,
`uninstall`, `skill`, `doctor`, `check`, `version`) are rejected before a
process exists. `search` has no flag or import that reaches this gate.

## Live evidence actually recorded

These five rows are the only ones labelled `live`:

- `github search`
- `reddit search`
- `bilibili hot`
- `v2ex hot`
- `xueqiu quote`

Source: the per-call public-mode verification table in
`agent-reach-backend.md`. Each of these five has its own row in that table.

`github read`, `bilibili read`, and `xueqiu search` were previously labelled
`live` on the strength of an aggregate statement in
`SUPERIORITY-ACCEPTANCE.md`, not a recorded per-call run. They are now
`fixture`/`native-tests` only: an aggregate summary is not a replacement for
the individual row. Record a fresh live run here before promoting any of them
back.

No live call was made while adding the quota gate or this inventory. The
two transcription actions have **never** been executed here.

## What this does not establish

- Authenticated parity: none of the 12 `consent` actions has been run
  against a configured account.
- Content completeness: READMEs, issue/PR comments, thread replies, profile
  fields, and podcast transcripts have not been compared artifact by
  artifact.
- Reliability/freshness, latency, and resource parity: not measured here.
- Clean-machine onboarding and account lifecycle: not covered.
- That Trailhead beats Agent Reach overall. Coverage of the same 40 action
  names is not superiority, and 28 of them are Agent Reach's own code.

## Isolation caveat

Public mode starts the upstream CLI with a temporary empty `HOME` and
redirected `XDG_*`/`APPDATA` variables. That is **environment isolation, not
a filesystem or process sandbox**: a same-user process can still read any
absolute path and use the network. Do not describe it as a security boundary.

Credential material comes only from upstream's own `HOME`/`XDG` config (the
consented path): no API key, token, or cookie variable is ever forwarded from
Trailhead's environment in either mode. `describe()["credential_source"]` is
`upstream-home-config`.

Upstream error text (registry stderr, execution stderr, `error` fields,
`meta.attempts`) is passed through best-effort pattern redaction for common
key/token/bearer shapes and `scheme://user:password@host` URLs. That reduces
accidental secret echo; it is not a universal redaction guarantee, so a
hostile upstream that prints a credential in a novel format can still leak it.

## Reproduce

```bash
# static inventory, no executable or network required
.venv/bin/python -m hermes_trailhead reach --format json
# contract tests: gates, attribution, argv, inventory drift
.venv/bin/python -m pytest tests/test_reach_backend.py tests/test_cli_reach.py -q
```

`reach_backend.validate_parity_inventory(registry)` raises if the pinned
registry gains or loses a channel/action, so upstream drift fails a test
instead of silently shrinking coverage. Update this document only together
with `PARITY_ACTIONS`, the pinned commit, and new evidence.

