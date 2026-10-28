# Native `read` pagination — implementation and evidence

Scope: `hermes_trailhead/read` for one public URL. This change makes
`read --offset` / `read --max-chars` page over the **extracted** document with
truthful offsets, totals and truncation disclosure, and narrows one
non-English shell false positive. Raw evidence:
[evidence/read-pagination.json](evidence/read-pagination.json).

No credentials, paid calls, ASR, Agent Reach forwarding, model-backed
`web_extract`, publication or commits are involved. `read` still force-disables
ASR for the extraction, refuses the model tier, and does not import Agent Reach.

## Contract

```bash
python3 -m hermes_trailhead read URL [--offset CHARS] [--max-chars CHARS] --format json
```

- `--offset` is a non-negative **character** offset into the cleaned extracted
  text (not raw HTML bytes). Default `0`.
- `--max-chars` is the response window, `1..200000`. Default `20000`, so a
  default read keeps the historical ~20k output.
- `--offset` beyond the end returns an empty window with `pagination.note`; it
  is not an error and does not pretend text was skipped.
- Each payload carries `pagination`:
  `offset`, `max_chars`, `start`, `end`, `returned_chars`, `next_offset`,
  `more`, `total_available_chars`, `window_empty`, `retrieval_char_cap`,
  `extractor_truncated`, `retrieval_capped`, `transport_byte_cap`,
  `transport_capped`, `document_sha256`, `note`.
- `content` is exactly `document[start:end]`; `next_offset == end` while
  `more` is true, `null` otherwise. Successive windows therefore have no gap
  and no overlap by construction.
- `completeness.raw_page_complete` is always `false`. `content` is readable
  text extracted from the page (markup, scripts and repeated chrome removed),
  never a byte-identical copy of the fetched page.
  `completeness.extracted_document_complete` is true only when the window covers all
  available extracted characters and no extractor/retrieval/transport bound
  cut the document.

### Document identity (`pagination.document_sha256`)

`document_sha256` is the SHA-256 (lowercase hex) of the **whole available
extracted document** — the same string `start`/`end` index into — computed
*before* the window is sliced. Windows from the same extraction therefore
carry the same digest even though their `content` differs, and any edit to the
extracted text changes it.

- Scope: the digest covers the text this read actually extracted and retained
  (after the extractor, retrieval and transport bounds above). It is not a
  hash of the upstream page and proves nothing about text those bounds cut.
- `""` means "no document identity was observed": the read never reached
  extraction (invalid URL/offset/max-chars/timeout, internal error) or the
  extracted document is empty. The empty string is never used as a digest, so
  a caller cannot confuse "nothing read" with "hashed empty text".
- Algorithm: `hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()`
  where `content` is the cleaned extracted text (`hermes_trailhead.cli._document_sha256`).
  UTF-8 is fixed here so the value is stable across platforms and locales.

**Refetch caveat (explicit):** `read` is stateless and refetches the URL on
every invocation. The digest identifies *which version* a given window came
from; it cannot make a later page still exist or unchanged. A caller chaining
offsets must compare `document_sha256` across windows and discard the sequence
when it changes — otherwise `next_offset` may index a document that has
shifted or is gone. Because of that, equal digests prove same-text paging of
the available extraction, and differing digests prove the upstream page (or
extraction) changed; neither direction is a completeness claim about the
upstream page.

### Three distinct bounds

| Bound | Value | Meaning |
|---|---|---|
| Window | 200,000 chars max | one response (`--max-chars`), default 20,000 |
| Retrieval | 1,000,000 chars | cleaned text retained for paging in one `read` |
| Transport | 8,388,608 bytes | raw HTTP body read by the fetchers for one `read` |

The transport byte cap is enforced in `_fetch_text`, `_fetch_jina` and the
proxy routes via `_bounded_body`, which reads one byte past the cap so the
payload can report `transport_capped` instead of presenting a clipped body as
whole. The proxy route's historical 50k-char preview becomes 1,000,004 chars
inside a read scope and marks `transport_capped` when it cuts. Search is
unaffected: the byte cap defaults to unbounded and the cleaned-text limit stays
20,000 outside the read scope.

## Implementation

- `extract.retrieval_scope(char_limit, byte_limit)` is a context manager that
  widens `_html_to_readable_text` and the fetchers for exactly one `cmd_read`
  call and restores every context variable afterwards. `search` keeps the 20k
  preview.
- `_html_to_readable_text(..., limit=, stats=)` reports `total_chars` (full
  cleaned length before the cap) and `capped`. `extract_one` uses that total as
  `content_length`, so a capped document reports the measured total rather than
  the returned prefix. Already-clean (non-HTML) bodies are bounded at the same
  limit, so plain text cannot bypass the declared 1M retrieval cap.
- `cmd_read` slices the extracted document, computes `next_offset`, and keeps
  the old fields (`content_length`, `returned_chars`, `truncated`,
  `truncation_note`) plus the new pagination/completeness blocks. The JSON key
  set is identical on success and every error path.
- `_document_sha256(content)` fills `pagination.document_sha256` from the
  pre-window extracted text; `_read_pagination_block` defaults the same key to
  `""`, so every error path keeps the key with no identity claimed. The text
  renderer prints the digest in the window line and states the refetch caveat
  once, so an interactive reader sees the same limit the JSON documents.
- New stable error codes, exit 2, no extraction attempted: `invalid_offset`,
  `invalid_max_chars`. Existing codes are unchanged.
- A chunk is not re-classified as a shell: pagination happens after extraction
  and no window is passed back through shell detection. `evidence.usable`
  remains a property of the document, not of the window.

Default-output compatibility: for a legacy extractor payload that already
ended at the historical 20k cap (content ends with the `\n...` marker and is
≤ 20,008 chars), a default read still returns that payload whole. It is already
bounded and nothing lies beyond it; this is not a hidden skip of document
text. Larger documents get the first 20,000-character window.

## Real public read

URL: `https://docs.python.org/zh-cn/3/library/typing.html` (zh-Hans, long
Chinese reference; the document that exposed the extractor cap in earlier
acceptance work). Run 2026-10-28T14:14Z, 4 windows of 20,000 characters:

| Window | Span | Chars | SHA-256 (16) | 类型提示 | typing | 泛型 | 协议 |
|---|---|---|---|---|---|---|---|
| 1 | 0–20000 | 20000 | `5c764991dab17784` | 6 | 37 | 34 | 3 |
| 2 | 20000–40000 | 20000 | `63222002bc6a2408` | 1 | 41 | 17 | 0 |
| 3 | 40000–60000 | 20000 | `9f5d1a1f6e793d14` | 3 | 41 | 10 | 29 |
| 4 | 60000–78047 | 18047 | `b04da5ac09911b62` | 2 | 76 | 5 | 2 |

- Total available extracted characters: **78,047**. Spans are contiguous; the
  concatenation of the four windows is 78,047 chars and its SHA-256 is
  `eb8e809440b16bbd…`, identical to a single `--max-chars 200000` read of the
  same page. The evidence artifact records `contiguous_no_gaps: true` and
  `reconstruction_matches_full_single_window: true`.
- Re-run 2026-10-28 for `pagination.document_sha256`: all four windows report
  `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea` — the
  same value as the documented reconstruction hash — while each window's own
  content hashes to its distinct row above. This is the one live check that
  the digest is document identity rather than window identity; it says
  nothing about the upstream page beyond this extraction.
- The first window's `类型提示 ×6, typing ×37, 泛型 ×34` matches the marker set
  frozen in [SEARCH-RELEVANCE-EVIDENCE.md](SEARCH-RELEVANCE-EVIDENCE.md) for
  this page, so this is the same document, now readable past 20k rather than
  truncated with no continuation.
- `truncated: true` on the first three windows is truthful — more text exists
  and `next_offset` says where. The extractor itself did **not** truncate
  (`extractor_truncated: false`), the retrieval cap was not reached
  (`retrieval_capped: false`), and no transport bound was hit
  (`transport_capped: false`).

Reproduce:

```bash
cd <repo>
python3 -m hermes_trailhead read "https://docs.python.org/zh-cn/3/library/typing.html" --format json
python3 -m hermes_trailhead read "https://docs.python.org/zh-cn/3/library/typing.html" --format json --offset 20000 --max-chars 20000
python3 -m hermes_trailhead read "https://docs.python.org/zh-cn/3/library/typing.html" --format json --max-chars 200000
```

Page content changes upstream over time; the artifact records the exact
hashes and timestamp rather than promising immutability.

## Deterministic contract tests

`tests/test_read_pagination.py` — **27 passed**. It never touches the network.
Covered:

- A frozen ~63k-character Chinese typing fixture reconstructs exactly from
  successive windows: contiguous spans, no gap, no overlap, total equals
  document length, `next_offset` links windows, last window has `more: false`.
- Default read returns `document[:20000]`; an explicit large window returns
  the whole fixture and only then sets `extracted_document_complete` true and
  `raw_page_complete` false.
- Offset beyond the end returns an empty, contiguous window with a note and
  does not error.
- Extractor truncation (`content_length` > available), retrieval cap and
  transport-byte cap are reported by separate fields and distinct notes; a
  windowed read does not double-count them.
- `retrieval_scope` widens the limit to 1,000,000 only during the call and
  restores 20,000 afterwards; `_bounded_body` stops at the byte cap and marks
  the state. Plain text is bounded at the same limit as HTML.
- Invalid offset/max-chars values are stable JSON errors with exit 2 and no
  extraction; the max window boundary is accepted.
- A window quoting shell vocabulary (`页面不存在`, `Loading...`) is still
  usable evidence and is not re-classified as a shell.

`tests/test_followup_qa.py` adds the adversarial cases this change fixed:

- Windows at offset `0`, `20000` and near EOF of one fixture all report the
  same `document_sha256`, equal to the SHA-256 of the full fixture — proving
  the digest is document identity, not a window hash.
- An edited fixture of the *same length* behind the same URL reports a
  different digest, so a caller can detect that offsets no longer apply.
- An empty extraction and every pre-extraction error path report `""`
  (invalid paging argument: no extraction attempted, empty document: no text
  to identify), while a short-but-real document still has an identity.

Run: `python3 -m pytest -q tests/test_read_pagination.py tests/test_followup_qa.py`

## F8 non-English shell assessment (fixture-level, conservative)

F8 in [MAINTENANCE-REVIEW.md](MAINTENANCE-REVIEW.md) records literal marker
matching and the intentionally narrowed 801–2000-char single-language band.
Those forms were **not** changed: no reproduced live false negative justified
normalising zero-width/full-width characters or adding phrases.

The non-English false positive that *was* reproduced is in `_is_html_shell`'s
short-body gate. It counts whitespace tokens; Han/Kana/Hangul text has almost
none, so a genuine short CJK HTML document was unconditionally classified as a
client-rendered shell. Fixture (a 376-cleaned-char Chinese docs body, 11
whitespace words, 332 CJK chars):

| Rule | Verdict |
|---|---|
| old `len(words) < 25` gate | **shell** (false positive) |
| positive CJK prose evidence | true |
| current `_is_html_shell` | **not a shell**; readable text is returned |

Fix: the short-body gate is vetoed only by positive prose evidence — at least
80 CJK characters **and** at least two CJK sentence marks (`。！？；`), i.e. more
connected text than any label/loading pane renders. A Chinese label shell
(`登录 / 注册 / 加载中 / 查询结果 / 暂无数据`) has no such prose, and a short
Latin shell (`Loading...` app shell) still hits the word-count gate. Both are
asserted in the tests.

Conservative scope of the claim:

- 0 of 8 live Chinese pages probed (docs.python.org zh-cn ×4, ruanyifeng,
  liaoxuefeng, zh.wikipedia, runoob) triggered the old short rule — their
  template navigation supplies enough tokens. The false positive is
  fixture-level; this change does not claim measured live coverage.
- The legitimate Chinese article fixture (≈1.2k chars) that twice contains
  `页面不存在` is still **not** classified as a missing page: the F4
  conservatism for the middle band is preserved.
- F8's literal/zero-width matching issue remains open; no heuristic was
  broadened without a reproduced failure.

## Not claimed

- Raw HTML byte-identical completeness, or completeness of artifacts the page
  never served (replies behind JS, authenticated content).
- Any authenticated, paid or ASR-backed path; read still refuses them.
- Clean-machine/cross-OS behaviour.
- That the four-window run generalises to every long page: it is one public
  Chinese document plus deterministic fixtures. A wider multi-page sample is
  still needed for a coverage claim.
- All-artifact pagination/completeness. This covers the native `read` document
  only; search hits, comments, replies and other artifacts remain open in
  [SUPERIORITY-ACCEPTANCE.md](SUPERIORITY-ACCEPTANCE.md).
- That `document_sha256` identifies an upstream page, or that arbitrary
  upstream text is complete. It hashes only what one read extracted: text cut
  by the extractor, retrieval or transport bound is outside the hash, so an
  equal digest means "same available extraction", never "the page is
  unchanged and fully captured".
