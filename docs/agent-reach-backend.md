# Optional: Agent Reach backend

Trailhead's native lanes cover web, docs, GitHub, Reddit, X, YouTube transcripts,
and a browser/session tier. Some platforms are **not** native: Bilibili, V2EX,
Boss直聘, Xueqiu, Xiaohongshu, Xiaoyuzhou, and LinkedIn job detail. Agent Reach
(a third-party CLI) already exposes read-only accessors for those.

`hermes_trailhead/reach_backend.py` is an **optional forwarding layer** over an
Agent Reach install the operator already has. It is not a reimplementation, it
is not bundled, and nothing it returns is rebranded as native Trailhead output.

- No dependency is added to `pyproject.toml`.
- Nothing is installed, configured, updated, or logged in to.
- No browser, cookie jar, or profile is copied.
- Every result says it came from Agent Reach and lists the forwarding limits.

This is gap-closing by reuse: Trailhead gains platform/action breadth it does
not implement itself, while the evidence stays attributable.

## Discovery

Order, first hit wins:

1. An explicit `executable=` argument.
2. `TRAILHEAD_AGENT_REACH_BIN` (absolute path or a name resolved on `PATH`).
3. `shutil.which("agent-reach")`.

The resolved path must be an executable regular file, otherwise discovery
reports `found: false` with a reason (`explicit_missing`,
`explicit_not_executable`, `explicit_is_directory`, `not_installed`, ...).
There is no auto-install, no `pip install`, and no fallback download.

`TRAILHEAD_AGENT_REACH_HOME` optionally points the child process at a different
`HOME` in **consented authenticated mode** (for an isolated or throwaway
upstream config); when set, `XDG_*`, `APPDATA`, and `LOCALAPPDATA` are moved
inside that directory too, so the override really isolates the run. It is
ignored in public mode, which always uses its own throwaway `HOME`. The child environment is otherwise restricted to `PATH`,
locale, and temp variables — API keys, tokens, and browser configuration in the
parent environment are **not** forwarded in either mode.

## Public mode vs. consented authenticated mode

`AgentReachBackend(..., allow_authenticated=False)` is the default.

Routing is decided **per action**, never per channel. A channel declaring a
`session` or `browser` login does not make its public actions authenticated:
Bilibili declares a login for subtitles, yet `hot` and `read` are served by
public backends.

| Action route (upstream declaration) | Public mode (default) | `allow_authenticated=True` |
|---|---|---|
| action declares a public-web scope (`public_web` non-empty) | forced `--backend public-web`; upstream cannot fall back to a browser | normal route (a site tool or the browser may be used) |
| action declares a known public API backend (see `PUBLIC_API_BACKENDS`) | that backend is forced explicitly: `github-api`, `v2ex-api`, `bilibili-api`, `tencent` | normal route, no forcing |
| channel declares no login and no public-web scope (YouTube, web) | runs its declared backends | same |
| action is reachable only through a declared login | **`auth_required` error, nothing is spawned** | runs against the operator's existing upstream login |

A public-mode call never silently falls back to a browser or to a session
backend. When only a session route exists, the result is an explicit
`auth_required` error that says how to consent. Consent means "use the login
state I already created in Agent Reach"; it does not mean Trailhead creates,
refreshes, imports, or copies one.

If upstream renames a backend so the expected public label disappears from an
action's declared `backends`, the action stops being public (it is reported as
`auth_required` in public mode) instead of quietly running unforced.

### Public mode runs blind

In public mode the upstream process is started with a **private, empty
temporary `HOME`** created under `TMPDIR` (`tempfile.TemporaryDirectory`) and
removed when the call returns. `HOME`, `USERPROFILE`, `XDG_CONFIG_HOME`,
`XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `APPDATA`, and
`LOCALAPPDATA` all point inside that directory. Consequences, by design:

- `~/.agent-reach/config.yaml` (API keys, saved cookies) is not readable.
- `~/.config/gh/hosts.yml` and any other CLI credential store is not readable.
- `~/.agent-reach/sessions/<tool>/` logins are not usable.
- Operator tools installed under `~/.agent-reach/tools/` are not on the child's
  `PATH` either. A backend that needs one reports upstream's own `NEED_SETUP`
  (for example `bili is not installed`) rather than silently borrowing a
  credential — that failure is forwarded, not hidden.
- `TRAILHEAD_AGENT_REACH_HOME` and the operator's `HOME` are ignored.

Every public result carries `provenance.home_mode = "isolated-temp"` and a
limitation line stating that the upstream process could not see operator
config; consented runs report `home_mode = "operator"`.

## Forced-route verification

When a backend was pinned with `--backend`, a successful payload must report
that same backend. `public-web` accepts `public-web` and its
`public-web/<tool>` sub-labels; every other pin requires an exact match. A
mismatch (including a payload with no `backend`) returns
`error.code = "route_violation"`, `ok: false`, and **zero items** — content
from an unverified route is never returned as success. `provenance` keeps both
`forced_backend` and `reported_backend` for diagnosis.

## Forwarded surface

Only these read-only channel/action pairs can run. Anything else in the upstream
registry is rejected as `action_not_allowlisted` or `unknown_action`.

| Channel | Actions | Public route |
|---|---|---|
| `github` | `search`, `read` | forced `github-api` (`gh` needs `~/.config/gh`, so it is never used in public mode) |
| `v2ex` | `hot`, `node`, `read`, `user` | forced `v2ex-api` |
| `youtube` | `read`, `search`, `subtitle` | `yt-dlp` |
| `web` | `search`, `read` | `exa` / `jina` |
| `twitter` | `search`, `profile`, `tweets`, `thread` | `search` forced `public-web`; the rest need consent |
| `reddit` | `search`, `read`, `subreddit` | `search`/`read` forced `public-web`; `subreddit` needs consent |
| `facebook` | `search`, `profile` | `search` forced `public-web`; `profile` needs consent |
| `instagram` | `search`, `profile`, `posts` | consent only |
| `xiaohongshu` | `search`, `read`, `comments` | `search`/`read` forced `public-web`; `comments` needs consent |
| `linkedin` | `jobs`, `read` | forced `public-web` |
| `boss` | `search`, `read` | forced `public-web` |
| `bilibili` | `search`, `read`, `hot`, `subtitle` | `hot`/`read` forced `bilibili-api`; `search` forced `bili-cli` (login-free, but needs the tool installed); `subtitle` needs consent |
| `xueqiu` | `quote`, `search`, `hot_posts`, `hot_stocks` | `quote`/`search` forced `tencent` (public quote/search API); `hot_posts`/`hot_stocks` need consent |

Excluded on purpose:

- `transcribe` (YouTube, Xiaoyuzhou) — paid/key-consuming Whisper endpoints.
  Never run automatically; `xiaoyuzhou` therefore has no forwarded actions.
- All management verbs: `setup`, `add`, `remove`, `login`, `logout`, `browser`,
  `configure`, `update`, `uninstall`, `skill`, `doctor`, `check`, `version`.
  They are rejected as `forbidden_command` before a process exists.

## Safety invariants

- **Argument arrays only, `shell=False`.** The upstream command is
  `[exe, channel, action, *options, "--backend", ..., "--timeout", ..., "--", *positionals]`.
  Options precede `--`; every positional follows it, so a target cannot become
  a flag even if upstream's parser changes.
- **Unsafe positionals rejected.** A value starting with `-`, containing a
  control character, or longer than `MAX_VALUE_CHARS` is refused with
  `unsafe_target` / `invalid_params`.
- **URL schemes validated.** `javascript:`, `data:`, `file:`, `ftp:`, `gopher:`,
  `smb:`, `telnet:`, `vbscript:`, `about:`, `chrome:` are rejected everywhere.
  Target-like params (`target`, `url`, `link`, `href`, `repo`) must be `http(s)`
  URLs or bare identifiers, and URLs with embedded credentials are refused.
  Bare identifiers (`owner/repo`, `t=1252479`) pass through byte-for-byte.
- **Registry is untrusted input.** The `agent-reach channels` payload is checked
  for schema version, `ok`, channel/action/param name shape, duplicate names,
  param types, backend labels, and public-web prefixes. Malformed output is
  `registry_invalid`, not a best-effort guess. The validated registry is cached
  for the process lifetime (`refresh=True` re-reads).
- **Bounded.** `limit` is clamped to 1–50, `timeout` to 1–120 s (with a grace
  window so upstream can emit its own JSON timeout), item counts are capped,
  item text is truncated to 4000 characters, oversized `raw` blobs are dropped,
  and oversized stdout is rejected.
- **No mutation of upstream state.** Nothing here writes config, sessions,
  cookies, or the upstream registry.
- **No route substitution.** A pinned backend must be the reported backend of a
  successful payload (`route_violation` otherwise), and a public-mode call that
  cannot use a public route returns `auth_required` without spawning.
- **Public mode cannot read operator credentials.** The child `HOME` is a fresh
  temporary directory that is removed after the call, including on timeout and
  upstream error.

## Result shape

`AgentReachBackend.execute(channel, action, params, ...)` returns a
`ReachResult`; `.to_dict()` emits:

```json
{
  "ok": true,
  "engine": "agent-reach",
  "channel": "github",
  "action": "search",
  "backend": "github-api",
  "items": [{"title": "...", "url": "https://github.com/...", "author": "...",
             "published_at": "...", "text": "...", "text_truncated": false,
             "raw": {...}, "url_rejected": false}],
  "error": null,
  "provenance": {
    "engine": "agent-reach",
    "native": false,
    "attribution": "Agent Reach (third-party CLI), forwarded by Hermes Trailhead",
    "executable": "/path/to/agent-reach",
    "schema_version": 1,
    "route": "public_api",
    "public_only": true,
    "requested": "github search",
    "reported_backend": "github-api",
    "forced_backend": "github-api",
    "home_mode": "isolated-temp"
  },
  "limitations": [
    "Items are produced by the third-party Agent Reach CLI and forwarded by Trailhead without native scoring or extraction.",
    "Trailhead never installs, configures, updates, or logs in to Agent Reach.",
    "Public-only mode: no authenticated session and no browser fallback were used.",
    "The upstream process ran with a private empty HOME; operator config, login state, and stored credentials were not visible to it."
  ],
  "elapsed_ms": 332,
  "attempts": [{"backend": "github-api", "result": "ok", "message": null}],
  "exit_code": 0,
  "timed_out": false,
  "argv": ["/path/to/agent-reach", "github", "search", "--limit", "2",
           "--backend", "github-api", "--timeout", "20", "--", "url shortener"]
}
```

Notes for consumers:

- `engine` is always `agent-reach`; there is no field that claims native origin.
- `attempts` is the upstream's own backend chain, including failed attempts.
  In public mode the chain is a single pinned backend, because that is what was
  asked for; `NEED_SETUP` rows only appear in consented runs.
- `provenance.forced_backend` is the label Trailhead pinned (or `null` when
  nothing was pinned); `provenance.reported_backend` is what upstream claimed,
  and the two must agree for `ok: true`.
- `provenance.home_mode` is `"isolated-temp"` in public mode and `"operator"`
  once the caller consents to using the existing login state.
- `error.code` is Trailhead's classification (`not_configured`,
  `registry_invalid`, `unknown_channel`, `unknown_action`,
  `action_not_allowlisted`, `forbidden_command`, `auth_required`,
  `invalid_params`, `unsafe_target`, `route_violation`, `timeout`,
  `process_error`, `malformed_output`, `upstream_error`). For
  `upstream_error`, `error.upstream_code` preserves the upstream code verbatim.
- Failures still carry `provenance` and `limitations`, so an empty result is
  never confused with a native one.

## Suggested CLI integration

`cli.py` (owned separately) can use:

```python
backend = AgentReachBackend()            # discovery via env / PATH
if backend.available():
    print(json.dumps(backend.describe(), indent=2))   # capabilities + reason
    result = backend.execute("v2ex", "hot", {"limit": 10})
```

`describe()` and `capabilities()` never touch the network beyond
`agent-reach channels`. Expose the backend only when the operator asks for it
(e.g. `--agent-reach`); a missing executable must degrade to "not configured",
never to an install prompt inside a search run.

## Verification (pinned upstream, public routes only)

Checked against Agent Reach `v1.6.0` at commit
`14c213405669414492bda0f8d52cc6531d062c45`, isolated venv, public mode (empty
temporary `HOME`, operator `HOME` deliberately set so the isolation was real —
`~/.config/gh/hosts.yml` exists on this host):

| Call | Pinned backend | Observed |
|---|---|---|
| `github search "url shortener" --limit 2` | `github-api` | `ok`, 2 repos, `home_mode=isolated-temp` |
| `v2ex hot --limit 2` | `v2ex-api` | `ok`, 2 topics |
| `bilibili hot --limit 2` | `bilibili-api` | `ok`, 2 videos (public HTTP API, no login) |
| `xueqiu quote SH600519` | `tencent` | `ok`, 1 item with live quote fields |
| `bilibili search "rust"` | `bili-cli` | `upstream_error` / `NEED_SETUP` — `bili is not installed`; the isolated `HOME` has no `~/.agent-reach/tools`, and the failure is reported rather than hidden |
| `twitter search "hermes agent"` | `public-web` | `upstream_error` / `UPSTREAM_BROKEN` (`Public web returned no usable content in the requested scope`), no browser fallback |
| `reddit search "python asyncio" --limit 2` | `public-web` | `ok`, 2 items; payload reported `backend: "public-web"`, which is the accepted pinned label |
| `bilibili subtitle <bv>` | — (none) | `auth_required`, no process spawned |
| `xueqiu hot_posts` | — (none) | `auth_required`, no process spawned |

Coverage gained by this pass, honestly stated: four additional public routes
(GitHub search/read, V2EX, Bilibili hot/read, Xueqiu quote/search) now work in
public mode, where the previous channel-level gate rejected Bilibili and Xueqiu
outright. This is not a claim of beating any other tool end to end; it is the
public, login-free subset of upstream's own backends, with the failures above
left visible.

No transcription action was run. No upstream login, install, or configuration
command was invoked, and no operator credential was read.

Run the focused suite:

```bash
.venv/bin/python -m pytest tests/test_reach_backend.py -q
```
