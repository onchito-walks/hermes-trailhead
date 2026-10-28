# Optional research backends (Agent Reach search fallback)

Trailhead's own lanes — DuckDuckGo/Bing/Jina/SearXNG, GitHub's public API,
Redlib, yt-dlp, and site-scoped search — run first and run to completion. This
page describes the **one** optional backend that can run after them, and the
conditions under which it is allowed to.

The goal is gap-closing by reuse: when every native/free lane for a source
family returns nothing, an already-installed third-party CLI (Agent Reach) may
supply public, read-only **search** leads — attributed, bounded, and never
mistaken for Trailhead's own coverage.

- Module: `hermes_trailhead/backends.py` (`run_reach_search_fallback`,
  `configured_reach_executable`, `build_reach_search_adapter`,
  `REACH_SEARCH_ROUTES`).
- Adapter: `hermes_trailhead/reach_backend.py` (unchanged, reused as-is).
- Contract tests: `tests/test_reach_search_fallback.py`.

## Enablement: explicit configuration only

| State | Behaviour |
|---|---|
| `TRAILHEAD_AGENT_REACH_BIN` set to a path or name | the fallback may run, after the native chain is exhausted |
| `TRAILHEAD_AGENT_REACH_BIN` set but missing/not executable | one recorded `not_configured` attempt; the lane still reports its native error |
| `agent-reach` present on `PATH`, variable unset | **no fallback** — `PATH` presence is never treated as consent |
| default install | no dependency added, nothing downloaded, installed, updated, or logged in to |

Trailhead never installs Agent Reach, never writes its config, and never
creates a login. If the operator wants the fallback they name the binary
themselves; if they remove the variable, the next search is native-only again.

```bash
export TRAILHEAD_AGENT_REACH_BIN=/opt/agent-reach/bin/agent-reach
python3 -m hermes_trailhead search x "hermes agent" --execute --limit 3 --format json
unset TRAILHEAD_AGENT_REACH_BIN
```

`TRAILHEAD_AGENT_REACH_HOME` is **not** consulted by the search fallback: it is
an authenticated-mode knob, and search never runs authenticated.

## Ordering: last, and only when empty

```
lane-native discovery (yt-dlp / GitHub API / social-search)
  → native + free HTTP backend chain (DDG, Jina, Bing, SearXNG, Redlib, …)
  → site-scoped tail attempts
  → optional Agent Reach public search (this page)
```

A lane that already produced a lead never touches the fallback; the adapter is
not even constructed. A lane that produced nothing gets one bounded upstream
call, and only for families that have a real public upstream search route.

## Lane mapping

| Trailhead lane | Upstream channel / action | Public route upstream |
|---|---|---|
| `web` | `web search` | its declared public backends (e.g. `exa`) |
| `github` | `github search` | forced `github-api` |
| `reddit` | `reddit search` | forced `--backend public-web` |
| `x` | `twitter search` | forced `--backend public-web` |
| `youtube` | `youtube search` | `yt-dlp` (only if the isolated run can reach it) |

Not mapped, on purpose:

- `tiktok` — upstream has no TikTok channel.
- `instagram` — upstream exposes `instagram search` only behind a browser
  login, so in public mode it can only answer `auth_required`. Mapping it would
  burn a subprocess to produce a guaranteed error.
- every non-search action: `read`, `profile`, `thread`, `subtitle`,
  `transcribe`, and all management verbs.

## Public, read-only, no quota

- `AgentReachBackend(..., allow_authenticated=False)` is hard-coded in
  `build_reach_search_adapter`. There is no search flag or environment variable
  that turns consent on.
- The child process runs with a private, empty temporary `HOME`, so operator
  credentials, `~/.config/gh`, and stored upstream sessions are invisible to it.
- Only the `search` action is ever requested, so a transcription (Whisper) call
  or a paid/key-consuming action cannot be reached from a search run.
- A returned payload whose provenance does not say `public_only: true` (or that
  claims the `authenticated` route) is **refused** with `auth_gate`, even if it
  contains items.

## Bounds

| Knob | Value |
|---|---|
| upstream timeout passed to the adapter | `REACH_SEARCH_TIMEOUT` = 20 s (adapter clamps to 1–120 s, adds its own grace) |
| items requested / kept | `limit` (adapter clamps 1–50) |
| snippet | first 300 characters of upstream `text` (`REACH_SNIPPET_CHARS`) |
| upstream stdout | rejected by the adapter above 4 MB |
| item text / raw blob | truncated at 4000 chars / raw dropped above 2000 chars by the adapter |

## Attribution

A fallback success is never dressed as a native lane:

- `BackendResult.engine` / `SearchExecution.engine` = `agent_reach_<channel>_<action>`
  (for example `agent_reach_twitter_search`).
- `attempts` keeps the native names first, then the fallback name, then the
  upstream route labels (`agent_reach_github_search:github-api`,
  `agent_reach_web_search:exa/ok`).
- `attribution` = `Agent Reach (third-party CLI), forwarded by Hermes Trailhead`
  (the adapter's own attribution string when it supplies one).
- Snippets are leads, not extraction. Nothing here populates extracted content,
  and downstream extraction/scoring still has to run on the URL.

## Errors: recorded, actionable, non-fatal

Every failure is an empty result with an error string, never an exception, and
never a reason to discard what other lanes found:

| Situation | Attempt label | Error text includes |
|---|---|---|
| binary not configured / missing / not executable | `…_not_configured` | `not_configured`, the `TRAILHEAD_AGENT_REACH_BIN` hint |
| upstream said `ok: false` | `…_<upstream_code>` | Trailhead's class (`upstream_error`, `route_violation`, `timeout`, `malformed_output`, …), the upstream message, and its hint when present |
| payload without a public route | `…_auth_gate` | why authenticated forwarding is refused |
| adapter raised | `…_adapter_error` | exception type and message |
| `ok` but no usable URL | `…_no_matching_urls` | item count and how many were dropped by the lane's URL contract |

Because the error is prefixed with `optional agent-reach fallback for <lane> not
used […]`, a reader can tell a native failure from an upstream one at a glance.
When the native chain already produced a diagnosis, it is kept first and the
fallback reason is appended, so both are visible. An empty result's `engine`
stays the last **native** attempt — a failed fallback is recorded in
`attempts`, never credited as the engine that answered.

## Determinism in tests

The fallback is closed unless (a) an adapter is injected explicitly, (b) the
caller passes the explicit `allow_reach=True` signal, or (c) the public
`execute_search`/`execute_action` path runs with no injected `fetch` — that
boundary decides `trusted_runtime` and forwards `allow_native=allow_reach=True`
explicitly, because it always hands the chain a real fetcher object.

`execute_backend_chain` therefore does **not** infer "real runtime" from
`fetch is None`: `search.execute_action` always builds a fetcher, so a gate
keyed on `fetch is None` would make the fallback unreachable from the normal
CLI. Injectable `fetch` fixtures still default to `allow_reach=False`, so
existing deterministic tests are unaffected; a test that wants the fallback
either injects an adapter or opts in with `allow_reach=True`.
`tests/test_reach_search_fallback.py` covers the default CLI-shaped path
(operator env + mocked adapter factory + empty HTTP, no injected adapter), the
patched-fetcher fixture guard, native-success skip, unconfigured/PATH-only
skip, attributed success, the public/no-auth/no-quota gate, and
malformed/blocked/error paths.

```bash
.venv/bin/python -m pytest tests/test_reach_search_fallback.py -q
```
