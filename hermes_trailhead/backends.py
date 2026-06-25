"""Hermes Trailhead multi-backend search engine.

Each source family gets its own ranked chain of search backends.
No single backend failure can crater all results — each lane has
independent fallback paths.  The engine tries backends in order;
first success wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import html
import json
import re
import urllib.request
from typing import Callable
from urllib.parse import parse_qs, quote_plus, urlparse


FetchFn = Callable[[str, int], str]


@dataclass
class Backend:
    """One search backend in a platform's ranked chain."""
    name: str
    description: str
    build_url: Callable[[str], str]
    parser: Callable  # (str, int) -> tuple; resolved via _get_parsers()
    timeout: int = 20
    needs_approval: bool = False
    paid: bool = False
    accept_url: Callable[[str], bool] | None = None


# ── Lazy parser resolution (avoids circular import search ↔ backends) ─────

_parsers = None

def _get_parsers():
    global _parsers
    if _parsers is None:
        from .search import (
            _parse_markdown_search_results,
            _parse_html_search_results,
        )
        _parsers = (_parse_markdown_search_results, _parse_html_search_results)
    return _parsers


def _mk() -> Callable:
    """Return markdown parser."""
    return _get_parsers()[0]


def _hp() -> Callable:
    """Return HTML parser."""
    return _get_parsers()[1]


# ── URL builders ──────────────────────────────────────────────────────────


def _ddg_lite_url(query: str) -> str:
    return f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"


def _ddg_html_url(query: str) -> str:
    return f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"


def _jina_ddg_url(query: str) -> str:
    return f"https://r.jina.ai/http://duckduckgo.com/html/?q={quote_plus(query)}"


def _searxng_url(query: str) -> str:
    return f"http://127.0.0.1:8099/search?{quote_plus('q')}={quote_plus(query)}&format=json"


def _searxng_parser() -> Callable:
    return _parse_searxng_results


def _parse_searxng_results(page: str, limit: int):
    from .search import SearchHit

    try:
        data = json.loads(page)
    except Exception:
        return tuple()
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for row in data.get("results", []) if isinstance(data, dict) else []:
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or url).strip()
        snippet = str(row.get("content") or "").strip()
        if _is_noise_url(url) or url in seen:
            continue
        seen.add(url)
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return tuple(hits)


def _bing_search_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}"


def _bing_parser() -> Callable:
    return _parse_bing_search_results


def _clean_title(raw: str) -> str:
    return re.sub(r"<[^>]+>", "", raw)


def _is_noise_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return (
        not url.startswith(("http://", "https://"))
        or "duckduckgo.com" in host
        or "google.com/search" in url
        or "bing.com/search" in url
        or "javascript:" in url.lower()
    )


def _bing_decode_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.bing.com" or parsed.path != "/ck/a":
        return url
    params = parse_qs(parsed.query)
    encoded = html.unescape(params.get("u", [""])[0])
    if not encoded.startswith("a1"):
        return url
    payload = encoded[2:]
    padding = "=" * ((4 - len(payload) % 4) % 4)
    try:
        decoded = base64.b64decode(payload + padding).decode("utf-8", errors="replace")
    except Exception:
        return url
    if decoded.startswith("/"):
        return f"https://www.bing.com{decoded}"
    return decoded if decoded.startswith(("http://", "https://")) else url


def _parse_bing_search_results(page: str, limit: int) -> tuple[SearchHit, ...]:
    from .search import SearchHit

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a class="tilk" aria-label="([^"]+)"[^>]+href="([^"]+)"', page, flags=re.I | re.S):
        raw_title, raw_url = match.group(1), match.group(2)
        title = _clean_title(html.unescape(raw_title))
        url = _bing_decode_url(html.unescape(raw_url))
        if _is_noise_url(url) or url in seen:
            continue
        if not title or title.lower() in {"images", "videos", "news", "maps", "shopping"}:
            continue
        seen.add(url)
        hits.append(SearchHit(title=title, url=url, snippet=""))
        if len(hits) >= limit:
            break
    return tuple(hits)




def _github_search_url(query: str) -> str:
    return f"https://github.com/search?q={quote_plus(query)}&type=repositories"


def _youtube_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def _redlib_search_url(query: str) -> str:
    return f"https://redlib.perennialte.ch/search?q={quote_plus(query)}"


def _reddit_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "reddit.com" not in host:
        return False
    if path.startswith("/search"):
        return False
    return path.startswith(("/r/", "/comments/", "/u/", "/user/"))


def _nitter_search_url(query: str) -> str:
    return f"http://localhost:8788/search?f=tweets&q={quote_plus(query)}"


_X_RESERVED_PATH_PREFIXES = (
    "/home",
    "/explore",
    "/i/",
    "/search",
    "/notifications",
    "/messages",
    "/settings",
    "/bookmarks",
    "/compose",
    "/hashtag/",
    "/intent/",
    "/login",
    "/signup",
)


def _x_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "x.com" not in host and "twitter.com" not in host:
        return False
    if path.startswith(_X_RESERVED_PATH_PREFIXES):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 1 and (len(parts) == 1 or (len(parts) >= 3 and parts[1] == "status"))


def _youtube_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        "youtu.be" in host
        or ("youtube.com" in host and (path == "/watch" or path.startswith("/shorts/") or path.startswith("/@")))
    )


def _github_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host != "github.com":
        return False
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0] in {
        "features",
        "topics",
        "marketplace",
        "pricing",
        "login",
        "search",
        "mcp",
        "security",
        "enterprise",
        "solutions",
        "product",
        "orgs",
        "about",
        "customer-stories",
        "sponsors",
    }:
        return False
    return True


QUERY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "build",
    "printer",
    "discussion",
    "thread",
    "video",
    "guide",
    "post",
    "search",
    "about",
    "best",
    "top",
    "how",
    "what",
    "why",
    "when",
    "where",
    "who",
    "is",
    "are",
    "was",
    "vs",
}


def _query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for term in re.findall(r"[a-z0-9]+", query.lower()):
        if len(term) < 4 or term in QUERY_STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def _result_matches_query(url: str, title: str, query: str, snippet: str = "") -> bool:
    terms = _query_terms(query)
    if not terms:
        return True
    haystack = f"{title} {url} {snippet}".lower()
    return any(term in haystack for term in terms)


# ── HTTP fetch ────────────────────────────────────────────────────────────


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Hermes Trailhead/0.3 (multi-backend)",
            "Accept": "text/html,text/plain,text/markdown,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── Platform backend chains ───────────────────────────────────────────────


BACKENDS: dict[str, list[Backend]] = {
    "github": [
        Backend("searxng_site_github", "Local SearXNG site:github.com", lambda q: _searxng_url(f"site:github.com {q}"), _searxng_parser, accept_url=_github_result_url),
        Backend("bing_search", "Bing search", _bing_search_url, _bing_parser, accept_url=_github_result_url),
        Backend("ddg_lite_site_github", "DuckDuckGo Lite site:github.com",
                lambda q: _ddg_lite_url(f"site:github.com {q}"), _hp, accept_url=_github_result_url),
        Backend("jina_duckduckgo_site_github", "Jina Reader over DuckDuckGo site:github.com",
                lambda q: _jina_ddg_url(f"site:github.com {q}"), _mk, accept_url=_github_result_url),
        Backend("github_search", "GitHub issue search", _github_search_url, _hp, accept_url=_github_result_url),
    ],
    "reddit": [
        Backend("searxng_site_reddit", "Local SearXNG site:reddit.com", lambda q: _searxng_url(f"site:reddit.com {q}"), _searxng_parser, accept_url=_reddit_result_url),
        Backend("redlib_search", "Redlib privacy frontend", _redlib_search_url, _hp, accept_url=_reddit_result_url),
        Backend("jina_duckduckgo_site_reddit", "Jina Reader over DuckDuckGo site:reddit.com",
                lambda q: _jina_ddg_url(f"site:reddit.com {q}"), _mk, accept_url=_reddit_result_url),
        Backend("ddg_lite_site_reddit", "DuckDuckGo Lite site:reddit.com",
                lambda q: _ddg_lite_url(f"site:reddit.com {q}"), _hp, accept_url=_reddit_result_url),
    ],
    "youtube": [
        Backend("searxng_site_youtube", "Local SearXNG site:youtube.com/watch", lambda q: _searxng_url(f"site:youtube.com/watch {q}"), _searxng_parser, accept_url=_youtube_result_url),
        Backend("ddg_lite_site_youtube", "DuckDuckGo Lite site:youtube.com",
                lambda q: _ddg_lite_url(f"site:youtube.com/watch {q}"), _hp, accept_url=_youtube_result_url),
        Backend("jina_duckduckgo_site_youtube", "Jina Reader over DuckDuckGo site:youtube.com",
                lambda q: _jina_ddg_url(f"site:youtube.com/watch {q}"), _mk, accept_url=_youtube_result_url),
        Backend("youtube_search", "YouTube search results", _youtube_search_url, _hp, accept_url=_youtube_result_url),
    ],
    "x": [
        Backend("searxng_site_x", "Local SearXNG site:x.com", lambda q: _searxng_url(f"site:x.com {q}"), _searxng_parser, accept_url=_x_result_url),
        Backend("nitter_search", "Nitter privacy frontend", _nitter_search_url, _hp, accept_url=_x_result_url),
        Backend("jina_duckduckgo_site_x", "Jina Reader over DuckDuckGo site:x.com",
                lambda q: _jina_ddg_url(f"site:x.com {q}"), _mk, accept_url=_x_result_url),
        Backend("ddg_lite_site_x", "DuckDuckGo Lite site:x.com",
                lambda q: _ddg_lite_url(f"site:x.com {q}"), _hp, accept_url=_x_result_url),
    ],
    "web": [
        Backend("searxng", "Local SearXNG", _searxng_url, _searxng_parser),
        Backend("bing_search", "Bing search", _bing_search_url, _bing_parser),
        Backend("jina_duckduckgo", "Jina Reader over DuckDuckGo", _jina_ddg_url, _mk),
        Backend("ddg_html", "DuckDuckGo HTML", _ddg_html_url, _hp),
        Backend("ddg_lite", "DuckDuckGo Lite", _ddg_lite_url, _hp),
    ],
    "tiktok": [
        Backend("searxng_site_tiktok", "Local SearXNG site:tiktok.com (discovery only)", lambda q: _searxng_url(f"site:tiktok.com {q}"), _searxng_parser),
        Backend("jina_duckduckgo_site_tiktok", "Jina Reader over DDG site:tiktok.com (discovery only)",
                lambda q: _jina_ddg_url(f"site:tiktok.com {q}"), _mk),
        Backend("ddg_lite_site_tiktok", "DuckDuckGo Lite site:tiktok.com (discovery only)",
                lambda q: _ddg_lite_url(f"site:tiktok.com {q}"), _hp),
    ],
    "instagram": [
        Backend("searxng_site_instagram", "Local SearXNG site:instagram.com (discovery only)", lambda q: _searxng_url(f"site:instagram.com {q}"), _searxng_parser),
        Backend("jina_duckduckgo_site_instagram", "Jina Reader over DDG site:instagram.com (discovery only)",
                lambda q: _jina_ddg_url(f"site:instagram.com {q}"), _mk),
        Backend("ddg_lite_site_instagram", "DuckDuckGo Lite site:instagram.com (discovery only)",
                lambda q: _ddg_lite_url(f"site:instagram.com {q}"), _hp),
    ],
}


# ── Chain executor ────────────────────────────────────────────────────────


@dataclass
class BackendResult:
    hits: tuple  # tuple[SearchHit, ...] — lazy type to avoid circular import
    engine: str
    backend_name: str
    attempts: list[str] = field(default_factory=list)
    saw_response: bool = False
    error: str = ""


def execute_backend_chain(
    platform: str,
    query: str,
    *,
    limit: int = 5,
    fetch: FetchFn | None = None,
) -> BackendResult:
    """Try each backend in the platform's chain. First success wins."""
    chain = BACKENDS.get(platform, [])
    if not chain:
        return BackendResult(hits=(), engine="none", backend_name="", attempts=[])

    fetcher = fetch or _fetch
    attempts: list[str] = []
    saw_response = False
    last_error = ""

    for backend in chain:
        attempts.append(backend.name)
        try:
            url = backend.build_url(query)
            page = fetcher(url, backend.timeout)
            saw_response = True
            parse_markdown, parse_html = _get_parsers()
            parser = backend.parser()
            parsed_hits = parser(page, max(limit * 10, 25) if backend.accept_url else limit)
            hits = tuple(
                hit
                for hit in parsed_hits
                if (backend.accept_url is None or backend.accept_url(hit.url))
                and (platform not in {"github", "reddit"} or _result_matches_query(hit.url, hit.title, query, hit.snippet))
            )[:limit]
            if hits:
                return BackendResult(
                    hits=hits,
                    engine=backend.name,
                    backend_name=backend.name,
                    attempts=attempts,
                    saw_response=True,
                    error="",
                )
            last_error = f"{backend.name} returned no parseable search results."
        except Exception:
            last_error = f"{backend.name} failed."
            continue

    return BackendResult(hits=(), engine=attempts[-1] if attempts else "none", backend_name=attempts[-1] if attempts else "", attempts=attempts, saw_response=saw_response, error=last_error)
