# Snippet recovery and explicit ranking criteria — bounded follow-up (en / zh / es)

Status: **observations only. Three queries, nine hits per run, one agent reading the payloads.**
This is not a relevance model, not a reranker, not a parity or superiority comparison, and not a
completeness measurement. Machine-readable record: [`evidence/search-followup.json`](evidence/search-followup.json).
Reviewer: Hermes agent (`monchobotjr`), **agent-reviewed, NOT human reviewed**.
The three probe expectations were frozen before any call (`status: frozen_before_calls` at
`2026-10-28T13:59:17Z`) and the executed record preserves them verbatim alongside the observations.

## 1. What changed

Two changes, both in `hermes_trailhead/search.py`. No CLI flag and no text-renderer change was made
in this change, and `backends.py`, `cli.py` and `extract.py` were not touched by it.

1. **Snippets are read from the real Jina/DuckDuckGo block shape.** The previous reader stopped at
   the first blank line after a `## [title](...)` heading, but Jina separates the heading, the
   favicon/breadcrumb line and the snippet line *with blank lines* — so every snippet came back
   `""`.
2. **Explicit, opt-in ranking criteria.** `execute_search()` and `execute_action()` accept
   `preferred_language=` and `preferred_sources=`. With both empty (the default, and what the CLI
   uses today) hit order is exactly the backend order.

## 2. Snippet recovery

### The block shape that was actually returned

```text
## [Requests: HTTP for Humans™ — Requests 2.34.2 documentation](http://duckduckgo.com/l/?uddg=...)

[![Image 1](http://external-content.duckduckgo.com/ip3/docs.python-requests.org.ico)](http://duckduckgo.com/l/?uddg=...)[docs.python-requests.org/en/master/index.html](http://duckduckgo.com/l/?uddg=...)

[**Requests**: **HTTP** for Humans™ ¶ Release v2.34.2. (Installation) **Requests** is an elegant ...](http://duckduckgo.com/l/?uddg=...)
```

### Exact extraction rules

- The snippet is the **link text of an inline markdown link line** inside the block
  (`^\[(?!\[)(.+)\]\((https?://[^)\s]+)\)$`). It is never composed from the title, the URL, the
  query or the page.
- Favicon/image lines (`[![Image N]...`) are skipped.
- The grey breadcrumb line is skipped: it equals the hit URL or its `host+path`.
- The read window ends at the next `#` heading, so a block can never borrow the next block's text.
- Removed: `**`/`__` highlight markers, backslash escapes, the `¶` heading-anchor glyph; whitespace
  is collapsed. **Nothing is added, re-spaced, translated or completed.**
- A line that opens a markdown link/highlight and never closes it is a truncated response tail and is
  skipped rather than used as prose.
- Text is capped at 300 characters (the same cap as before).

### Before / after counts

| Run | Queries | Hits | Hits with a non-empty snippet |
| --- | --- | --- | --- |
| Before (pre-change parser, raw responses kept) | 3 | 9 | **0 / 9** |
| After, re-parsing the *same* raw bytes | 3 | 9 | **9 / 9** |
| After, fresh live calls | 3 | 9 | **9 / 9** (lengths 140, 264, 108 / 167, 155, 133 / 200, 300, 300) |

The "after, same raw bytes" row is the exact comparison: identical response bytes, only the reader
changed. URLs, titles, counts and order were identical before and after — only `snippet` changed.

### Recovered snippets (live run, exact)

**`requests HTTP library` (en)** — 3/3 non-empty

| # | Title | URL | Snippet (exact, as returned) |
| --- | --- | --- | --- |
| 1 | Requests: HTTP for Humans™ — Requests 2.34.2 documentation | `docs.python-requests.org/en/master/index.html` | Requests: HTTP for Humans™ Release v2.34.2. (Installation) Requests is an elegant and simple HTTPlibrary for Python, built for human beings. |
| 2 | requests · PyPI | `pypi.org/project/requests/` | RequestsRequests is a simple, yet elegant, HTTPlibrary. ... Requests allows you to send HTTP/1.1 requests extremely easily. There's no need to manually add query strings to your URLs, or to form-encode your PUT & POST data — but nowadays, just use the json method! |
| 3 | GitHub - psf/requests: A simple, yet elegant, HTTP library. | `github.com/psf/requests` | A simple, yet elegant, HTTPlibrary. Contribute to psf/requests development by creating an account on GitHub. |

**`Python类型提示` (zh)** — 3/3 non-empty

| # | Title | URL | Snippet (exact, as returned) |
| --- | --- | --- | --- |
| 1 | typing --- 对类型提示的支持 — Python 3.15.2 文档 | `docs.python.org/zh-cn/3/library/typing.html` | Learn how to use the typing module to add type annotations to your Python code. See examples of type aliases, NewType, callable objects, and other advanced type hints. |
| 2 | Python 类型注解（Type Hints） - 菜鸟教程 | `www.runoob.com/python3/python-type-hints.html` | Python 类型注解（Type Hints） 想象一下，你给朋友寄一个包裹。如果你在包裹上写明"易碎品"和"向上箭头"，快递员就会知道要小心轻放、正确朝向。类型注解（Type Hints） 在编程中就扮演着类似的角色——它是一种为代码添加"说明标签"的技术，明确地指出变量、函数参数和返回值应该是什么 ... |
| 3 | Python 类型提示(Typing Hint)使用详解 - 知乎 | `zhuanlan.zhihu.com/p/688656182` | 类型提示，对应当前的python 3.12 中 Typing Hint英文词语(官方文档有时也称类型注解(type annotation)。正如 hint 的英文本义，Typing Hint 只是对当前变量类型的提示，并非强制类型申明，Python未来版本会继续完… |

**`documentación Python asyncio` (es)** — 3/3 non-empty

| # | Title | URL | Snippet (exact, as returned) |
| --- | --- | --- | --- |
| 1 | Desarrollando con asyncio — documentación de Python - 3.15.0 | `docs.python.org/es/3/library/asyncio-dev.html` | La programación asincrónica es diferente a la programación «secuencial» clásica. Esta página enumera errores y trampas comunes y explica cómo evitarlos. Modo depuración: Por defecto asyncio se ejec... |
| 2 | asyncio — Asynchronous I/O — Python 3.15.2 documentation | `docs.python.org/3/library/asyncio.html` | asyncio is a library to write concurrent code using the async/await syntax. asyncio is used as a foundation for multiple Python asynchronous frameworks that provide high-performance network and web-servers, database connection libraries, distributed task queues, etc. asyncio is often a perfect fit f |
| 3 | A conceptual overview of asyncio — Python 3.15.2 documentation | `docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html` | A conceptual overview part 1: the high-level In part 1, we'll cover the main, high-level building blocks of asyncio: the event loop, coroutine functions, coroutine objects, tasks, and await. Event loop Everything in asyncio happens relative to the event loop. It's the star of the show, but prefers t |

### Two literal artifacts that were deliberately not repaired

- DuckDuckGo's highlight spans sometimes touch, so the reader emits `**HTTP****library**` and
  `**Requests****Requests**`. Stripping the markers leaves `HTTPlibrary` and `RequestsRequests`.
  Inserting the missing space would be inventing text, so the strings are stored exactly as the
  reader produced them.
- The Spanish `docs.python.org/3` snippets hit the 300-character cap mid-word (`... perfect fit f`).

## 3. Explicit ranking criteria

### API

```python
execute_search(platform, query, *, limit=5, fetch=None, reach_adapter=None,
               preferred_language="", preferred_sources=())

execute_action(action, *, limit=5, fetch=None, reach_adapter=None,
               preferred_language="", preferred_sources=())

order_hits_by_criteria(hits, *, preferred_language="", preferred_sources=())
```

`SearchExecution` gained `preferred_language`, `preferred_sources` and `criteria_matches`; `to_dict()`
exposes them as `preferred_language`, `preferred_sources` (list) and `criteria_matches` (one record
per hit: `url`, `url_language`, `language_match`, `source_matches`). **Hit JSON is unchanged**:
`{"title", "url", "snippet"}`, pinned by `tests/test_evidence_honesty.py` and re-pinned here.

### Exact matching rules

| Item | Rule |
| --- | --- |
| URL language, path | first path segment, if it is an ISO 639-1 code with an optional region subtag (`/es/`, `/zh-cn/`, `/pt-BR/`) |
| URL language, host | otherwise the leftmost host label, only when the host has ≥ 3 labels and the label is a recognised code (`es.wikipedia.org`) |
| Recognised codes | fixed `_LANGUAGE_CODES` frozenset in `search.py`; any other code yields `url_language: ""` |
| Language match | URL tag equals the request, or extends it with a region subtag — `zh` matches `zh-cn`; **`zh-hans` and `zh-cn` never match each other** (no script/region folding) |
| Source match | requested host equals the URL host, or the URL host is a real subdomain of it; scheme, path, port and a leading `www.` are stripped; no wildcards, no path matching |
| Precedence | language group first, domain group second, then original backend order — a stable sort, so equals keep their relative order |
| Inactive criterion | a criterion the caller did not pass contributes nothing; both empty returns the input order untouched |
| Never inferred | the query text is never inspected (no script counting, no keyword list); nothing is re-ranked unless the caller asks |

Because of the missing folding, a caller who wants the `docs.python.org/zh-cn/...` page asks for
`preferred_language="zh"`, not `"zh-Hans"`. That is the rule, not a discovery about the page.

### Measured effect (same frozen hits, criteria = that query's language + `docs.python.org`)

**`requests HTTP library`** — order unchanged; only `docs.python-requests.org/.../en/...` carries an
URL language, and `docs.python-requests.org` is *not* a subdomain of `docs.python.org`, so the source
criterion matches nothing here.

| Rank | Backend order (no criteria) | With caller criteria | URL language | Criteria hits |
| --- | --- | --- | --- | --- |
| 1 | `docs.python-requests.org/en/master/index.html` | `docs.python-requests.org/en/master/index.html` | `en` | lang `en` |
| 2 | `pypi.org/project/requests/` | `pypi.org/project/requests/` | `-` | - |
| 3 | `github.com/psf/requests` | `github.com/psf/requests` | `-` | - |

**`Python类型提示`** — the official Chinese page moves from rank 2 to rank 1.

| Rank | Backend order (no criteria) | With caller criteria | URL language | Criteria hits |
| --- | --- | --- | --- | --- |
| 1 | `www.runoob.com/python3/python-type-hints.html` | `docs.python.org/zh-cn/3/library/typing.html` | `zh-cn` | lang `zh-cn` + source`docs.python.org` |
| 2 | `docs.python.org/zh-cn/3/library/typing.html` | `www.runoob.com/python3/python-type-hints.html` | `-` | - |
| 3 | `zhuanlan.zhihu.com/p/688656182` | `zhuanlan.zhihu.com/p/688656182` | `-` | - |

**`documentación Python asyncio`** — the Spanish page moves from rank 2 to rank 1.

| Rank | Backend order (no criteria) | With caller criteria | URL language | Criteria hits |
| --- | --- | --- | --- | --- |
| 1 | `docs.python.org/3/library/asyncio.html` | `docs.python.org/es/3/library/asyncio-dev.html` | `es` | lang `es` + source`docs.python.org` |
| 2 | `docs.python.org/es/3/library/asyncio-dev.html` | `docs.python.org/3/library/asyncio.html` | `-` | source`docs.python.org` |
| 3 | `docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html` | `docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html` | `-` | source`docs.python.org` |

Counts: 2 of 3 queries changed order (the en query had no hit to promote); 0 hits added, dropped or
duplicated; the relative order inside each group is the backend order. The live run reproduced all three orders
(`criteria_order` equals the live hit order in `evidence/search-followup.json`).

What this does **not** claim: that a URL language segment proves the page language, that a matching
domain is a better answer, that the ranking is correct, or that any of this generalises beyond these
nine rows. `extract`'s `evidence.relevance` remains `"unknown"`, and no relevance score is produced.

## 4. Limitations

1. **Agent reviewed, not human reviewed** — one agent read three queries × three hits per run.
2. **One engine.** Every call went `ddg_lite` (circuit open) → `ddg_html` (circuit open) →
   `jina_duckduckgo`. Results are engine-correlated; no second backend was compared.
3. **No fallback exercised.** No optional public backend was needed.
4. **Snippet text is DuckDuckGo's stored blurb**, not the page. It can be a meta description whose
   language differs from the page: the `docs.python.org/zh-cn/.../typing.html` hit returned an
   English blurb (`Learn how to use the typing module ...`), and the reranker still placed it first
   on its `/zh-cn/` URL segment. Snippet language is therefore *not* a language signal here.
5. **URL-shape language only.** Content-language detection was not attempted, and a brand label on a
   three-label host can be read as a language.
6. **Not folded:** `zh-hans`, `zh-cn`, `zh-tw` are distinct tags.
7. **Truncation:** the 300-character cap can cut mid-word; it was not raised.
8. **CLI unchanged.** Criteria are an API surface only; the parent integrates CLI flags if it decides
   they are worth it — until then `python -m hermes_trailhead search ...` behaves exactly as before.
   Snippets are populated in the hit objects and in `--format json`; the plain-text renderer in
   `cli.py`/`formatters.py` prints title + URL and was not touched by this change, so a text-format
   run still shows no snippet.
9. **Ordering ≠ relevance.** No scoring, no quality judgement, no claim of universal relevance.
10. **Networks move.** The live after-run happened minutes after the before-run; snippet text and hit
    sets can differ on a later run. The exact comparison is the frozen raw response, kept by
    short SHA-256 in the JSON artifact.

## 5. Reproduce

```bash
cd <repo>
export TRAILHEAD_DISABLE_ASR=1
.venv/bin/python -m pytest -q tests/test_search_preferences.py

# default path: backend order, snippets now populated
.venv/bin/python -m hermes_trailhead search web "Python类型提示" --execute --no-extract --limit 3 --format json

# criteria path (API)
.venv/bin/python - <<'PY'
from hermes_trailhead.search import execute_search
print(execute_search("web", "Python类型提示", limit=3,
                     preferred_language="zh", preferred_sources=("docs.python.org",)
                     ).executions[0].to_dict()["criteria_matches"])
PY
```

## 6. Verification run for this change

| Check | Result |
| --- | --- |
| `python3 -m py_compile hermes_trailhead/*.py` | clean |
| `pytest -q tests/test_search_preferences.py` | 37 passed |
| `pytest -q` (whole suite) | 786 passed, 0 failed in this run; sibling modules were being edited by other workers at the same time, so this count is a snapshot |
| Public calls in this probe | 6 total (3 before, 3 after), no paid/auth/model calls |
