# Known-URL reading (`hermes-trailhead read`)

`read` answers the question an agent actually has after discovery: *given this
one URL, is there usable evidence behind it?* It is the native counterpart to
the optional Agent Reach forwarding layer and does not need search, a query, an
upstream install, a login, or a paid API.

Acceptance context: `docs/SUPERIORITY-ACCEPTANCE.md` dimension 9 requires a
stable JSON/error contract, discoverable capabilities **and known-URL reading**
verified through an agent session. This command is that surface.

```bash
hermes-trailhead read URL [--format text|json] [--timeout SECONDS]
python3 -m hermes_trailhead read URL --format json
```

## Examples

```bash
# Human summary plus the readable text
hermes-trailhead read https://example.com

# Machine contract (stdout is always valid JSON, success or failure)
hermes-trailhead read https://docs.python.org/3/library/json.html --format json

# Tighter network budget for a flaky host
hermes-trailhead read https://example.com --timeout 8 --format json

# Scripting: distinguish unusable evidence from a usage error
hermes-trailhead read https://example.com --format json > out.json || echo "exit=$?"
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Extraction returned **usable evidence** (`ok: true`) |
| `1` | URL was valid and extraction ran, but evidence is blocked, failed, or unusable |
| `2` | Usage error: invalid URL or `--timeout` outside `1`–`120` seconds |

A valid URL that yields nothing is not a crash; it is exit `1` with a coded
error. Do not rely on stdout being non-empty as a success signal — read `ok`.

## JSON contract (schema_version 1)

Every outcome — success, blocked, failed, invalid input — returns the **same
top-level keys**. `error` is `null` on success and an object otherwise.

```json
{
  "command": "read",
  "schema_version": 1,
  "ok": true,
  "url": "https://example.com",
  "source_type": "web",
  "timeout_seconds": 15,
  "asr": {
    "enabled": false,
    "env": "TRAILHEAD_DISABLE_ASR",
    "note": "read never invokes paid ASR"
  },
  "policy": {
    "agent_reach": "not_used",
    "asr": "disabled",
    "hermes_web_extract": "disabled",
    "public_tiers": "direct/proxy HTTP, Jina Reader, native platform public APIs"
  },
  "extraction_status": "ok",
  "content_length": 156,
  "returned_chars": 156,
  "truncated": false,
  "truncation_note": "",
  "content": "This domain is for use in documentation examples ...",
  "error": null,
  "evidence": {
    "usable": true,
    "transport_ok": true,
    "relevance": "unknown",
    "reasons": [],
    "source_quality": {
      "quality": "generic",
      "score": 35,
      "reasons": ["Generic web page"],
      "label": "Generic web page"
    }
  },
  "video_evidence": null
}
```

| Field | Meaning |
|---|---|
| `url` | The normalized URL that was read (credentials are masked/refused) |
| `source_type` | `web`, `docs`, `github`, `reddit`, `x`, `youtube`, `tiktok`, `instagram`, `forum`, `pdf`, `unknown`, or `""` before extraction |
| `timeout_seconds` | Integer network budget used for this run |
| `asr` | Always `enabled: false`; the environment variable is set only for the extraction |
| `policy` | Which fallback tiers were allowed; see “Fallbacks” below |
| `extraction_status` | Extractor transport status: `ok`, `blocked`, `error`, `not_attempted` |
| `content_length` | Characters the extractor measured (see truncation semantics) |
| `returned_chars` | Characters actually present in `content` |
| `truncated` | `true` when text was dropped by the extractor or its readable-text cap was hit |
| `truncation_note` | Why it was truncated; empty when it was not |
| `content` | The captured text (not the 2,000-char preview used by search JSON) |
| `error` | `null` or `{ "code": ..., "message": ... }` |
| `evidence.usable` | The product answer: can this text be cited? |
| `evidence.transport_ok` | Whether the network/extraction tier produced a body |
| `evidence.relevance` | `unknown` for `read` — no query was supplied, so no relevance is claimed |
| `evidence.reasons` | Human-readable reasons behind the usability verdict |
| `evidence.source_quality` | URL-shape quality from `scoring.py`; not proof the text answers a question |
| `video_evidence` | Transcript/caption/visual status object for video sources, else `null` |

### Error codes

| `error.code` | Exit | When |
|---|---|---|
| `invalid_url` | 2 | Empty, non-http(s), scheme-less, whitespace-bearing, credentialed, or malformed-authority/port URL |
| `invalid_timeout` | 2 | `--timeout` outside `1`–`120` seconds |
| `extraction_blocked` | 1 | Login wall, bot wall, app shell, or platform tier required but unavailable |
| `extraction_error` | 1 | All enabled public tiers failed |
| `extraction_not_attempted` | 1 | Extractor returned without attempting transport |
| `unusable_evidence` | 1 | Transport succeeded but text is too short, an empty profile, error narration, or a shell |
| `internal_error` | 1 | Unexpected exception in the extraction call (still a stable JSON error) |

Consumers should branch on `ok` first, then `error.code`; unknown future codes
must not be treated as success.

## Invalid input is never echoed verbatim

`read` prints the rejected URL back so the caller can see what failed, but it
never prints credentials and never repeats a parser exception message (those
messages can quote the input):

- A URL that parses but embeds userinfo is rebuilt without it:
  `https://user:secret@example.com/x` → `url: "https://example.com/x"`,
  `error.message: "URL must not embed credentials"`.
- A URL that *fails to parse* (malformed port, port out of range, unbalanced
  IPv6 bracket) gets the fixed message
  `"URL could not be parsed; check the scheme, host, and port"`. The parser's
  own text — `Port could not be cast to integer value as 'bad'` — is never
  surfaced, because the offending fragment can be a password.
- For that parse-failure path, userinfo is stripped textually (greedy, so a
  password containing `@` is removed whole):
  `http://user:SECRET@example.com:bad/` → `url: "http://example.com:bad/"`.
  If any credential-shaped text survives that stripping, the field becomes the
  constant `"[unparseable URL]"` instead.
- Scheme-less and protocol-relative inputs are stripped the same way, because
  `urlparse` reports no netloc/userinfo for those shapes:
  `user:secret@example.com/x` → `example.com/x`,
  `//user:secret@example.com/x` → `//example.com/x`.
- Nothing credential-shaped can reach extraction: credentialed URLs are
  rejected before `extract_hits` is called, so `content` is always `""` for
  `invalid_url`.
- The same redaction applies to text mode, where the payload is written to
  stderr; stdout stays empty (`rc == 2`).

Regression tests: `tests/test_cli_read.py::test_read_parse_failure_never_echoes_credentials`
and the generic-message/stderr siblings cover malformed port, out-of-range
port, malformed IPv6 bracket, and a password containing `@`.

## Usability is separate from transport

`extraction_status: "ok"` only means a body arrived. `ok` and
`evidence.usable` require **all** of:

1. extractor status `ok`;
2. more than 50 characters of non-empty text;
3. the shared evidence assessment considers the text usable.

That assessment rejects client-rendered HTML shells, the extractor's own
failure narration, access/404 interstitials, and empty social profiles. A page
can therefore transport successfully and still exit `1` with
`unusable_evidence` — that is the honest outcome, not a bug.

`relevance` is always `unknown` because `read` has no query to compare against.
Supplying a query would be a different command (`search --execute --extract`).

## Truncation and completeness

`content_length` and `returned_chars` are reported separately and are not
rounded or inflated:

- When an extractor branch slices a longer body (for example to 8,000 chars), it
  records the full length and `read` reports `truncated: true` with
  `"extractor kept N of M measured characters"`.
- The generic HTML cleaner caps readable text at 20,000 chars and appends
  `...`; `read` detects that cap marker and reports `truncated: true` even
  though the measured and returned counts match.
- `truncated: false` does **not** prove the upstream artifact is complete.
  Pagination, lazy-loaded comments, collapsed replies, paywalled sections and
  media-only content are outside what an HTTP extraction can certify. Treat the
  flag as “the extractor did not drop text it had” — not a completeness proof.

`content` is emitted in full as captured (bounded by the extractor's own caps),
unlike `search` JSON which previews at 2,000 chars.

## ASR is always disabled

Paid/key-consuming transcription is never invoked by `read`:

- `cmd_read` wraps extraction in `TRAILHEAD_DISABLE_ASR=1` and restores the
  previous value (including “unset”) afterwards.
- `extract._ensure_asr_enabled()` checks that variable at call time, so both the
  YouTube and TikTok ASR tiers refuse **before** downloading media or contacting
  a transcription API.
- Free caption/subtitle tiers (yt-dlp auto-captions, TikTok's own VTT track)
  remain available. A video with no captions returns blocked/unusable evidence
  rather than silently spending ASR quota.
- There is no opt-in flag in this contract. A future explicit ASR flag must be a
  separate, clearly named contract; `read` itself never transcribes.

## Fallbacks: native and public-only

`read` adds no upstream dependency and no new connector:

- **Agent Reach is not used.** The command never imports, locates, or executes
  `agent-reach`; `policy.agent_reach` is `"not_used"`.
- **The model-backed Hermes `web_extract` subprocess is disabled.** It can
  consume a model call, so `read` injects a failing final tier and reports the
  failure. Use `search ... --execute --extract` when that tier is explicitly
  wanted.
- **Enabled tiers are public HTTP ones** already present in `extract.py`:
  direct/proxy requests, Jina Reader, and native public platform APIs
  (GitHub API/raw, FxTwitter/Nitter, Redlib/PullPush/Arctic Shift, TikWM,
  Instagram embed, yt-dlp captions).
- **No credential is requested, accepted, created, or printed.** Credentials
  embedded in the input URL are rejected and masked in error output.
- The shared extractor also contains operator-configured session tiers (for
  example Camofox) that are inert unless the operator has already set them up.
  `read` neither requires nor configures them; pages that need a login normally
  surface as `extraction_blocked`.

## Runtime bound

- `--timeout` is the timeout applied to each extractor network attempt:
  `1`–`120` seconds, default `15` (the `search --execute --extract` path uses
  `10`; the default here is slightly more generous for cold single-URL reads).
- The extractor's tier ladder is finite and `read` adds no retries, no search
  fan-out, no pagination and no background jobs. Total wall time is bounded by
  that ladder — one direct attempt, up to two passes over the enabled proxy
  pool, one Jina attempt, plus any platform-specific public API calls — so a
  read can take several multiples of `--timeout` when proxies are configured or
  a host is slow. Size `--timeout` for the slowest route you expect; it is not a
  whole-command deadline.
- Because the LLM subprocess tier is disabled, the slowest historical tail
  (spawning `hermes chat`) is not part of a read.

## Implementation

`hermes_trailhead/cli.py`:

- `_read_base_payload()` owns the JSON shape; both the failure path and the
  success path start from it and override fields, so the key set cannot drift.
- `cmd_read()` validates input, wraps extraction in `_asr_forced_off()`, builds
  one `SearchHit` and calls the existing
  `extract_hits((hit,), limit=1, timeout=..., extract=_read_no_llm_extract)`.
- The hit is assessed with `ScoredHit.from_extracted_hit()` + `score_hit()`,
  so usability and source quality come from the same code as
  `search --execute --extract`.
- `extract.py` and `backends.py` are unchanged; no new fetch connector exists.

Tests: `tests/test_cli_read.py` covers the success contract, every error code,
timeout bounds, URL validation/credential masking, ASR forcing and restoration,
disabled LLM fallback, truncation reporting, transcript evidence, text-mode
output and the stable key set. They inject a fake `extract_hits`, so they never
touch the network.

```bash
python3 -m pytest -q tests/test_cli_read.py
python3 -m hermes_trailhead read https://example.com --format json
```

## What `read` deliberately does not do

- Search for or rank alternative URLs.
- Read more than one URL per invocation (call it per URL, or use `search`).
- Render JavaScript or bypass a login/paywall (those return `blocked`).
- Judge relevance without a query, or claim completeness beyond the extractor's
  measured text.
- Transcribe audio with a paid/key-consuming ASR service.
