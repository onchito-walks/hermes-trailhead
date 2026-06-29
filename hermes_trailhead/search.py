"""Hermes Trailhead search planning and execution for hard-to-reach internet sources.

`search_run()` returns an agent action plan. `execute_search()` executes that plan through
loginless public search pages rendered by Jina Reader. This keeps the default path free of
paid APIs while still producing real retrieved links when the network path is available.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import re
from typing import Callable, Literal
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import urllib.request

from . import backends
from .channels import check_reddit, check_x_search

Platform = Literal["all", "web", "x", "reddit", "tiktok", "instagram", "youtube", "github"]
SearchStatus = Literal["ready", "planned", "gap", "approval_required"]
ExecutionStatus = Literal["ok", "gap", "blocked"]


@dataclass(frozen=True)
class SearchAction:
    platform: str
    status: SearchStatus
    query: str
    recommended_tool: str
    direct_url: str = ""
    site_query: str = ""
    frontend_url: str = ""
    approval_required: bool = False
    paid_api_required: bool = False
    evidence_needed: tuple[str, ...] = ()
    caveat: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence_needed"] = list(self.evidence_needed)
        return data


@dataclass(frozen=True)
class SearchRun:
    query: str
    platform: str
    mode: str
    paid_api_required: bool
    actions: tuple[SearchAction, ...]

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "platform": self.platform,
            "mode": self.mode,
            "paid_api_required": self.paid_api_required,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SearchExecution:
    platform: str
    status: ExecutionStatus
    query: str
    executed_query: str
    engine: str
    result_count: int
    hits: tuple[SearchHit, ...]
    action_status: SearchStatus
    approval_required: bool
    evidence_state: str
    caveat: str
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status,
            "query": self.query,
            "executed_query": self.executed_query,
            "engine": self.engine,
            "result_count": self.result_count,
            "hits": [hit.to_dict() for hit in self.hits],
            "action_status": self.action_status,
            "approval_required": self.approval_required,
            "evidence_state": self.evidence_state,
            "caveat": self.caveat,
            "error": self.error,
        }


@dataclass(frozen=True)
class ExecutedSearchRun:
    plan: SearchRun
    executions: tuple[SearchExecution, ...]

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.to_dict(),
            "executions": [execution.to_dict() for execution in self.executions],
        }


PLATFORMS: tuple[str, ...] = ("web", "x", "reddit", "tiktok", "instagram", "youtube", "github")
Fetch = Callable[[str, int], str]


@dataclass(frozen=True)
class BackendAttempt:
    url: str
    engine: str
    parser: str  # "markdown" | "html"


def backend_chain(platform: str, query: str, *, site_query: str = "") -> list[BackendAttempt]:
    """Build the ranked backend attempt list for a platform+query.

    Returns pre-built URL/engine/parser attempts so execute_action()
    can iterate without importing backends.py at call time.
    """
    from .backends import BACKENDS

    chain = BACKENDS.get(platform, [])
    executed_query = site_query or query
    attempts: list[BackendAttempt] = []

    for backend in chain:
        url = backend.build_url(executed_query)
        # Determine parser type: if the backend uses _parse_markdown_search_results, it's "markdown"
        parser_type = "markdown" if "markdown" in backend.parser.__name__ else "html"
        attempts.append(BackendAttempt(
            url=url,
            engine=backend.description,
            parser=parser_type,
        ))

    return attempts


def _site_query(site: str, query: str) -> str:
    return f"site:{site} {query}"


def _search_url(engine: str, query: str) -> str:
    if engine == "redlib":
        return f"https://redlib.perennialte.ch/search?q={quote_plus(query)}"
    if engine == "nitter":
        return f"http://localhost:8788/search?f=tweets&q={quote_plus(query)}"
    if engine == "github":
        return f"https://github.com/search?q={quote_plus(query)}"
    if engine == "youtube":
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    return ""


def _fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Hermes Trailhead/0.1",
            "Accept": "text/plain,text/markdown,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


_ORIGINAL_FETCH_TEXT = _fetch_text


def _clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(text).strip()


def _normalize_result_url(url: str) -> str:
    url = html.unescape(url).strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if ("duckduckgo.com" in parsed.netloc.lower() or not parsed.netloc) and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


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


def _parse_markdown_search_results(markdown: str, limit: int) -> tuple[SearchHit, ...]:
    hits: list[SearchHit] = []
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^##+\s+\[(.+?)\]\((https?://[^)]+)\)", line.strip())
        if not match:
            continue
        title = _clean_title(match.group(1))
        url = _normalize_result_url(match.group(2))
        if _is_noise_url(url):
            continue
        snippet_parts: list[str] = []
        for next_line in lines[i + 1 : i + 4]:
            stripped = next_line.strip()
            if not stripped or stripped.startswith("##"):
                break
            if stripped.startswith("[") and "](" in stripped:
                continue
            snippet_parts.append(stripped)
        hits.append(SearchHit(title=title, url=url, snippet=" ".join(snippet_parts)[:300]))
        if len(hits) >= limit:
            break
    return tuple(hits)


def _parse_html_search_results(page: str, limit: int) -> tuple[SearchHit, ...]:
    """Parse loginless DuckDuckGo HTML/Lite results as a Jina fallback."""
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for match in re.finditer(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page, flags=re.I | re.S):
        raw_url, raw_title = match.group(1), match.group(2)
        url = _normalize_result_url(raw_url)
        if _is_noise_url(url) or url in seen:
            continue
        title = _clean_title(raw_title)
        if not title or title.lower() in {"cached", "similar", "more results"}:
            continue
        seen.add(url)
        hits.append(SearchHit(title=title, url=url, snippet=""))
        if len(hits) >= limit:
            break
    return tuple(hits)


def action_for(platform: str, query: str, *, live: bool = False) -> SearchAction:
    if platform == "web":
        return SearchAction(
            platform="web",
            status="ready",
            query=query,
            recommended_tool="web_search or hermes-trailhead --execute",
            site_query=query,
            paid_api_required=False,
            evidence_needed=("query", "result_count", "extracted_source_count", "source URLs"),
            caveat="Use web_extract on promising URLs; search results are leads, not evidence.",
        )

    if platform == "x":
        status: SearchStatus = "planned"
        caveat = "Use x_search if Hermes has it configured; otherwise use Nitter or site:x.com search. Do not use cookie auth without approval."
        if live:
            res = check_x_search(live=True)
            if res.status == "ok":
                status = "ready"
                caveat = res.detail
            else:
                status = "gap"
                caveat = res.detail
        return SearchAction(
            platform="x",
            status=status,
            query=query,
            recommended_tool="x_search, Nitter, or hermes-trailhead --execute site search",
            direct_url=_search_url("nitter", query),
            site_query=_site_query("x.com", query),
            frontend_url="http://localhost:8788",
            approval_required=True,
            paid_api_required=False,
            evidence_needed=("query", "handles checked", "post count", "working links", "coverage caveat"),
            caveat=caveat,
        )

    if platform == "reddit":
        status = "ready"
        caveat = "Prefer Redlib/reddit-search first; browser/cookie auth requires approval."
        if live:
            res = check_reddit(live=True)
            if res.status != "ok":
                status = "gap"
                caveat = res.detail
            else:
                caveat = res.detail
        return SearchAction(
            platform="reddit",
            status=status,
            query=query,
            recommended_tool="Redlib, reddit-search, web_search, or hermes-trailhead --execute site search",
            direct_url=_search_url("redlib", query),
            site_query=_site_query("reddit.com", query),
            frontend_url="https://redlib.perennialte.ch",
            paid_api_required=False,
            evidence_needed=("query/subreddits", "post count", "comment/thread links", "working Redlib or Reddit links"),
            caveat=caveat,
        )

    if platform == "tiktok":
        return SearchAction(
            platform="tiktok",
            status="gap",
            query=query,
            recommended_tool="hermes-trailhead --execute site search, then supervised browser/media tool if needed",
            site_query=_site_query("tiktok.com", query),
            approval_required=True,
            paid_api_required=False,
            evidence_needed=("site query", "video/profile URLs", "retrieved count", "reader/browser caveat"),
            caveat="No dedicated TikTok reader is configured by default. Use site:tiktok.com search first; account/session browser work needs approval.",
        )

    if platform == "instagram":
        return SearchAction(
            platform="instagram",
            status="gap",
            query=query,
            recommended_tool="hermes-trailhead --execute site search, then supervised browser if needed",
            site_query=_site_query("instagram.com", query),
            approval_required=True,
            paid_api_required=False,
            evidence_needed=("site query", "profile/post URLs", "retrieved count", "reader/browser caveat"),
            caveat="No dedicated Instagram reader is configured by default. Use site:instagram.com search first; account/session browser work needs approval.",
        )

    if platform == "youtube":
        return SearchAction(
            platform="youtube",
            status="planned",
            query=query,
            recommended_tool="hermes-trailhead --execute site search, media tools, or yt-dlp if installed",
            direct_url=_search_url("youtube", query),
            site_query=_site_query("youtube.com", query),
            paid_api_required=False,
            evidence_needed=("video URLs", "metadata/transcript availability", "retrieved count"),
            caveat="Use media/transcript tools when available; install yt-dlp only in a project venv when needed.",
        )

    if platform == "github":
        return SearchAction(
            platform="github",
            status="ready",
            query=query,
            recommended_tool="GitHub MCP, gh CLI, or hermes-trailhead --execute site search",
            direct_url=_search_url("github", query),
            site_query=_site_query("github.com", query),
            paid_api_required=False,
            evidence_needed=("repo/issue/PR URLs", "auth boundary", "retrieved count"),
            caveat="Use GitHub MCP first when available; gh CLI for terminal/git workflows.",
        )

    raise ValueError(f"Unknown platform: {platform}")


def search_run(platform: Platform, query: str, *, live: bool = False) -> SearchRun:
    if platform == "all":
        actions = tuple(action_for(p, query, live=live) for p in PLATFORMS)
    else:
        actions = (action_for(platform, query, live=live),)
    return SearchRun(
        query=query,
        platform=platform,
        mode="hermes_trailhead_action_plan",
        paid_api_required=any(action.paid_api_required for action in actions),
        actions=actions,
    )


def execute_action(action: SearchAction, *, limit: int = 5, fetch: Fetch | None = None) -> SearchExecution:
    executed_query = action.site_query or action.query
    fetcher = fetch or _fetch_text
    evidence_state = "discovered_links_only" if action.status == "gap" or action.approval_required else "search_hits"
    allow_native = fetch is None and _fetch_text is _ORIGINAL_FETCH_TEXT
    backend_result = backends.execute_backend_chain(action.platform, action.query, limit=limit, fetch=fetcher, allow_native=allow_native)
    status: ExecutionStatus = "ok" if backend_result.hits else ("gap" if backend_result.saw_response else "blocked")
    error = "" if backend_result.hits else backend_result.error
    return SearchExecution(
        platform=action.platform,
        status=status,
        query=action.query,
        executed_query=executed_query,
        engine=backend_result.engine,
        result_count=len(backend_result.hits),
        hits=backend_result.hits,
        action_status=action.status,
        approval_required=action.approval_required,
        evidence_state=evidence_state,
        caveat=action.caveat,
        error=error,
    )


def execute_search(platform: Platform, query: str, *, live: bool = False, limit: int = 5, fetch: Fetch | None = None) -> ExecutedSearchRun:
    plan = search_run(platform, query, live=live)
    executions = tuple(execute_action(action, limit=limit, fetch=fetch) for action in plan.actions)
    return ExecutedSearchRun(plan=plan, executions=executions)
