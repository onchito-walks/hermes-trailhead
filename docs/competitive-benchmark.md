# Competitive benchmark — Hermes Trailhead vs Agent Reach

Status: **honest groundwork, not a parity claim.** Trailhead implements 2 of
Agent Reach's 14 channels natively, 6 partially, and 6 not at all; an optional
read-only forwarding layer (`reach` / `reach-call`) makes 13 of the 14 channels
reachable when Agent Reach is installed, with its attribution preserved. Any
statement that Trailhead "beats Agent Reach" today would be false: the breadth
is partly borrowed, and native depth is still missing on six channels. This
document separates what was measured from what was read out of source, and it
lists the gaps that would have to close first.

Reference competitor, pinned and read-only:

- Agent Reach `agent-reach` **1.6.0**, upstream commit
  `14c213405669414492bda0f8d52cc6531d062c45`
- Installed in an isolated evaluation venv, used without running its installer,
  login, or cookie import.
- Channel/action inventory captured from `agent-reach channels` (JSON, schema 1)
  and `agent-reach doctor` on 2026-10-28.

---

## 1. How the measured comparison works

`hermes-trailhead compare` asks both tools for the **same outcome** on an
explicit case, then records observations. It does not grade and does not rank.

```bash
# what cases exist, and what each side is asked for
.venv/bin/python -m hermes_trailhead compare --list-cases

# measured head-to-head, cold sandbox, JSON report written only where you point it
export TRAILHEAD_AGENT_REACH_BIN=/path/to/eval-venv/bin/agent-reach
.venv/bin/python -m hermes_trailhead compare --timeout 30 --out /tmp/compare-cold.json

# a deliberately warm run: reuse the sandbox from the cold run
.venv/bin/python -m hermes_trailhead compare --sandbox /tmp/compare-cold-sandbox

# single case, no competitor side
.venv/bin/python -m hermes_trailhead compare --case web-wikipedia-http --no-agent-reach

# human formats
.venv/bin/python -m hermes_trailhead compare --format markdown
```

`compare`, `reach`, and `reach-call` share the `TRAILHEAD_AGENT_REACH_BIN` pin,
so the same evaluation install is used for measurement and forwarding.

### 1.1 Matched outcomes, not matched command names

Each case declares the outcome requested and the Agent Reach action that asks
for that same outcome:

| Case shape | Trailhead | Agent Reach |
|---|---|---|
| documentation / article URL | `extract.extract_one(url)` | `agent-reach read <url>` |
| GitHub repository URL | `extract.extract_one(url)` | `agent-reach github read <url>` |
| V2EX topic URL | `extract.extract_one(url)` | `agent-reach v2ex read <url>` |
| V2EX **node** listing | `extract.extract_one(url)` | `agent-reach v2ex node python` |
| YouTube **transcript** | `extract.extract_one(url)` (transcript path) | `agent-reach youtube subtitle <url>` |
| open-web question | `search.execute_search("web")` + `extract_hits` | `agent-reach web search <query>` |

Two corrections came out of review and are now enforced by the manifest:

- A transcript case must not be compared against Agent Reach's `read`, which
  returns title/description metadata. It uses `youtube subtitle`.
- A node-listing case must not be compared against `v2ex read <node-url>`, which
  upstream rejects (the earlier run's `BAD_INPUT` was this mistake, later
  masked by a cascading `TIMEOUT`). It uses `v2ex node python`.

### 1.2 Evidence, not byte counts

`evidence_ok` is the only success signal. A result counts as evidence only when
all of the following hold:

1. `status == ok`;
2. the payload is not a login/verification wall (checked by phrase, and only
   when the page is mostly wall);
3. script/style/tag markup is stripped and the **cleaned** text still exceeds
   the case's floor (200 chars);
4. a payload that is more than half markup is rejected **only while its cleaned
   text stays under four times the floor**. Above that threshold a long page is
   accepted on cleaned text length alone — the check is "readable text came
   back", not "the markup ratio is healthy";
5. nav/shell chrome does not dominate a short page (three or more distinct
   phrases such as "skip to content", "cookie policy", "sign up", "menu" in the
   opening text, with under four times the floor of real text);
6. for `evidence_requirement=transcript`, transcript material is actually
   present (VTT cue lines, a `WEBVTT` header, or a transcript payload reported
   by Trailhead's video evidence).

The markup rule is deliberately narrow, and the docs say so instead of claiming
"no markup-dominated content": a 600 KB page that is 96% markup but still
yields thousands of characters of cleaned prose is scored `evidence`. That is a
statement about cleaned text being present, not a content-quality guarantee.
Markup-heavy verdicts only fire on short payloads (cleaned text under 4× the
case floor), which is the case where the wrapper really is all there is.

Relevance beyond "the requested page or transcript came back" is not scored
automatically — that would need a judge model, and a fabricated score would be
worse than no score. The report states the requirement per case so a human can
check the preview.

So a 602 KB Wikipedia HTML response and a 158-byte Instagram search snippet are
both reported, but only the first is evidence — and the report shows `raw_chars`,
`cleaned_chars`, `markup_ratio`, and the verdict for each side. Length is never
used to decide a winner, because no winner is decided at all.

### 1.3 Both sides as killable subprocesses, one wall budget

The two sides are measured under the same runtime rule: each case gets one
wall-clock budget (`--timeout`, default 30 s), and a side that exceeds it is
killed with its whole process group and reported `status=timeout`.

- **Trailhead** runs in a stdlib worker subprocess:
  `python -m hermes_trailhead.comparative --worker`. The parent sends one JSON
  request on stdin and reads one JSON response from stdout; there is no shell,
  and the worker cannot relabel itself or claim another case.
- **Agent Reach** runs as its CLI subprocess (`agent-reach <channel> <action>
  …`) with the same budget.
- Per-fetch timeouts inside either tool (for example Trailhead's extraction
  tiers) cannot extend the case budget: the parent kills the process, not the
  individual request. Before this change Trailhead ran in-process with only a
  per-fetch timeout, so a slow extraction chain could outlive the case while
  Agent Reach was already being killed — that asymmetry is gone.
- In-process runners can still be injected for tests; the report labels that
  mode `injected` and says it has no wall timeout, so a test run is never
  mistaken for a measured one.

### 1.4 Environment isolation — what it guarantees, and what it does not

A run creates a throwaway directory containing `home/`, a separate
`agent-reach-home/`, and `tmp/`, and hands that explicit environment to both
subprocesses. The parent process environment is not mutated.

- `HOME`, `HERMES_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `TMPDIR` point
  inside the throwaway tree;
- credential-, session-, cookie-, and proxy-shaped variables are dropped
  (name markers `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `COOKIE`,
  `SESSION`, `CAMOFOX`, `AUTH`, `PROXY`);
- Agent Reach receives that same minimal environment, so it cannot see the
  operator's `agent-reach` config, logins, or browser profile;
- Trailhead's transcript cache starts empty, so a cold run cannot silently
  reuse a cached transcript;
- `TRAILHEAD_DISABLE_ASR=1` is set for the Trailhead worker. That is
  `extract.py`'s existing switch, and it keeps a public comparison from
  invoking billable/key-consuming transcription. The report records
  `environment.billable_asr`.

What this is **not**: it is environment isolation, not a filesystem or OS
sandbox. A subprocess can still open absolute paths outside the sandbox, so
this is not proof that no readable credential elsewhere on disk was used, and
it is not a security boundary against a hostile tool. It does make both sides
start from the same empty config, with no inherited credential or session
variables, which is what the comparison needs.

`--sandbox DIR` reuses a directory on purpose; the report then says
`run_kind=warm`. Cold and warm results are never merged into one number.

### 1.5 What the report contains, and what it refuses to contain

Per side, per case: `status`, `duration_ms`, `raw_chars`, `cleaned_chars`,
`markup_ratio`, `chrome_signals`, `evidence_verdict`, `evidence_note`,
`item_count`, `backend`, `error`, `command`, `detail`, `freshness`.

Per case: a verdict from
`both_evidence`, `trailhead_only_evidence`, `agent_reach_only_evidence`,
`neither_evidence`, `not_comparable`.

There is **no** aggregate ranking, no A/A- grade, and no minimum-case threshold
that flips a winner. `summary.aggregate_ranking` is always `null` and
`summary.ranking_note` says why. The old three-case winner rule was removed
because three cases cannot support a product claim.

Statuses `unavailable` (not installed), `not_run` (`--no-agent-reach`, auth case
skipped) are distinct and never counted as failures or wins. Auth-shaped cases
are skipped unless `--include-auth` is passed; nothing reads a credential,
copies a cookie, or imports a session.

`--include-auth` does **not** produce an authenticated comparison. The run still
uses the empty throwaway HOME, so it is an *unauthenticated attempt*: no stored
session, cookie, or consent config is used, and a `blocked` result is the
expected outcome. Every such case carries an explicit `auth` block in the report
(`mode: unauthenticated_attempt`, `configured: false`) with the same note, and
the text/markdown output prints it — there is no suggestion anywhere that a
login or consent configuration was exercised. There is no login mechanism in
this tool, and the comparison does not add one.

The report's `environment` block also records `execution` (`subprocess` vs
`injected` per side), `wall_timeout_s`, `isolation` (`kind:
environment-only`, `filesystem_sandbox: false`, `credential_proof: false`), and
`billable_asr` (`disabled: true`).

---

## 2. Case manifest

| Case | Kind | Family | Prompt | Agent Reach asked for | Evidence requirement | Gate |
|---|---|---|---|---|---|---|
| `docs-python-typing` | URL | docs | `https://docs.python.org/3/library/typing.html` | `read <url>` | page text | public |
| `github-requests-readme` | URL | github | `https://github.com/psf/requests` | `github read <url>` | page text | public |
| `web-wikipedia-http` | URL | web | `https://en.wikipedia.org/wiki/HTTP` | `read <url>` | page text | public |
| `forum-v2ex-topic` | URL | v2ex | `https://www.v2ex.com/t/1252479` | `v2ex read <url>` | page text | public |
| `forum-v2ex-node` | URL | v2ex | `https://www.v2ex.com/go/python` | `v2ex node python` | page text | public |
| `video-youtube-transcript` | URL | youtube | `https://www.youtube.com/watch?v=aircAruvnKk` | `youtube subtitle <url>` | **transcript** | public |
| `question-typing-protocol` | question | web | "What does typing.Protocol require for structural subtyping?" | `web search <query>` | page text | public |
| `instagram-profile-session-tier` | URL | instagram | `https://www.instagram.com/nasa/` | `instagram profile nasa` | page text | auth |
| `facebook-page-session-tier` | URL | facebook | `https://www.facebook.com/nasa` | `facebook profile nasa` | page text | auth |

All public cases are public pages that require no account, token, or cookie.
The two auth cases are in the manifest so the document is explicit about what a
default run does *not* cover; they are skipped and reported as `not_run`. With
`--include-auth` they still run only as labeled *unauthenticated attempts* in
the empty sandbox HOME — this benchmark has no login path and never claims an
authenticated result. The public comparison also sets `TRAILHEAD_DISABLE_ASR=1`,
so no case can invoke a billable transcription.

---

## 3. Measured run — 2026-10-28 — **INVALIDATED**

The first measured run (7 public cases, Agent Reach 1.6.0 from the pinned venv,
30 s timeout) is kept on disk as evidence of what was observed, but **it is not
a result and none of its numbers are cited as a win**. Review found five
methodology defects:

1. The transcript case compared Trailhead's transcript against Agent Reach's
   `read` metadata — different requested outcomes.
2. The V2EX node case compared Trailhead's node page against
   `v2ex read <node-url>`, which upstream rejects; the failure was then
   reported as "Agent Reach timed out".
3. "Usable content" was `status=ok` and ≥200 characters, so 602 KB of Wikipedia
   HTML counted the same as 602 KB of article text.
4. The question case compared Trailhead's all-lane search sweep with Agent
   Reach's web-only search — different scope.
5. Both sides ran with the operator's environment, so Agent Reach could have
   used an existing config/session, and Trailhead could serve a warm transcript
   cache. A single aggregate winner was printed.

The run also predates the sandbox, `--sandbox` warm/cold labeling, and the
evidence verdicts. Its raw artifacts are
`$TMPDIR/trailhead-compare-2026-10-28.json` and
`$TMPDIR/trailhead-compare-2026-10-28.md`; treat them as historical.

### 3.1 Observations that remain true as anecdotes (not results)

These were single-run observations. They are worth re-checking, not quoting as
comparative outcomes:

- Agent Reach's V2EX channel was flaky across three runs: one success, one
  `BAD_INPUT` (caused by the invalid `read <node-url>` invocation), then a
  cascading `TIMEOUT` after its own circuit breaker paused the platform.
- A YouTube read on Trailhead returned in 3 ms against a warm cache; the same
  case took ~10.5 s cold. This is exactly why cold and warm runs are now
  labeled separately and why every run gets a fresh sandbox by default.
- Agent Reach's YouTube `read` hit a `yt-dlp` bot check (`PLATFORM_BLOCKED`);
  its `subtitle` action was never exercised in that run.

### 3.2 Re-running honestly (bounded)

A corrected run is a deliberate, bounded act, not a sweep:

```bash
export TRAILHEAD_AGENT_REACH_BIN=/path/to/eval-venv/bin/agent-reach
.venv/bin/python -m hermes_trailhead compare --timeout 30 --out /tmp/compare-cold.json
```

Then read the per-case verdicts. If a case shows `not_comparable`, the missing
side's status says why (`unavailable`, `not_run`, `timeout`, `blocked`). If both
sides return evidence, the case is `both_evidence` and no ordering is implied.

### 3.3 Bounded smoke of the corrected method (2026-10-28, cold sandbox)

Three cases, run exactly as the docs then instructed (`--timeout 40`, pinned
1.6.0, fresh sandbox). This is a smoke test of the harness, not a benchmark
suite.

It predates the killable-worker change: the Trailhead side then ran in-process
with per-fetch timeouts, so its numbers are **not** wall-clock comparable with
the Agent Reach subprocess and no timing claim survives. The per-case evidence
outcomes are kept as harness observations only; re-measure before quoting
anything.

| Case | Trailhead | Agent Reach | Verdict |
|---|---|---|---|
| `video-youtube-transcript` | `blocked`, 2 183 ms — page and transcript unreachable | `blocked`, 1 559 ms — `PLATFORM_BLOCKED` (yt-dlp bot check) | `neither_evidence` |
| `forum-v2ex-node` | `ok`, 2 621 cleaned / 67 713 raw chars, 96% markup, 299 ms | `ok`, 6 204 cleaned / 6 600 raw chars, 6% markup, 321 ms | `both_evidence` |
| `web-wikipedia-http` | `ok`, 137 803 cleaned / 602 460 raw chars, 77% markup, 462 ms | `ok`, 102 234 cleaned / 102 758 raw chars, 1% markup, 1 059 ms | `both_evidence` |

What the smoke establishes:

- The transcript case is asked of Agent Reach as `youtube subtitle`; with a cold
  sandbox both sides are `blocked` and the case is `neither_evidence`. The old
  "Trailhead ok in 3 ms" was the local transcript cache, not a fresh fetch.
- The node case is finally comparable: Agent Reach's `v2ex node` works, so the
  earlier `BAD_INPUT`/`TIMEOUT` framing was an artifact of asking for `read` on
  a node URL.
- Raw length was never the whole story: Trailhead's 602 KB Wikipedia response is
  77% markup and only 137 803 characters of readable text, still above Agent
  Reach's 102 234. Reporting both numbers (and the ratio) is the point.
- Verdicts are per case; `aggregate_ranking` is `null`. Two cases tie on
  evidence, one ties on absence.

Report artifact: `$TMPDIR/trailhead-compare-corrected-final.json`
(cold sandbox, `credentials_forwarded: false`).

Still not covered by this smoke: X, Reddit, Bilibili, Xiaohongshu, LinkedIn,
BOSS, Xueqiu, Xiaoyuzhou, and any auth-gated surface. No broadening claim
follows from three cases.

---

## 4. Capability parity matrix — all 14 upstream channels

Legend: **full** = every Agent Reach action on that channel has a dedicated
Trailhead code path; **partial** = some actions covered, or covered only by
generic known-URL extraction; **absent** = no dedicated path.

Two coverage columns, because they are not the same thing:

- **Native**: Trailhead code implements the surface itself.
- **Forwarded**: `hermes-trailhead reach-call` runs the installed Agent Reach
  CLI read-only and returns its items **with Agent Reach attribution**. This is
  gap-closing by reuse, not a native implementation, and it stops working when
  that CLI is absent.

| # | Channel | AR level | AR actions (v1.6.0) | Trailhead native | Forwarded via `reach-call` |
|---|---|---|---|---|---|
| 1 | `web` | default | search, read | **full** | read, search |
| 2 | `youtube` | default | read, search, subtitle, transcribe | **full** | read, search, subtitle (`transcribe` excluded: paid/key) |
| 3 | `github` | default | search, read (repo or issue/PR with comments) | **partial** | read, search |
| 4 | `reddit` | optional | search, read, subreddit | **partial** | search, read (public-web); `subreddit` needs consent |
| 5 | `twitter` | experimental | search, profile, tweets, thread | **partial** | search (public-web); profile/tweets/thread need consent |
| 6 | `instagram` | experimental | search (users), profile, posts | **partial** | search, profile, posts — consent only |
| 7 | `facebook` | experimental | search, profile | **partial** | search (public-web); profile needs consent |
| 8 | `v2ex` | default | hot, node, read, user | **partial** (generic read only) | hot, node, read, user |
| 9 | `bilibili` | default | search, read, hot, subtitle | **absent** | search, read, hot, subtitle — consent only |
| 10 | `xiaohongshu` | optional | search, read, comments | **absent** | search, read (public-web); comments need consent |
| 11 | `linkedin` | optional | jobs, read | **absent** | jobs, read (public-web) |
| 12 | `boss` | optional | search, read | **absent** | search, read (public-web) |
| 13 | `xueqiu` | optional | quote, search, hot_posts, hot_stocks | **absent** | quote, search, hot_posts, hot_stocks — consent only |
| 14 | `xiaoyuzhou` | optional | transcribe | **absent** | not forwarded (its only action is paid/key ASR) |

Totals, as of this document (Agent Reach 1.6.0: 14 channels, 40 actions):

- **Native**: 2 full / 6 partial / 6 absent channels; 14 of 40 actions have a
  dedicated Trailhead path (web 2, youtube 4, github 2, reddit 2, twitter 2,
  instagram 1, facebook 1).
- **Forwarded**: 13 of 14 channels and 38 of 40 actions are reachable
  when Agent Reach is installed, in public mode where upstream declares a
  public route, or with explicit `--allow-authenticated` consent otherwise.
  The two excluded actions are the paid `transcribe` calls (YouTube,
  Xiaoyuzhou).
- **Still absent under every mode**: Xiaoyuzhou transcription (paid ASR) and
  every Agent Reach management verb (install, login, browser, update).

### 4.1 What forwarding does and does not buy

Commands:

```bash
# inventory: what can be forwarded, and how each pair is reached
hermes-trailhead reach
hermes-trailhead reach --format json

# one read-only call, Agent Reach attribution preserved in the output
hermes-trailhead reach-call v2ex node python --limit 5
hermes-trailhead reach-call github read https://github.com/psf/requests --format json

# session-only actions require explicit consent; there is no silent fallback
hermes-trailhead reach-call instagram profile nasa            # -> auth_required
hermes-trailhead reach-call instagram profile nasa --allow-authenticated
```

Measured on the pinned 1.6.0 install, 2026-10-28 (single calls, forwarding
probes — not benchmark results):

| Call | Result |
|---|---|
| `reach-call v2ex node python --limit 3` | ok, backend `v2ex-api`, 3 items, attribution present |
| `reach-call github read https://github.com/psf/requests` | ok, backend `gh`, 1 item (2 894 chars) |
| `reach-call instagram profile nasa` (no consent) | `auth_required`, nothing spawned |
| `reach-call youtube transcribe <url>` | rejected: `action_not_allowlisted` |
| `reach --agent-reach <missing>` | `found: false`, `not_configured`, no install attempt |

What it does **not** buy:

- Forwarded items carry no Trailhead scoring, extraction follow-through, or
  source typing — they are the upstream's text, passed through.
- No quality claim can rest on forwarded output; the report says
  "without native scoring or extraction" in its own `limitations` list.
- It depends on the competitor staying installed and compatible (registry
  schema 1). If Agent Reach changes, forwarding breaks; native lanes do not.
- Auth-gated forwarding means "use the login the operator already made in
  Agent Reach". Trailhead still never creates, imports, or copies a session.
- Breadth is borrowed, not owned. Calling this "beating Agent Reach" would be
  circular: the capability is Agent Reach's.

## 5. Per-action depth on the shared channels

Native depth only. A `reach-call` to any of these pairs returns exactly the
upstream behaviour below, with Agent Reach attribution — forwarding adds no
extra depth.

| Action | Agent Reach 1.6.0 | Trailhead today | Depth verdict |
|---|---|---|---|
| `web read` | Jina Reader, Exa fallback, anti-bot page detection | direct → Jina → Hermes web_extract, HTML-shell detection, source typing | parity; Trailhead reports *why* a page failed, AR returns an error code |
| `web search` | Exa hosted MCP (free tier, rate-limited) | DDG lite/html, Jina-over-DDG, Bing, local SearXNG | Trailhead broader fallback chain; AR single upstream with clear `RATE_LIMITED` |
| `github read` (repo) | README + repo facts via `gh`/API | condensed facts block, README, releases, file/tree fetch | AR returns more text; Trailhead's block is more compact and labeled |
| `github read` (issue/PR) | issue/PR body **with comments** | not implemented as a dedicated path | **AR ahead** |
| `youtube read` | title/channel/date/description via yt-dlp | metadata + captions + ASR with `video_evidence` status | Trailhead deeper on failure reporting; same underlying yt-dlp risk |
| `youtube subtitle` | full subtitle text | caption/transcript text inside extract | parity |
| `youtube transcribe` | Whisper via Groq/OpenAI quota | Groq ASR (same key model) | parity; both depend on a key + quota |
| `reddit read` | public page text first, `opencli` for post+top comments | Redlib → PullPush → Arctic Shift → old.reddit, post + comments composed | Trailhead has more independent routes; AR has cleaner single semantics |
| `reddit subreddit` | latest posts in a subreddit | not a dedicated action | **AR ahead** |
| `twitter thread` | tweet + replies via `opencli` browser | FxTwitter + Nitter replies | AR needs a browser login; Trailhead needs a working Nitter |
| `twitter profile` / `tweets` | profile and recent tweets | not implemented | **AR ahead** |
| `instagram profile` | profile via `opencli` | `web_profile_info` + session tier, else blocked | AR broader, Trailhead needs BYO session |
| `instagram posts` | recent posts list | not implemented | **AR ahead** |
| `instagram read` | not in AR's action set | single post/reel caption + media transcript | **Trailhead ahead** (AR cannot read one reel URL) |
| `v2ex read` | `/t/<id>` topic + replies via API | generic page extraction | AR structured; Trailhead returns the whole page, unnormalized |
| `v2ex hot/node/user` | three dedicated actions | not implemented | **AR ahead** |
| `v2ex non-topic URL` | rejected as `BAD_INPUT` (channel claims the host) | generic extraction works | **Trailhead ahead** (upstream contract, not a timing claim) |

---

## 6. Onboarding and account lifecycle

| Capability | Agent Reach 1.6.0 | Trailhead |
|---|---|---|
| Install | `agent-reach setup` plus per-channel `add` (installs upstream tools) | none — `pip install` / repo checkout; no installer by design |
| Per-channel add/remove | `add <channel>`, `remove <channel>` | none |
| Login / logout | `login|logout <channel>`, browser-based, `--import-existing` session reuse | no login flow; BYO persistent browser session via env (`docs/AUTHENTICATED-TIER.md`) |
| Browser lifecycle | `browser setup|status|stop`, `browser profiles|use ID` (shared browser, slots) | external Camofox instance, env-configured, health probed only |
| Skill / agent wiring | `skill`, `skill link <dir>` writes a SKILL.md for other agents | repo-local `hermes_trailhead` module; no skill linking |
| Health | `doctor` (no network), `check [channel]` (live), `regressed` flag | `doctor`, `doctor --live --record`, `queue`, `capability-radar`, `reliability` |
| Update | `update`, `update --check`, update notice in JSON `meta` | none — user-managed checkout |
| Uninstall | `uninstall [--dry-run]` | none |
| Key config | `configure groq-key|openai-key|proxy|github-token` | environment variables read by the relevant backend only |
| Version | `version` (JSON, install method) | `--version` |

Trailhead is deliberately weaker here: it has no lifecycle manager. That is a
product choice, not a feature, and it is why "install and be done" users will
find Agent Reach easier to stand up.

---

## 7. Safety posture

| Surface | Agent Reach 1.6.0 | Trailhead |
|---|---|---|
| Installer | writes tools, skill files, browser setup; `--allow-upgrade` possible | none |
| Credentials | never asks for passwords; login happens in its own browser window / session state | none read; session tier is env-configured and owned by the user |
| Cookie / session reuse | `login --import-existing`, `browser profiles`, yt-dlp cookie advice | no cookie import, no browser-profile copying in any path |
| Approval gates | per-action `approval_required` in output envelope; `public-web` backend avoids browser | `approval_required` on routes/channels (X, TikTok, Instagram, external tools) |
| Blocked reporting | `PLATFORM_BLOCKED` / `NEED_LOGIN` codes with hints | `blocked` status plus reason; `score` no longer paints cached files as success |
| Public writes | none in the CLI surface | none |
| Update network calls | update notice (cached from an explicit `update --check`) | none |

Neither tool is unsafe by construction; the difference is surface area.
Agent Reach manages accounts and browsers, so it necessarily handles more
sensitive state. Trailhead's narrower surface is a smaller attack surface *and*
a weaker capability set — the two facts belong in the same sentence.

---

## 8. Speed

Only one timing number survives the methodology review unchanged, because it
does not depend on case design:

| Measurement | Trailhead | Agent Reach |
|---|---|---|
| CLI startup (`--version` / `version`), 3 runs each | 0.12–0.13 s | 0.19 s |

Per-case timings from the 2026-10-28 run are **withheld**: they came from
mismatched outcomes (metadata vs transcript, rejected node invocation),
un-sandboxed environments, and a warm Trailhead cache. Quoting them would
re-import the defect the run was invalidated for. Re-measure with
`compare --out DIR/cold.json`, then `compare --sandbox DIR` for a warm number,
and report the two runs separately.

What can be said without numbers: on the invalidated run the all-lane question
case was the slowest Trailhead path and the most content-heavy, while Agent
Reach's web search was fast and returned few items. That is a design difference
(seven lanes plus per-hit extraction vs one upstream query), not a measurement.

---

## 9. Reliability

| Concern | Agent Reach 1.6.0 | Trailhead |
|---|---|---|
| Pre-flight | `doctor` (install state), `check` (live per action/backend), `regressed` marker | `doctor`/`doctor --live`, `queue`, `reliability` trends, `capability-radar` |
| Multi-route fallback | per action `backends` list, `FINAL_CODES` stops futile retries | per lane backend chains + extraction tiers (direct → Jina → Hermes → browser) |
| Quality contract | release acceptance + upstream tests | deterministic `gauntlet` (100/100 product contract) and `benchmark` canary |
| Failure memory | `regressed` per channel since last check | reliability records over time (`doctor --live --record`) |
| Upstream drift | `update` upgrades every added channel's tools | none — upstream tools drift silently |
| Named weak spot | browser slot contention (`BUSY`), login expiry | single-route lanes (Redlib window, Nitter availability), no update path |

---

## 10. Integrations

| Integration | Agent Reach 1.6.0 | Trailhead |
|---|---|---|
| Output contract | one JSON object, `schema_version: 1`, `{ok, channel, action, backend, items, meta, error}` | per-command JSON (`--format json`), no versioned envelope |
| Agent skills | ships `SKILL.md` and links it into other agents' skill dirs | Python module + CLI; no skill artifact |
| Editor/agent targets | Claude Code, Cursor (documented) | Hermes-native (research CLI, report generator, routes) |
| Importable API | Python package channels | `hermes_trailhead` modules (`extract`, `scoring`, `search`, `comparative`) |
| MCP | not in this CLI | not provided |
| Plugins | none | none |
| Borrowed breadth | — | `reach` (inventory) and `reach-call` (one read-only action) forward the installed Agent Reach CLI with `engine`/`provenance`/`limitations` on every result; public mode forces `--backend public-web`, session-only actions need `--allow-authenticated` |
| Executable pin | `--agent-reach`, `TRAILHEAD_AGENT_REACH_BIN`, PATH | same order, shared by `compare`, `reach`, `reach-call` |

---

## 11. Gap register (what would have to close for a parity claim)

1. **Six channels with no native Trailhead path**: Bilibili, Xiaohongshu,
   LinkedIn, BOSS Zhipin, Xueqiu, Xiaoyuzhou. Five of the six are reachable only
   by forwarding Agent Reach (`reach-call`); Xiaoyuzhou transcription is not
   forwarded at all because its only action bills a Whisper endpoint.
2. **GitHub issue/PR depth**: no comment composition; AR reads issues/PRs with
   comments in one action.
3. **Twitter action surface**: no profile, no recent-tweets list; thread reads
   depend on a third-party frontend.
4. **Instagram/Facebook listings**: no "recent posts" or user search; both
   require a session tier that is off by default.
5. **V2EX actions**: no hot/node/user actions; generic read only.
6. **Channel lifecycle**: no add/remove/login/update/uninstall, no shared
   browser management, no skill linking. The forwarding layer deliberately
   refuses those verbs, so breadth depends on the operator managing Agent Reach
   themselves.
7. **Forwarded output is unprocessed**: no Trailhead scoring, extraction
   follow-through, or source typing on `reach-call` items; no caching, no
   fallback tiers, no circuit breaker of our own.
8. **Machine contract**: no versioned JSON envelope, so downstream agents
   cannot pin a schema the way they can with `schema_version: 1`.
9. **Tool inventory**: `doctor` does not report upstream tool versions the way
   AR's `doctor` does.
10. **Documentation debt outside this file**: `README.md` still describes
   `score --live` as re-probing and "re-verified live" grades, and `CHANGELOG.md`
   still advertises the old grade semantics. Those files are PM-owned; this
   benchmark does not edit them.

## 12. What the current evidence supports

- **No comparative performance claim.** The one measured run is invalidated
  (section 3); there is no honest head-to-head result to quote yet. The tooling
  to produce one is in place and tested.
- **Methodology is now enforced, not promised**: matched Agent Reach actions per
  case (`youtube subtitle`, `v2ex node`), evidence verdicts over cleaned text
  instead of byte counts (with the markup rule stated as the narrow
  short-payload check it is), both sides as killable subprocesses with one wall
  budget, environment isolation with billable ASR disabled, cold/warm
  separation, labeled unauthenticated auth attempts, and no aggregate ranking.
- **Native vs borrowed breadth is a real, documented split**: 2 of 14 channels
  natively full, 6 partial, 6 absent; 14 of 40 actions have a dedicated path.
  `reach-call` forwards 38 of 40 read-only actions, preserving Agent Reach
  attribution. That is borrowed capability, and it stops working without the
  competitor installed.
- **Qualitative differences verified from source and a bounded probe**: Agent
  Reach rejects a V2EX node URL on `read` (`BAD_INPUT`) and offers `v2ex node`
  instead; Trailhead's YouTube path can serve a transcript, while Agent Reach's
  `read` returns metadata and its `subtitle` action is the equivalent.
- **One observed reliability fact worth re-checking**: Agent Reach's V2EX
  channel returned `BAD_INPUT`, then a success, then a cascading `TIMEOUT` while
  its circuit breaker paused the platform. Single-host anecdote.
- No claim about breadth, depth on unmeasured channels, long-run reliability, or
  overall product superiority follows from any of this.

Re-run before quoting any number. The report carries its own timestamp,
environment block (sandbox, run kind, execution mode, wall timeout, isolation
flags, ASR state, Agent Reach path/version), and limitations list for exactly
that reason.
