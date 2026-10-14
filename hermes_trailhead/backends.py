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
import shutil
import subprocess
from pathlib import Path
import urllib.request
from typing import Callable
from urllib.parse import parse_qs, quote_plus, urlparse


FetchFn = Callable[[str, int], str]
CommandFn = Callable[..., subprocess.CompletedProcess]


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


REDLIB_LOCAL_URL = "http://127.0.0.1:8789"


def _redlib_search_url(query: str) -> str:
    """Local self-hosted Redlib instance (privacy Reddit frontend).

    The local instance at 127.0.0.1:8789 serves search + thread pages with
    readable HTML (post + comments) from the VPS.  Remote public Redlib
    instances and reddit.com OAuth stay blocked (see README prior-art note).
    """
    return f"{REDLIB_LOCAL_URL}/search?q={quote_plus(query)}&sort=relevance"


def _redlib_parser() -> Callable:
    return _parse_redlib_results


def _parse_redlib_results(page: str, limit: int):
    """Parse local Redlib search HTML into Reddit hits (canonical reddit.com URLs)."""
    from .search import SearchHit

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'<h2 class="post_title">\s*(?:<a[^>]*class="post_flair"[^>]*>.*?</a>\s*)?'
        r'<a href="(/r/[^"]+/comments/[^"]+)"[^>]*>(.*?)</a>',
        page,
        flags=re.I | re.S,
    ):
        path = html.unescape(match.group(1)).rstrip("/")
        title = _clean_title(html.unescape(match.group(2)))
        url = f"https://www.reddit.com{path}"
        if not title or url in seen or not _reddit_result_url(url):
            continue
        seen.add(url)
        hits.append(SearchHit(title=title, url=url, snippet=""))
        if len(hits) >= limit:
            break
    return tuple(hits)


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


def _tiktok_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host.startswith("shop."):
        # TikTok Shop listings are commercial pages, not creator content.
        return False
    return "tiktok.com" in host and not path.startswith(("/about", "/legal", "/login"))


def _open_web_result_url(url: str) -> bool:
    """Web lane accepts open-web content only.

    Interactive-media hosts handled by dedicated lanes (YouTube, TikTok,
    Instagram, Facebook) are rejected here — their family lanes return them
    with richer evidence (transcripts, captions), and a web-lane extraction of
    a platform page mostly yields `blocked` noise at the top of the results.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return not any(
        d in host
        for d in ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "twitch.tv")
    )


def _instagram_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    # Reject navigation/aggregation shells. `/popular/x` (and the legacy
    # `/explore/tags/`) resolve to hashtag aggregation pages, not deep post
    # content — they carry no caption and extract as junk. Only real post/reel
    # and profile routes are worth keeping for discovery.
    return "instagram.com" in host and not path.startswith(
        ("/about", "/accounts", "/explore/tags", "/popular")
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


# ── Lane-native discovery backends ────────────────────────────────────────

def _search_hit(title: str, url: str, snippet: str = ""):
    from .search import SearchHit

    return SearchHit(title=title, url=url, snippet=snippet)


def _resolve_ytdlp() -> str | None:
    """Resolve the yt-dlp executable, including the project venv.

    The doctor/capability check and the flat-search backend must agree on where
    yt-dlp lives. It is normally installed only in the Trailhead project venv,
    which may not be on PATH under a cron/chroot profile HOME — so check PATH
    first, then fall back to the canonical Trailhead venv binary.
    """
    on_path = shutil.which("yt-dlp")
    if on_path:
        return on_path
    venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp"
    if venv.exists():
        return str(venv)
    return None


def _run_ytdlp_flat_search(query: str, limit: int, *, timeout: int = 20, runner: CommandFn | None = None):
    """Discover YouTube videos via yt-dlp flat search without fetching video pages."""
    ytdlp = _resolve_ytdlp() if runner is None else "yt-dlp"
    if runner is None and ytdlp is None:
        return tuple()
    assert ytdlp is not None
    run = runner or subprocess.run
    try:
        completed = run(
            [ytdlp, f"ytsearch{max(limit, 1)}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return tuple()
    hits = []
    seen: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("webpage_url") or row.get("url") or "").strip()
        video_id = str(row.get("id") or "").strip()
        if video_id and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not title or not _youtube_result_url(url) or url in seen:
            continue
        seen.add(url)
        description = str(row.get("description") or "").strip()
        snippet = description[:300] if description else "YouTube video — description not available in discovery"
        hits.append(_search_hit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return tuple(hits)


def _github_query_terms(query: str) -> tuple[str, ...]:
    """Query terms for GitHub's search API.

    GitHub search is near-exact (all terms must match), so numeric-axis
    compounds are kept as hyphenated tokens ("5 axis" -> "5-axis") — the
    generic web/social tokenizer drops both halves ("5" for length, "axis"
    only survives alone), which reduced queries like "DIY 5 axis 3D printer"
    to the single generic term "axis" and returned unrelated repos.
    """
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    terms: list[str] = []
    skip_next = False
    for i, tok in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok.isdigit() and nxt == "axis":
            compound = f"{tok}-axis"
            if compound not in terms:
                terms.append(compound)
            skip_next = True
            continue
        if len(tok) >= 4 and tok not in QUERY_STOPWORDS and tok not in terms:
            terms.append(tok)
    return tuple(terms)


def _github_api_search_url(query: str, endpoint: str) -> str:
    """GitHub public search API URL (free, no auth, rate-limited unauthenticated).

    GitHub search is exact-match over the raw query string, unlike web search:
    a verbose multi-word query (e.g. "VORON Stealthchanger 3D printer") returns
    zero results because every token must match.  Reduce to the top meaningful
    terms (keeping numeric-axis compounds like "5-axis") so the API finds the
    canonical repos/issues the caller actually wants.
    """
    terms = _github_query_terms(query)
    gh_query = " ".join(terms) if terms else query
    qualifier = "+in:title" if endpoint == "issues" else ""
    return f"https://api.github.com/search/{endpoint}?q={quote_plus(gh_query)}{qualifier}&per_page=6"


def _github_token() -> str:
    """GITHUB_TOKEN from the process env or $HERMES_HOME/.env (value at runtime).

    Authenticated GitHub API = 5,000 req/hr core and 30 search req/min vs 60/hr
    and ~10/min anonymous.  The token is attached only to outbound API
    requests; it is never logged, printed, or returned by lane tools.
    """
    import os

    key = os.environ.get("GITHUB_TOKEN", "")
    if key:
        return key
    env_path = resolve_hermes_home() / ".env"
    if os.path.exists(env_path):
        try:
            for line in open(env_path):
                if line.startswith("GITHUB_TOKEN="):
                    return line.strip().split("=", 1)[1].strip("\"' \t")
        except OSError:
            pass
    return ""


def _github_request_headers() -> dict[str, str]:
    """Headers for GitHub API requests — Bearer auth when a token exists."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Hermes-Trailhead"}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _run_github_api_search(
    query: str,
    limit: int,
    *,
    timeout: int = 20,
    opener: Callable[[str, int], str] | None = None,
):
    """Discover GitHub repos, issues, and PRs via GitHub's public search API.

    This is the canonical lane-native discovery for GitHub.  The native
    ``github.com/search`` HTML page is a JS shell that parses to nothing but
    marketing links, and generic ``site:github.com`` web search routinely
    misses the primary repo.  GitHub's search API returns real repo/issue/PR
    URLs from a datacenter IP with no account, well within the free
    unauthenticated limit (~10 search req/min).  On rate-limit or transient
    errors it returns empty so the chain falls through to HTTP backends.
    """
    from .search import SearchHit

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for endpoint in ("repositories", "issues"):
        url = _github_api_search_url(query, endpoint)
        try:
            if opener is not None:
                page = opener(url, timeout)
            else:
                req = urllib.request.Request(url, headers=_github_request_headers())
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    page = resp.read().decode("utf-8", errors="replace")
            data = json.loads(page)
        except Exception:
            continue
        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if endpoint == "repositories":
                url = str(item.get("html_url") or "").strip()
                full_name = str(item.get("full_name") or "").strip()
                title = full_name or url
                stars = item.get("stargazers_count") or 0
                desc = str(item.get("description") or "").strip()
                snippet = f"{desc} — {stars} stars" if desc else f"{stars} stars"
            else:
                url = str(item.get("html_url") or "").strip()
                repo = item.get("repository", {}) or {}
                repo_name = str(repo.get("full_name") or "").strip()
                ititle = str(item.get("title") or "").strip()
                title = f"[{repo_name}] {ititle}" if repo_name else ititle
                snippet = ititle
            if not url or not _github_result_url(url) or url in seen:
                continue
            if not _result_matches_query(url, title, query, snippet):
                continue
            seen.add(url)
            hits.append(_search_hit(title=title, url=url, snippet=snippet))
            if len(hits) >= limit:
                return tuple(hits)
    return tuple(hits)


def _social_search_url(platform: str, title: str, author: str, query: str) -> str:
    if platform == "x":
        # Profile pages are poor results — use search to find actual posts.
        return f"https://x.com/search?q={quote_plus(query)}"
    if platform == "tiktok":
        handle = author.strip().lstrip("@")
        if handle:
            return f"https://www.tiktok.com/@{handle.split()[0]}"
        return f"https://www.tiktok.com/search?q={quote_plus(title or query)}"
    if platform == "instagram":
        handle = author.strip().lstrip("@")
        if handle:
            return f"https://www.instagram.com/{handle.split()[0]}/"
        return f"https://www.instagram.com/explore/search/keyword/?q={quote_plus(title or query)}"
    subreddit_match = re.search(r"r/([A-Za-z0-9_]+)", author)
    if subreddit_match:
        subreddit = subreddit_match.group(1)
        # Use the original search query, not the post text, for the URL.
        # Post text makes terrible search queries; the user's terms find the post.
        return f"https://www.reddit.com/r/{subreddit}/search/?q={quote_plus(query)}&restrict_sr=1"
    return f"https://www.reddit.com/search/?q={quote_plus(query)}"


def _run_social_search(platform: str, query: str, limit: int, *, timeout: int = 20, runner: CommandFn | None = None):
    """Use the local composite social-search tool as lane-native discovery fallback."""
    source = {"reddit": "reddit", "x": "x", "tiktok": "tiktok", "instagram": "ig"}.get(platform)
    if not source:
        return tuple()
    if runner is None and not shutil.which("social-search"):
        return tuple()
    terms = _query_terms(query)
    social_query = " ".join(terms) if terms else query
    run = runner or subprocess.run
    try:
        completed = run(
            ["social-search", social_query, "--sources", source, "--raw"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return tuple()
    try:
        data = json.loads(completed.stdout or "{}")
    except Exception:
        return tuple()
    key = {"reddit": "Reddit", "x": "X/Twitter", "tiktok": "TikTok", "instagram": "Instagram"}.get(platform, platform)
    hits = []
    seen: set[str] = set()
    for row in data.get(key, []) if isinstance(data, dict) else []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        author = str(row.get("author") or "").strip()
        if not text:
            continue
        haystack = f"{text} {author}".lower()
        if terms and not any(term in haystack for term in terms):
            continue
        title = text.splitlines()[0][:140]
        url = _social_search_url(platform, title, author, query)
        dedupe = f"{platform}:{title}:{author}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        meta = " ".join(part for part in [author, f"likes={row.get('likes')}" if row.get("likes") else "", f"comments/retweets={row.get('retweets')}" if row.get("retweets") else ""] if part)
        snippet = f"{text}\n{meta}".strip()
        hits.append(_search_hit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return tuple(hits)


# ── Tavily Search API ────────────────────────────────────────────────────

def _tavily_api_key() -> str:
    import os

    key = os.environ.get("TAVILY_API_KEY", "")
    if key:
        return key
    env_path = resolve_hermes_home() / ".env"
    if os.path.exists(env_path):
        try:
            for line in open(env_path):
                if line.startswith("TAVILY_API_KEY="):
                    return line.strip().split("=", 1)[1].strip("\"' \t")
        except OSError:
            pass
    return ""


def _tavily_search(platform: str, query: str, limit: int, *, timeout: int = 15) -> tuple:
    """Use Tavily Search API as a reliable paid fallback for gated platforms."""
    api_key = _tavily_api_key()
    if not api_key:
        return tuple()

    domain = {"tiktok": "tiktok.com", "instagram": "instagram.com"}.get(platform)
    if not domain:
        return tuple()

    search_query = f"site:{domain} {query}"
    body = json.dumps(
        {
            "api_key": api_key,
            "query": search_query,
            "max_results": max(limit, 5),
            "include_domains": [domain],
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:
        return tuple()

    results = data.get("results", [])
    hits: list = []
    seen: set[str] = set()
    for r in results:
        url = str(r.get("url", "")).strip()
        title = str(r.get("title", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = str(r.get("content", "")).strip()[:300]
        hits.append(_search_hit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return tuple(hits)


# ── Platform backend chains ───────────────────────────────────────────────


BACKENDS: dict[str, list[Backend]] = {
    "github": [
        Backend("searxng_site_github", "Local SearXNG site:github.com", lambda q: _searxng_url(f"site:github.com {q}"), _searxng_parser, accept_url=_github_result_url, timeout=10),
        Backend("ddg_lite_site_github", "DuckDuckGo Lite site:github.com",
                lambda q: _ddg_lite_url(f"site:github.com {q}"), _hp, accept_url=_github_result_url),
        Backend("jina_duckduckgo_site_github", "Jina Reader over DuckDuckGo site:github.com",
                lambda q: _jina_ddg_url(f"site:github.com {q}"), _mk, accept_url=_github_result_url),
        Backend("bing_search", "Bing search", _bing_search_url, _bing_parser, accept_url=_github_result_url),
        Backend("github_search", "GitHub repository search", _github_search_url, _hp, accept_url=_github_result_url),
    ],
    "reddit": [
        # Local Redlib instance serves search + threads (verified 2026-10-14):
        # lane-native, free, no proxy needed.  Remote public Redlib instances
        # stay blocked and the social-search binary is absent on both machines,
        # so DDG/Jina remain as fallbacks.
        Backend("redlib_local_search", "Local Redlib instance search",
                _redlib_search_url, _redlib_parser, accept_url=_reddit_result_url, timeout=15),
        Backend("ddg_lite_site_reddit", "DuckDuckGo Lite site:reddit.com",
                lambda q: _ddg_lite_url(f"site:reddit.com {q}"), _hp, accept_url=_reddit_result_url),
        Backend("jina_duckduckgo_site_reddit", "Jina Reader over DuckDuckGo site:reddit.com",
                lambda q: _jina_ddg_url(f"site:reddit.com {q}"), _mk, accept_url=_reddit_result_url),
    ],
    "youtube": [
        Backend("ddg_lite_site_youtube", "DuckDuckGo Lite site:youtube.com",
                lambda q: _ddg_lite_url(f"site:youtube.com/watch {q}"), _hp, accept_url=_youtube_result_url),
        Backend("jina_duckduckgo_site_youtube", "Jina Reader over DuckDuckGo site:youtube.com",
                lambda q: _jina_ddg_url(f"site:youtube.com/watch {q}"), _mk, accept_url=_youtube_result_url),
        Backend("searxng_site_youtube", "Local SearXNG site:youtube.com/watch", lambda q: _searxng_url(f"site:youtube.com/watch {q}"), _searxng_parser, accept_url=_youtube_result_url, timeout=10),
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
        Backend("ddg_lite", "DuckDuckGo Lite", _ddg_lite_url, _hp, accept_url=_open_web_result_url),
        Backend("ddg_html", "DuckDuckGo HTML", _ddg_html_url, _hp, accept_url=_open_web_result_url),
        Backend("jina_duckduckgo", "Jina Reader over DuckDuckGo", _jina_ddg_url, _mk, accept_url=_open_web_result_url),
        Backend("bing_search", "Bing search", _bing_search_url, _bing_parser, accept_url=_open_web_result_url),
        Backend("searxng", "Local SearXNG", _searxng_url, _searxng_parser, accept_url=_open_web_result_url, timeout=10),
    ],
    "tiktok": [
        Backend("ddg_lite_site_tiktok", "DuckDuckGo Lite site:tiktok.com (discovery only)",
                lambda q: _ddg_lite_url(f"site:tiktok.com {q}"), _hp, accept_url=_tiktok_result_url),
        Backend("jina_duckduckgo_site_tiktok", "Jina Reader over DDG site:tiktok.com (discovery only)",
                lambda q: _jina_ddg_url(f"site:tiktok.com {q}"), _mk, accept_url=_tiktok_result_url),
        Backend("searxng_site_tiktok", "Local SearXNG site:tiktok.com (discovery only)", lambda q: _searxng_url(f"site:tiktok.com {q}"), _searxng_parser, accept_url=_tiktok_result_url, timeout=10),
        Backend("bing_site_tiktok", "Bing site:tiktok.com (discovery only)", lambda q: _bing_search_url(f"site:tiktok.com {q}"), _bing_parser, accept_url=_tiktok_result_url),
        Backend("tavily_tiktok", "Tavily Search API (paid fallback)", lambda q: "", _hp, accept_url=_tiktok_result_url),
    ],
    "instagram": [
        Backend("ddg_lite_site_instagram", "DuckDuckGo Lite site:instagram.com (discovery only)",
                lambda q: _ddg_lite_url(f"site:instagram.com {q}"), _hp, accept_url=_instagram_result_url),
        Backend("jina_duckduckgo_site_instagram", "Jina Reader over DDG site:instagram.com (discovery only)",
                lambda q: _jina_ddg_url(f"site:instagram.com {q}"), _mk, accept_url=_instagram_result_url),
        Backend("searxng_site_instagram", "Local SearXNG site:instagram.com (discovery only)", lambda q: _searxng_url(f"site:instagram.com {q}"), _searxng_parser, accept_url=_instagram_result_url, timeout=10),
        Backend("bing_site_instagram", "Bing site:instagram.com (discovery only)", lambda q: _bing_search_url(f"site:instagram.com {q}"), _bing_parser, accept_url=_instagram_result_url),
        Backend("tavily_instagram", "Tavily Search API (paid fallback)", lambda q: "", _hp, accept_url=_instagram_result_url),
    ],
}


# ── Chain executor ────────────────────────────────────────────────────────


# ── Circuit breaker ───────────────────────────────────────────────────────
# Prevents thrashing on backends that are consistently failing.  If a backend
# fails 3+ times in the last 5-minute window, the circuit opens — Trailhead
# skips that backend and tries the next one.  The circuit auto-closes when
# enough time passes (5 min since last failure).  Successful requests reset
# the counter immediately.
#
# State lives in ~/.hermes/state/trailhead-circuits.json — lightweight JSON,
# no external dependencies.  The Lane Guardian cron auto-clears stale state.

import time as _time

from .paths import hermes_state_dir, resolve_hermes_home

_DEFAULT_CIRCUIT_PATH = hermes_state_dir() / "trailhead-circuits.json"
_CIRCUIT_WINDOW_SECONDS = 300   # 5 min
_CIRCUIT_THRESHOLD = 3          # open after 3 consecutive failures


def _load_circuits(path: Path | None = None) -> dict[str, list[float]]:
    p = path or _DEFAULT_CIRCUIT_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        return {k: [float(t) for t in v] for k, v in (raw or {}).items()}
    except Exception:
        return {}


def _save_circuits(circuits: dict[str, list[float]], path: Path | None = None) -> None:
    p = path or _DEFAULT_CIRCUIT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(circuits, indent=2))


def _circuit_open(backend_name: str, path: Path | None = None) -> bool:
    """Return True if this backend's circuit breaker is open (skip it)."""
    circuits = _load_circuits(path)
    failures = circuits.get(backend_name, [])
    now = _time.time()
    # Drop stale failures outside the window
    fresh = [t for t in failures if now - t < _CIRCUIT_WINDOW_SECONDS]
    return len(fresh) >= _CIRCUIT_THRESHOLD


def _record_circuit_failure(backend_name: str, path: Path | None = None) -> None:
    """Record a failure for this backend."""
    circuits = _load_circuits(path)
    circuits.setdefault(backend_name, []).append(_time.time())
    # Trim to last 10 entries per backend (avoids unbounded growth)
    circuits[backend_name] = circuits[backend_name][-10:]
    _save_circuits(circuits, path)


def _reset_circuit(backend_name: str, path: Path | None = None) -> None:
    """Reset the circuit for this backend (it returned results successfully)."""
    circuits = _load_circuits(path)
    circuits.pop(backend_name, None)
    _save_circuits(circuits, path)


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
    allow_native: bool | None = None,
) -> BackendResult:
    """Try each backend in the platform's chain. First success wins."""
    chain = BACKENDS.get(platform, [])
    if not chain:
        return BackendResult(hits=(), engine="none", backend_name="", attempts=[])

    fetcher = fetch or _fetch
    attempts: list[str] = []
    saw_response = False
    last_error = ""

    if allow_native is None:
        allow_native = fetch is None

    # Real runtime gets lane-native discovery before generic public-search fallbacks.
    # Tests that inject `fetch` keep the old deterministic HTTP-only path unless
    # callers explicitly opt in with allow_native=True.
    if allow_native:
        if platform == "youtube":
            attempts.append("yt_dlp_flat_search")
            hits = _run_ytdlp_flat_search(query, limit, timeout=20)
            if hits:
                return BackendResult(hits=hits, engine="yt_dlp_flat_search", backend_name="yt_dlp_flat_search", attempts=attempts, saw_response=True, error="")
            last_error = "yt_dlp_flat_search returned no video discovery results."
        elif platform == "reddit":
            attempts.append("social_search_reddit")
            hits = _run_social_search("reddit", query, limit, timeout=20)
            if hits:
                return BackendResult(hits=hits, engine="social_search_reddit", backend_name="social_search_reddit", attempts=attempts, saw_response=True, error="")
            last_error = "social_search_reddit returned no practitioner leads."
        elif platform == "github":
            attempts.append("github_api_search")
            hits = _run_github_api_search(query, limit, timeout=20)
            if hits:
                return BackendResult(hits=hits, engine="github_api_search", backend_name="github_api_search", attempts=attempts, saw_response=True, error="")
            last_error = "github_api_search returned no repos/issues."

    for backend in chain:
        attempts.append(backend.name)
        # Circuit breaker: skip backends that have failed 3+ times in 5 min
        if _circuit_open(backend.name):
            attempts.append(f"{backend.name}_circuit_open")
            last_error = f"{backend.name} skipped — circuit breaker open."
            continue
        try:
            # Tavily backends call the API directly instead of HTTP fetch+parse.
            if backend.name.startswith("tavily_"):
                platform_key = {"tavily_tiktok": "tiktok", "tavily_instagram": "instagram"}.get(backend.name)
                if platform_key:
                    hits = _tavily_search(platform_key, query, limit, timeout=15)
                    if hits:
                        return BackendResult(
                            hits=hits,
                            engine=backend.name,
                            backend_name=backend.name,
                            attempts=attempts,
                            saw_response=True,
                            error="",
                        )
                    last_error = f"{backend.name} returned no results."
                    continue
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
                _reset_circuit(backend.name)
                return BackendResult(
                    hits=hits,
                    engine=backend.name,
                    backend_name=backend.name,
                    attempts=attempts,
                    saw_response=True,
                    error="",
                )
            last_error = f"{backend.name} returned no parseable search results."
            _record_circuit_failure(backend.name)
        except Exception:
            last_error = f"{backend.name} failed."
            _record_circuit_failure(backend.name)
            continue

    if allow_native and platform in {"x", "tiktok", "instagram"}:
        backend_name = f"social_search_{platform}"
        attempts.append(backend_name)
        hits = _run_social_search(platform, query, limit, timeout=12)
        if hits:
            return BackendResult(hits=hits, engine=backend_name, backend_name=backend_name, attempts=attempts, saw_response=True, error="")
        last_error = last_error or f"{backend_name} returned no social leads."

    return BackendResult(hits=(), engine=attempts[-1] if attempts else "none", backend_name=attempts[-1] if attempts else "", attempts=attempts, saw_response=saw_response, error=last_error)
