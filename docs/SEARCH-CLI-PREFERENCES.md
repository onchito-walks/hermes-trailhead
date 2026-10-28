# Explicit search criteria on the CLI — `--prefer-language` / `--prefer-source`

Status: implemented in `hermes_trailhead/cli.py` (this change) on top of the
`preferred_language` / `preferred_sources` API added to `hermes_trailhead/search.py`.
Owner: Tech Lead (contract) / Backend Engineer (CLI).

## 1. What the flags do

```bash
python3 -m hermes_trailhead search web "asyncio event loop" --execute \
  --prefer-language es \
  --prefer-source docs.python.org --prefer-source pypi.org
```

| Flag | Dest on `args` | Meaning |
|---|---|---|
| `--prefer-language TAG` | `preferred_language` (default `""`) | Order hits whose URL advertises this language first. |
| `--prefer-source HOST` | `preferred_sources` (default `[]`, repeatable) | Order hits on this domain (or its subdomains) first. |

Both values are forwarded — after normalisation — to
`search_execute_data(..., preferred_language=..., preferred_sources=...)` and from there to
`execute_search(..., preferred_language=..., preferred_sources=...)`. No other behaviour changes.

**These are ordering hints, not filters.**

- Every hit the engine returned is still returned, exactly once, with its own snippet.
- Matching hits keep their relative backend order (stable partition), so the result is
  deterministic and inspectable.
- With no flags, the backend order is returned untouched. No default is inferred from the
  query text, the platform, the TLD or the page contents — a Chinese query with no
  `--prefer-language` is not silently re-ranked.
- No extra engine call is made. Ordering runs once over the hits the engine already returned.

## 2. What a URL can express (the only matching rules)

Matching reads the result URL and nothing else.

**Language** (`search.language_from_url`, `search.language_matches`):

1. the first path segment, when it is a recognised ISO 639-1 code, optionally with a region
   subtag — `/es/`, `/zh-cn/`, `/pt-BR/` (normalised to lower case);
2. otherwise the leftmost host label when the host has at least three labels and that label is
   a recognised code — `es.wikipedia.org`.

A request matches when the URL tag is **at least as specific**: `zh` matches `/zh-cn/`,
`zh-cn` also matches a URL advertising `zh`, but `zh-hans` and `zh-cn` never match each other
(no script/region folding, no guessing).

**Source** (`search.normalize_source`, `search.source_matches`): exact host or a real
subdomain of the requested host. `python.org` matches `docs.python.org`; `notdocs.python.org`
does not match `docs.python.org`; `python.org.evil.example` does not match `python.org`.
Scheme, path, port and a leading `www.` are dropped from the flag value.

Anything the URL does not literally advertise — page language detected from content, HTTP
headers, TLD-only guesses, snippet text, `hreflang`, query keywords — is **not** used.

## 3. Validation (reject instead of guess)

`--prefer-language` accepts a two-letter primary subtag plus an optional 2–8 character
subtag: `es`, `zh-cn`, `pt-br`. `_` is normalised to `-` and case is lowered, so `ZH_CN`
becomes `zh-cn`.

`--prefer-source` must reduce to a domain host with dot-separated labels after normalisation.

A malformed value is a usage error: the command prints the reason to stderr, exits **2**, and
does **not** run the search. Example:

```text
error: invalid --prefer-language 'english': expected a language tag like 'es' or 'zh-cn'
       (two-letter primary subtag, optional 2-8 character subtag)
```

A **well-formed but unmatched** tag (`--prefer-language ja` against English/Spanish hits) is not
an error: it changes nothing and is reported as requested, with `0` matches.

## 4. Text output

```text
## web — ok (2 hits)

Engine: jina_duckduckgo
Preferences: language=es sources=docs.python.org
Ordering only: these criteria never remove a hit
Criteria matches: 1/2 hits
  1. asyncio ES
     https://docs.python.org/es/3/library/asyncio-dev.html
     snippet: El bucle de eventos es el núcleo de toda aplicación asyncio.
  2. asyncio EN
     https://docs.python.org/3/library/asyncio.html
     snippet: The event loop is the core of every asyncio application.
```

- The `Preferences:` / `Ordering only:` / `Criteria matches:` lines appear **only** when a
  criterion was requested. `Criteria matches` counts hits where at least one requested
  criterion matched, from `SearchExecution.criteria_matches` — URL evidence, not a score.
- `snippet:` is printed only when the engine supplied a non-empty snippet. Nothing is composed
  from the title, URL or page body, and no snippet is borrowed from a neighbouring result.
  The printed text is bounded to **300 characters**, the same bound the parser stores.
- Hits without a snippet simply show title and URL.

## 5. JSON output

`--format json` already carries the criteria in each execution, from `SearchExecution.to_dict()`:

```json
{
  "preferred_language": "es",
  "preferred_sources": ["docs.python.org"],
  "criteria_matches": [
    {"url": "https://docs.python.org/es/3/library/asyncio-dev.html",
     "url_language": "es", "language_match": true, "source_matches": ["docs.python.org"]}
  ]
}
```

`hits[]` keeps its legacy three keys (`title`, `url`, `snippet`), so existing consumers are
unaffected.

## 6. Interaction with scoring

Preferences order **discovery** hits. With extraction/scoring on (the default), extracted
evidence is scored and the top-level `hits[]` follow the scored order — a quality re-rank that
is independent of these flags. Use `--no-extract`/`--no-score` when you want the preference
order preserved verbatim in `hits[]`.

## 7. Limits (stated, not hidden)

- A preference the URL shape cannot express never matches: no content-language detection, no
  `hreflang`, no query-text inference.
- Region and script subtags are compared literally — `zh-cn` does not match `/zh-hans/`.
- Sources are domains, not URL patterns: no path, wildcard or regex syntax.
- Preferences do not change the query sent to the engine, the number of engine calls, or the
  number of hits requested.
