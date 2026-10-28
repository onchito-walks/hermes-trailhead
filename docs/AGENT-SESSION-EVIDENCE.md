# Agent-session evidence: `read` and `reach-call` interoperability

Status: **observations from one fresh agent session. Not a benchmark and not a
claim about Agent Reach quality.** Every fact below was produced by invoking the
packaged CLI from a clean context — `python -m hermes_trailhead …` — and parsing
its stdout. No `hermes_trailhead` module was imported by the evidence run, and no
Hermes/model/paid subprocess was started.

Session: 2026-10-28, fresh subagent with no prior conversation context, working
copy at `2fb3847` plus uncommitted changes, `hermes-trailhead 1.1.0`,
Python 3.11.15, Linux aarch64. Raw stdout/stderr for each run was written to an
out-of-tree scratch directory; only the observations are recorded here.

## 1. Capability discovery with `--help`

`python -m hermes_trailhead --help` listed 17 subcommands:

```
doctor, queue, plan, capability-radar, agent-brief, routes, route,
reliability, benchmark, gauntlet, score, reach, reach-call, compare,
search, report, read
```

`read --help` printed:

```
usage: hermes-trailhead read [-h] [--format {text,json}] [--timeout SECONDS] url
```

and documented the contract the implementation was then checked against:
absolute `http(s)` URL only, native extractor, Agent Reach not used, paid ASR
force-disabled, model-backed `web_extract` not used, exit `0` usable / `1`
blocked-or-unusable / `2` invalid URL or timeout, and `error.code` one of
`invalid_url`, `invalid_timeout`, `extraction_blocked`, `extraction_error`,
`extraction_not_attempted`, `unusable_evidence`, `internal_error`.

`reach --help` and `reach-call --help` documented the consent surface:
authenticated forwarding needs `--allow-authenticated`; transcription
additionally needs `--allow-quota-consuming`; `TRAILHEAD_DISABLE_ASR=1` still
vetoes it. The `reach-call` help text states that session-only actions return
`auth_required` unless `--allow-authenticated` is passed explicitly.

## 2. Native `read` of public docs and GitHub (real network)

```bash
.venv/bin/python -m hermes_trailhead read "https://docs.python.org/3/library/json.html" \
  --format json --timeout 30
.venv/bin/python -m hermes_trailhead read "https://github.com/psf/requests" \
  --format json --timeout 30
```

| Observed field | Python docs | GitHub repo |
|---|---|---|
| exit | `0` | `0` |
| stderr bytes | `0` | `0` |
| `ok` | `true` | `true` |
| `source_type` | `"docs"` | `"github"` |
| `extraction_status` | `"ok"` | `"ok"` |
| `content_length` / `returned_chars` | `20004` / `20004` | `3118` / `3118` |
| `truncated` | `true` (readable-text cap note) | `false` |
| `error` | `null` | `null` |
| `evidence.usable` / `transport_ok` | `true` / `true` | `true` / `true` |
| `evidence.relevance` | `"unknown"` | `"unknown"` |
| `evidence.source_quality` | `{"quality":"canonical","score":80,…}` | `{"quality":"canonical","score":75,…}` |
| `asr.enabled` / `policy.agent_reach` | `false` / `"not_used"` | `false` / `"not_used"` |
| content head | `json — JSON encoder and decoder …` | `GitHub repository: psf/requests …` |

Both payloads carried the same 17 top-level keys and the same 5 `evidence`
keys; `read` credential handling was exercised on the same build in §3.

## 3. Rejected URLs: no credential echo, generic parser message

```bash
.venv/bin/python -m hermes_trailhead read "http://user:SECRET@example.com:bad/" --format json
# exit 2, stderr empty
```

Observed payload (abridged to the fields that matter):

```json
{
  "ok": false,
  "url": "http://example.com:bad/",
  "extraction_status": "not_attempted",
  "content": "",
  "error": {
    "code": "invalid_url",
    "message": "URL could not be parsed; check the scheme, host, and port"
  }
}
```

- `SECRET` did not appear in stdout or stderr.
- Text mode (`read "http://user:SECRET@example.com:bad/"`, no `--format`)
  exited `2`, wrote **0 bytes to stdout**, and its stderr showed
  `URL: http://example.com:bad/` and the same generic `invalid_url` message —
  no secret.
- Malformed IPv6 bracket: `read "http://[::1" --format json` exited `2` with
  `url: "http://[::1"` (nothing credential-shaped to hide) and the same generic
  message; no traceback.

A 15-input CLI fuzz of malformed authorities — malformed port, out-of-range
port, unbalanced bracket, password containing `@`, empty host, embedded
whitespace, `ftp://`, scheme-less credentials, protocol-relative credentials,
and empty string — produced, for every input:

| Property | Result |
|---|---|
| exit code | `2` for all 15 |
| stdout | valid single JSON object for all 15 |
| `error.code` | `invalid_url` for all 15 |
| `SECRET` / `user:` in stdout+stderr | absent for all 15 |
| stderr bytes | `0` for all 15 |

Representative echoes: `http://user:SECRET@example.com:bad/` →
`http://example.com:bad/`; `https://user:SECRET@example.com:99999/` →
`https://example.com:99999/`; `http://user:SECRET@[::1` → `http://[::1`;
`https://user:p@ss:SECRET@example.com:bad/` → `https://example.com:bad/`;
`user:SECRET@example.com/path` → `example.com/path`;
`//user:SECRET@example.com/x` → `//example.com/x`.

Pre-fix comparison: a scratch copy of the package with the previous
`_read_display_url` (which returned the raw string on `ValueError`) and the
previous `f"URL could not be parsed: {exc}"` message, invoked through the same
CLI, returned `url: "http://user:SECRET@example.com:bad/"` and
`message: "URL could not be parsed: Port could not be cast to integer value as
'bad'"` — i.e. the password leaked. The current build returns the redacted URL
and the fixed message for the same command.

## 4. Consent-gated `reach-call` without enabling flags

```bash
.venv/bin/python -m hermes_trailhead reach --format json
# exit 0
```

Observed inventory facts (no Agent Reach installed on this host):

| Field | Value |
|---|---|
| `found` / `executable` | `false` / `null` |
| `error` | `{"code":"not_configured","message":"agent-reach is not installed or not discoverable"}` |
| `public_only` | `true` |
| `authenticated_allowed` | `false` |
| `quota_consuming_allowed` | `false` |
| `quota_ready` | `false` |
| `credential_source` | `"upstream-home-config"` |
| pinned parity reference | Agent Reach 1.6.0, commit `14c2134…`, 14 channels / 40 actions |
| parity gates | `public: 26`, `gated_auth: 12`, `gated_quota: 2`, `surfaced_ratio: 1.0` |

`reach-call` runs, all with **no consent flags**:

| Command | Exit | `error.code` | Other observed fields |
|---|---|---|---|
| `reach-call twitter profile nasa --format json` | `1` | `not_configured` | `ok:false`, `items:[]`, `provenance.public_only:true`, `executable:null` |
| `reach-call youtube transcribe <url> --format json` | `1` | `quota_required` | `provenance.quota_consuming:true`, `public_only:true`, 0 items |
| same, plus `--allow-quota-consuming` only | `1` | `auth_required` | message: quota flag is not enough; `--allow-authenticated` also required |

No run emitted stderr, and none forwarded to an upstream: the executable was
absent, the quota veto fired before availability/registry lookup, and
`provenance.public_only` stayed `true` in every refusal. This is the
consent-first behavior the help text promises, observed rather than assumed.

## 5. Interoperability contract an agent can depend on

1. **One JSON object on stdout.** `--format json` emits exactly one parseable
   object for success, extraction failure, and invalid input alike; stderr is
   empty in JSON mode.
2. **Exit codes are the coarse signal.** `0` = usable evidence; `1` = ran or
   refused forwarding, no usable evidence; `2` = caller error (URL/timeout).
   `ok` is the authoritative boolean, not stdout length.
3. **Stable shape.** Success and `invalid_url` payloads from this session had
   identical key sets:
   `asr, command, content, content_length, error, evidence, extraction_status,
   ok, policy, returned_chars, schema_version, source_type, timeout_seconds,
   truncated, truncation_note, url, video_evidence`, with
   `evidence = {usable, transport_ok, relevance, reasons, source_quality}`.
4. **`error` is `null` on success** and `{code, message}` otherwise; branch on
   `error.code` after `ok`.
5. **`policy`/`asr` are constant declarations**: `agent_reach: "not_used"`,
   `asr: "disabled"`, `hermes_web_extract: "disabled"`, paid ASR never invoked.
6. **`url` is display-safe.** It never contains userinfo, and parse failures
   never surface the parser's exception text; consumers may log it.
7. **Forwarding is opt-in and refusal-first.** Without consent flags,
   `reach-call` returns a coded refusal (`quota_required`, `auth_required`, or
   `not_configured`) with `ok:false`, zero items, and `public_only:true`; it
   does not silently fall back to an authenticated or paid route.

## 6. Limits of this evidence

- Agent Reach is **not installed** on this host, so authenticated forwarding was
  never exercised and the non-quota `auth_required` branch (for example
  `twitter profile`) was not reachable; that run correctly returned
  `not_configured` before the auth-mode check. The 12 consent-gated actions are
  known from the CLI's pinned parity inventory, not from a live forwarded call.
- One read per URL, one network moment; no retries, no concurrency, no
  cross-host comparison. Content counts are what the extractor returned, not a
  completeness proof.
- No model, Hermes chat, ASR, paid endpoint, or credential-bearing request was
  made during this session. No commit or push was performed.

## 7. Reproduction

```bash
cd <repo>
.venv/bin/python -m hermes_trailhead --version
.venv/bin/python -m hermes_trailhead read --help
.venv/bin/python -m hermes_trailhead reach --help
.venv/bin/python -m hermes_trailhead reach-call --help
.venv/bin/python -m hermes_trailhead read "https://docs.python.org/3/library/json.html" --format json --timeout 30
.venv/bin/python -m hermes_trailhead read "https://github.com/psf/requests" --format json --timeout 30
.venv/bin/python -m hermes_trailhead read "http://user:SECRET@example.com:bad/" --format json
.venv/bin/python -m hermes_trailhead read "http://[::1" --format json
.venv/bin/python -m hermes_trailhead read "user:SECRET@example.com/path" --format json
.venv/bin/python -m hermes_trailhead reach --format json
.venv/bin/python -m hermes_trailhead reach-call twitter profile nasa --format json
.venv/bin/python -m hermes_trailhead reach-call youtube transcribe "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --format json
```

Verification for the code change: `python3 -m py_compile hermes_trailhead/*.py`;
`.venv/bin/python -m pytest -q tests/test_cli_read.py` → **45 passed**;
`.venv/bin/python -m pytest -q` → **734 passed** (2026-10-28T13:28Z; the
repository suite also grows as other workers land their own tests).
