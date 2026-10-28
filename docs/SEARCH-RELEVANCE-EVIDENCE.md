# Multilingual search relevance — bounded probe (en / zh-Hans / es)

Status: **observations only. Three queries, nine hits, one agent reviewing titles, URLs and read text.**
This is not a parity or superiority comparison, and it is not a completeness measurement.
Machine-readable record: [`evidence/search-relevance.json`](evidence/search-relevance.json).
Reviewer: Hermes agent (`monchobotjr`), **agent-reviewed, NOT human reviewed**.
Frozen expectations were written to the JSON before any search call (`status: frozen_before_calls` at
`2026-10-28T13:33:24Z`); the executed record preserves them and adds the observed results.

## Why this probe exists

The repeated en/zh evidence already on file covers action parity and artifact presence. It does not
show whether an ordinary non-English *search* returns the entity the user asked for. This probe asks
that narrow question on three specific queries and records what the native path actually returned.

## What was run

```bash
export TRAILHEAD_DISABLE_ASR=1
python3 -m hermes_trailhead search web "<query>" --execute --no-extract --limit 3 --format json
python3 -m hermes_trailhead read "<selected-url>" --format json
```

- No paid, auth, login, or model-backed calls. `read` reports `hermes_web_extract: disabled`,
  `asr: disabled`, `agent_reach: not_used` in its own payload.
- 3 search calls + 3 read calls. No public optional backend fallback was needed (every query returned
  3 hits on the first call), so fallback for these queries is untested.
- Repo `9f0eedc`, clean tree, single Linux aarch64 host, Python 3.14.9.

| Query | Language | Search window (UTC) | Engine | Hits | Read window (UTC) |
| --- | --- | --- | --- | --- | --- |
| `requests HTTP library` | en | 13:33:39 → 13:33:41 | jina_duckduckgo | 3 | 13:33:56 → 13:33:57 |
| `Python类型提示` | zh-Hans | 13:33:46 → 13:33:48 | jina_duckduckgo | 3 | 13:33:58 → 13:33:58 |
| `documentación Python asyncio` | es | 13:33:48 → 13:33:50 | jina_duckduckgo | 3 | 13:33:58 → 13:33:58 |

Every search took the same attempt ladder — `ddg_lite`, `ddg_html`, `jina_duckduckgo` — and only the
last one returned hits.

## Results and explicit relevance review

Verdicts are the reviewer's reading, not the tool's: Trailhead's own `read` payload sets
`evidence.relevance: "unknown"` and never scores relevance.

### 1. `requests HTTP library` (en) — 3/3 relevant

| # | Returned title | URL | Verdict | Why |
| --- | --- | --- | --- | --- |
| 1 | Requests: HTTP for Humans™ — Requests 2.34.2 documentation | docs.python-requests.org/en/master/index.html | relevant | Official docs of the expected entity, and one of the frozen expected sources. |
| 2 | requests · PyPI | pypi.org/project/requests/ | relevant | Distribution page for the same package; expected source, canonical for install/version. |
| 3 | GitHub - psf/requests: A simple, yet elegant, HTTP library. | github.com/psf/requests | relevant | Source repository named in the frozen expectation. |

Read of rank 1 succeeded: `extraction_status: ok`, 14,505 chars, not truncated,
`evidence.usable: true`, `source_quality: canonical (80)`. Content markers: `HTTP for Humans` ×1,
`requests` ×143.

### 2. `Python类型提示` (zh-Hans) — 1/3 relevant, 2 partially relevant

| # | Returned title | URL | Verdict | Why |
| --- | --- | --- | --- | --- |
| 1 | Python 类型注解（Type Hints） - 菜鸟教程 | runoob.com/python3/python-type-hints.html | partially_relevant | Right topic and language, but a third-party tutorial site — not the expected official docs/PEP/mypy source. Ranked above the official page. |
| 2 | typing --- 对类型提示的支持 — Python 3.15.2 文档 | docs.python.org/zh-cn/3/library/typing.html | relevant | Exactly the expected entity and source; Chinese `typing` reference. |
| 3 | Python 类型提示(Typing Hint)使用详解 - 知乎 | zhuanlan.zhihu.com/p/688656182 | partially_relevant | On-topic Chinese practitioner explainer, user-generated, not a canonical entity. |

Read of rank 2 succeeded: 20,004 chars, **truncated** at the extractor cap, `usable: true`,
`canonical (80)`. Markers: `类型提示` ×6, `typing` ×37, `泛型` ×34 — the returned text is genuinely the
Chinese typing reference.

### 3. `documentación Python asyncio` (es) — 1/3 relevant, 2 partially relevant

| # | Returned title | URL | Verdict | Why |
| --- | --- | --- | --- | --- |
| 1 | asyncio — Asynchronous I/O — Python 3.15.2 documentation | docs.python.org/3/library/asyncio.html | partially_relevant | Authoritative asyncio reference, but English while the query asked for Spanish documentation. |
| 2 | Desarrollando con asyncio — documentación de Python - 3.15.0 | docs.python.org/es/3/library/asyncio-dev.html | relevant | Spanish official docs for asyncio; matches the expected `docs.python.org/es` entity. Ranked below the English page. |
| 3 | A conceptual overview of asyncio — Python 3.15.2 documentation | docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html | partially_relevant | Official but English and tutorial-level, not the asyncio reference. |

Read of rank 2 succeeded: 16,091 chars, not truncated, `usable: true`, `canonical (80)`.
Markers: `asyncio` ×72, `Desarrollando con asyncio` ×2, `corrutinas` ×3 — Spanish page, as claimed by
its title.

## Aggregate observations (counts, not grades)

| Item | Value |
| --- | --- |
| Hits returned | 9 / 9 cap |
| Relevant (expected entity/source) | 5 |
| Partially relevant (right topic, wrong source or language) | 4 |
| Not relevant | 0 |
| Duplicate URLs | 0 |
| Distinct domains | 6 (`docs.python.org` ×4, others ×1) |
| Reads attempted / usable | 3 / 3 |

- **Requested-language canonical source ranked first only for English.** Chinese rank 1 was
  already Chinese but third-party; Chinese and Spanish official pages sat at rank 2.
- **Source-owner ordering is query-dependent.** The English query put the maintainer docs, PyPI and
  GitHub first. The Chinese query put a tutorial farm above the official docs. The Spanish query put
  three `docs.python.org` pages first, only one of them Spanish.
- **No duplication, no off-topic hit.** The four `docs.python.org` hits are four distinct pages, so the
  domain concentration is not URL duplication; freshness was not evaluated.
- Reads were consistently better evidence than the search rows: all three were `usable`, canonical,
  and matched their titles' language.

## Gaps (recorded instead of graded)

1. **No snippets anywhere.** All 9 hits returned `snippet: ""` on the `jina_duckduckgo` path. Relevance
   review is therefore title + URL + read text; snippet-level relevance could not be assessed.
2. **One engine served every query.** `ddg_lite` and `ddg_html` produced no hits before the Jina path
   succeeded, so these results are engine-correlated; a second independent backend was not exercised.
3. **Fallback untested.** No optional public backend fallback was required (3/3 queries returned 3 hits
   immediately), so this probe says nothing about fallback quality.
4. **Language/source targeting is partial.** Canonical requested-language rank-1 in 1 of 3 queries;
   requested-language pages were present for all 3. No automatic language reranker was added.
5. **Top-3 only.** Expected entities outside the top 3 — PEP 484, mypy zh, `es.wikipedia` — are
   unverified. Absence from three rows is not evidence of absence.
6. **One truncated read** (zh, 20,004-char extractor cap); the upstream page continues.
7. **Version labels unverified.** Titles advertise Python 3.15.2 / Requests 2.34.2; only the three read
   pages were fetched, and their version labels were not cross-checked against the index.
8. **Not measured:** recall, completeness, latency, cost, or any cross-tool comparison. One agent read
   nine rows; that is the entire evidence base.

## Reproduce

```bash
cd <repo>
export TRAILHEAD_DISABLE_ASR=1
python3 -m hermes_trailhead search web "Python类型提示" --execute --no-extract --limit 3 --format json
python3 -m hermes_trailhead read "https://docs.python.org/zh-cn/3/library/typing.html" --format json
```

Raw per-call JSON was kept outside the repo in the session scratch directory; the repo artifact carries
the returned fields, per-call UTC timestamps, marker counts, and a short SHA-256 of each raw search
response so a re-run can be compared without trusting this write-up.
