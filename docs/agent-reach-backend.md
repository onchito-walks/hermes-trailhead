# Optional: Agent Reach backend

Trailhead's native lanes cover web, docs, GitHub, Reddit, X, YouTube transcripts,
and a browser/session tier. Some platforms are **not** native: Bilibili, V2EX,
Boss直聘, Xueqiu, Xiaohongshu, Xiaoyuzhou, and LinkedIn job detail. Agent Reach
(a third-party CLI) already exposes read-only accessors for those.

The complete pinned surface is inventoried in
[`ACTION-PARITY.md`](ACTION-PARITY.md): 40 actions across 14 channels, with
native / native-partial / upstream coverage, public / consent / quota gates, and
fixture-versus-live evidence kept separate.

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

Keys are never handed over as environment variables. Consented mode forwards
the operator's `HOME`/`XDG_*` **paths** so the already-configured upstream CLI
can read its own config/key store (`~/.agent-reach/config.yaml`); that store,
not Trailhead's environment, is the only credential source.
`describe()["credential_source"]` reports `upstream-home-config`.

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

### Quota gate: transcription is visible but never automatic

`youtube transcribe` and `xiaoyuzhou transcribe` are in the discoverable
inventory and in `capabilities()`, with `gate: "quota"`,
`quota_consuming: true`, and `blocked_by_default: true`. They are **not** in
`READ_ONLY_ACTION_ALLOWLIST`, so no read-only path can reach them.

Running one requires three separate things:

1. `allow_quota_consuming=True` (`--allow-quota-consuming`) — consent to spend
   Whisper/Groq/OpenAI quota. Without it: `quota_required`, nothing spawned.
2. `allow_authenticated=True` (`--allow-authenticated`) — the Whisper backends
   read the operator's configured key. With only the quota flag:
   `auth_required`, nothing spawned.
3. `TRAILHEAD_DISABLE_ASR` unset. `1`, `true`, `yes`, or `on` vetoes the call
   even when both flags are present (`asr_disabled`, nothing spawned). This is
   the same process-wide veto the native media ASR tier uses, and it is an
   **OR**: the flag is read from the real process environment *and* from any
   caller-supplied `env` mapping. Passing `env={}` (or one without the key)
   cannot clear a veto that holds for the process; an override can only add a
   veto, never remove one.

A quota call pins no backend, runs with the operator's `HOME` (consent mode),
and carries `provenance.quota_consuming = true` plus a limitation stating that
Trailhead did not meter or cap the spend. Normal `search` has no flag, code
path, or import that can reach this gate.

`describe()` keeps consent and readiness apart:

| Field | Meaning |
|---|---|
| `quota_consuming_allowed` | did this run pass `--allow-quota-consuming`? |
| `authenticated_allowed` | did this run pass `--allow-authenticated`? |
| `asr_disabled` / `asr_vetoed` | is the process-wide veto on? |
| `quota_ready` | could a quota call run *now*: quota consent **and** auth consent **and** no veto |
| `credential_source` | always `upstream-home-config` |

`quota_ready: true` alone is not a licence to call a paid action; the flags
still have to be passed to `execute()`/`reach-call`.

A refused quota call spawns **no process at all**, not even the harmless
`agent-reach channels` registry read: the CLI's positional-argument mapping is
skipped while a gate is closed, and `execute()` checks the ASR veto and both
consent flags before discovery. This is asserted by a test that uses a stub
executable which writes a marker file on any invocation.

If upstream renames a backend so the expected public label disappears from an
action's declared `backends`, the action stops being public (it is reported as
`auth_required` in public mode) instead of quietly running unforced.

### Public mode runs with an isolated environment (not a sandbox)

In public mode the upstream process is started with a **private, empty
temporary `HOME`** created under `TMPDIR` (`tempfile.TemporaryDirectory`) and
removed when the call returns. `HOME`, `USERPROFILE`, `XDG_CONFIG_HOME`,
`XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `APPDATA`, and
`LOCALAPPDATA` all point inside that directory. Consequences, by design:

- `~/.agent-reach/config.yaml` is not on the child's `HOME` path, so a tool that
  resolves config through `HOME` finds nothing.
- `~/.config/gh/hosts.yml` and other `HOME`/`XDG`-resolved credential stores are
  not resolved either.
- `~/.agent-reach/sessions/<tool>/` logins are not reachable through `HOME`.
- Operator tools installed under `~/.agent-reach/tools/` are not on the child's
  `PATH`. A backend that needs one reports upstream's own `NEED_SETUP` (for
  example `bili is not installed`) rather than silently borrowing a
  credential — that failure is forwarded, not hidden.
- `TRAILHEAD_AGENT_REACH_HOME` and the operator's `HOME` are ignored.

**This is environment isolation, not a filesystem or process sandbox.** The
child still runs as the same user with the same network access, and a program
that hard-codes an absolute path (or receives one as an argument) can read any
file that user can read. Trailhead does not claim otherwise, and no security
boundary should be inferred from the empty `HOME`, the redirected `XDG_*`
variables, or the removed temporary directory. Use OS-level isolation (a
container, a separate user, or a VM) when the threat model includes a hostile
upstream binary.

Every public result carries `provenance.home_mode = "isolated-temp"` and a
limitation line stating that the upstream process could not resolve operator
config through its environment; consented runs report `home_mode = "operator"`.

## Forced-route verification

When a backend was pinned with `--backend`, a successful payload must report
that same backend. `public-web` accepts `public-web` and its
`public-web/<tool>` sub-labels; every other pin requires an exact match. A
mismatch (including a payload with no `backend`) returns
`error.code = "route_violation"`, `ok: false`, and **zero items** — content
from an unverified route is never returned as success. `provenance` keeps both
`forced_backend` and `reported_backend` for diagnosis.

## Forwarded surface

Only these channel/action pairs can run. The first thirteen channels are the
read-only surface; `xiaoyuzhou` appears only through its quota gate. Anything
else in the upstream registry is rejected as `action_not_allowlisted` or
`unknown_action`.

| Channel | Actions | Public route |
|---|---|---|
| `github` | `search`, `read` | forced `github-api` (`gh` needs `~/.config/gh`, so it is never used in public mode) |
| `v2ex` | `hot`, `node`, `read`, `user` | forced `v2ex-api` |
| `youtube` | `read`, `search`, `subtitle`, `transcribe` | `read`/`search`/`subtitle` run on `yt-dlp`; `transcribe` is quota-gated (see below) |
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
| `xiaoyuzhou` | `transcribe` | quota-gated only: needs `--allow-quota-consuming` **and** `--allow-authenticated`; never public |

Excluded on purpose:

- `transcribe` (YouTube, Xiaoyuzhou) is **discoverable but blocked by default**.
  It is absent from `READ_ONLY_ACTION_ALLOWLIST`, needs both consent flags, and
  is vetoed by `TRAILHEAD_DISABLE_ASR=1`. It never runs in a normal search.
- All management verbs: `setup`, `add`, `remove`, `login`, `logout`, `browser`,
  `configure`, `update`, `uninstall`, `skill`, `doctor`, `check`, `version`.
  They are rejected as `forbidden_command` before a process exists.

## Safety invariants

- **Argument arrays only, `shell=False`.** The upstream command is
  `[exe, channel, action, *options, "--backend", ..., "--timeout", ..., "--", *positionals]`.
  Options precede `--`; every positional follows it, so a target cannot become
  a flag even if upstream's parser changes.
- **Unsafe positionals rejected.** For `str` target parameters, a value starting
  with `-`, containing a control character, or longer than `MAX_VALUE_CHARS` is
  refused with `unsafe_target` / `invalid_params`. A declared `float` may be
  negative: it follows `--name`, not the `--` terminator, so it cannot become a
  flag.
- **URL schemes validated.** `javascript:`, `data:`, `file:`, `ftp:`, `gopher:`,
  `smb:`, `telnet:`, `vbscript:`, `about:`, `chrome:` are rejected everywhere.
  Target-like params (`target`, `url`, `link`, `href`, `repo`) must be `http(s)`
  URLs or bare identifiers, and URLs with embedded credentials are refused.
  Bare identifiers (`owner/repo`, `t=1252479`) pass through byte-for-byte.
- **Registry is untrusted input.** The `agent-reach channels` payload is checked
  for schema version, `ok`, channel/action/param name shape, duplicate names,
  param types, backend labels, and public-web prefixes. Malformed output is
  `registry_invalid`, not a best-effort guess. The validated registry is cached
  **per process** — `_REGISTRY_CACHE`, LRU-bounded to 8 entries, keyed by
  `(absolute executable, public-mode flag, env-identity digest, runner)`.
  `refresh=True`, `clear_registry_cache()`, or a process restart re-reads it.
  Consequence, stated rather than hidden: a long-lived process keeps the
  inventory it first validated, so an upstream channel/action change is masked
  until one of those happens. That is **inventory staleness, not a credential or
  sandbox property**: public and authenticated discovery never share an entry
  (different `HOME`), a failed or malformed discovery is never cached, and
  consent flags, `HOME` mode, `max_items` and `timeout` stay per call. Design and
  measurements: [`MAINTENANCE-FOLLOWUP.md`](MAINTENANCE-FOLLOWUP.md).
- **Declared parameter types are coerced, not stringified.** `str` and `int`
  keep their existing rules (the `limit` 1–50 clamp; leading `-`, control
  characters and URL schemes refused). A declared `bool` accepts a native
  boolean and the strings `true/false/yes/no/1/0` (canonicalised); `1`, `0`,
  `1.0`, `"maybe"`, lists and mappings are refused. A declared `float` accepts
  finite numbers and decimal strings, is bounded to `MAX_FLOAT_PARAM` (`1e12`),
  and rejects `nan`, `±inf`, `1e999`, `"1_000"` and `"0x10"` as
  `invalid_params` before `build_argv` runs. A negative float is legitimate
  because it follows `--name`; only `str` targets refuse a leading `-`.
- **Bounded.** `limit` is clamped to 1–50 and `timeout` to 1–120 s. One call has
  **one wall clock**: `timeout + grace` is the aggregate deadline, and shared
  discovery is charged against it (`min(grace + 30 s, deadline − now)`); the
  action then gets only the remaining budget. A slow `agent-reach channels`
  read therefore cannot push the call past the advertised deadline, and a
  deadline already spent starts no action. Item counts are capped, item text is
  truncated to 4000 characters, oversized `raw` blobs are dropped, and oversized
  stdout is rejected.
- **Untrusted error text is redacted (best effort).** Registry stderr,
  execution stderr, upstream `error` fields (`code`, `message`, `hint`), and
  `meta.attempts` rows are passed through pattern redaction for common
  API-key/token/bearer shapes (`sk-…`, `ghp_…`, `github_pat_…`, `xox?-…`,
  `AKIA…`, `AIza…`, `gsk_…`, JWTs) and for `scheme://user:password@host` URLs.
  Redaction runs before truncation so a cut cannot leave a partial token. This
  is pattern redaction of known shapes, **not** a guarantee: an upstream that
  prints a secret in an unrecognized format still gets through.
- **No mutation of upstream state.** Nothing here writes config, sessions,
  cookies, or the upstream registry.
- **No route substitution.** A pinned backend must be the reported backend of a
  successful payload (`route_violation` otherwise), and a public-mode call that
  cannot use a public route returns `auth_required` without spawning.
- **Public mode is not handed operator credential paths — and is not a
  sandbox.** The child `HOME` is a fresh temporary directory removed after the
  call, including on timeout and upstream error, and `XDG_*`/`APPDATA` are
  redirected into it. A same-user process can still open any absolute path it
  knows, so this is environment isolation only; it is not a filesystem or
  process security boundary.

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
    "quota_consuming": false,
    "requested": "github search",
    "reported_backend": "github-api",
    "forced_backend": "github-api",
    "home_mode": "isolated-temp"
  },
  "limitations": [
    "Items are produced by the third-party Agent Reach CLI and forwarded by Trailhead without native scoring or extraction.",
    "Trailhead never installs, configures, updates, or logs in to Agent Reach.",
    "Public-only mode: no authenticated session and no browser fallback were used.",
    "The upstream process ran with a private empty HOME and redirected config/cache variables; that is environment isolation, not a filesystem sandbox, so operator files remain readable by absolute path."
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
- `provenance.quota_consuming` is `true` only for the double-gated transcription
  actions; those rows also carry `route: "quota"` and the quota limitation.
- `error.code` is Trailhead's classification (`not_configured`,
  `registry_invalid`, `unknown_channel`, `unknown_action`,
  `action_not_allowlisted`, `forbidden_command`, `auth_required`,
  `quota_required`, `asr_disabled`, `invalid_params`, `unsafe_target`,
  `route_violation`, `content_unusable`, `timeout`, `process_error`,
  `malformed_output`, `upstream_error`). For `upstream_error`,
  `error.upstream_code` preserves the upstream code verbatim. For
  `content_unusable`, `error.withheld_items` and `error.reasons`
  (`"blocked"` / `"missing_page"` / `"empty_body"`) say why the forwarded body was rejected.
- Failures still carry `provenance` and `limitations`, so an empty result is
  never confused with a native one.

## Detail reads must return content, not a shell

A detail read (`read`, `thread`, `comments`) is a claim about the artifact at
that URL. Upstream sometimes answers `ok: true` with the page it actually
fetched — a network-security block, a 404, a localized "页面不见了" placeholder —
and forwarding that as items is a false success. So:

- Forwarded item bodies go through the same classifier as extraction
  (`extract.classify_page_shell`): `"blocked"` for access interstitials,
  `"missing_page"` for 404s in any of the localizations LinkedIn/Xiaohongshu
  return. The test is deliberately conservative — a long article that merely
  *discusses* 404 pages is kept.
- Withheld rows are dropped from `items` and named in `limitations`
  (`N item(s) were withheld ...`); usable rows in the same response still come
  back with `ok: true`, so a mixed response is reported truthfully rather than
  discarded whole.
- If every row was a shell, the result is `ok: false`, `error.code =
  "content_unusable"`, zero items, with `provenance` and `attempts` intact.
- Metadata-only actions (`v2ex user`, `bilibili hot`, `xueqiu search`, `quote`,
  `jobs`, `search`, ...) are untouched: empty `text` with structured `raw` is
  their normal shape, and a discovery snippet is a lead, never a
  complete-artifact claim.

## Suggested CLI integration

`cli.py` uses:

```python
backend = AgentReachBackend()            # discovery via env / PATH
if backend.available():
    print(json.dumps(backend.describe(), indent=2))   # capabilities + parity
    result = backend.execute("v2ex", "hot", {"limit": 10})
# Paid transcription is a separate, explicit decision:
result = backend.execute(
    "youtube", "transcribe", {"target": url},
    allow_quota_consuming=True, allow_authenticated=True,
)
```

`describe()` and `capabilities()` never touch the network beyond
`agent-reach channels`; `parity_inventory()` is fully static. Expose the backend
only when the operator asks for it (e.g. `--agent-reach`); a missing executable
must degrade to "not configured", never to an install prompt inside a search
run. `hermes-trailhead reach` prints the full pinned inventory, including the
quota rows and their gates.

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

The pinned 40-action inventory ([`ACTION-PARITY.md`](ACTION-PARITY.md)) labels
exactly these five rows `live`, each backed by its own row in the per-call table
above — `github search`, `reddit search`, `bilibili hot`, `v2ex hot`,
`xueqiu quote`.

`github read`, `bilibili read`, and `xueqiu search` were previously labelled
`live` from an aggregate statement in `SUPERIORITY-ACCEPTANCE.md` rather than a
recorded per-call run; they are now `fixture`/`native-tests` only. The remaining
35 rows are also fixture/native contract-test evidence: contract tests with a
fake CLI, which is **not** live evidence. No aggregate summary promotes a row;
record a fresh run first.

No transcription action was run in this or the earlier pass. No upstream login,
install, or configuration command was invoked, and no operator credential was
read. Adding the quota gate is code and contract tests only; it produces no
transcript and spends no quota.

Run the focused suites:

```bash
.venv/bin/python -m pytest tests/test_reach_backend.py tests/test_cli_reach.py -q
```
