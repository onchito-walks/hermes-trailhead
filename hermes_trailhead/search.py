"""Hermes Trailhead search planning and execution for hard-to-reach internet sources.

`search_run()` returns an agent action plan. `execute_search()` executes that plan through
loginless public search pages rendered by Jina Reader. This keeps the default path free of
paid APIs while still producing real retrieved links when the network path is available.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import re
from typing import Callable, Literal, Sequence
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
    # Query this hit was retrieved for.  Carried internally so extraction and
    # scoring can judge relevance without a signature change in callers; the
    # public hit dict stays {title, url, snippet} for backwards compatibility.
    query: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


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
    #: Backend names in the order they were tried.  A lane whose hits came from
    #: the optional Agent Reach fallback says so here (``agent_reach_*``).
    attempts: tuple[str, ...] = ()
    #: Non-empty only when the hits were forwarded from a third-party tool.
    attribution: str = ""
    #: Criteria the caller asked for.  Empty means "no reordering was applied":
    #: hits stay in the order the backend returned them.
    preferred_language: str = ""
    preferred_sources: tuple[str, ...] = ()
    #: Per-hit record of what the URL itself matched (language segment, domain).
    #: This is URL-shape evidence, not a relevance score.
    criteria_matches: tuple[dict, ...] = ()

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
            "attempts": list(self.attempts),
            "attribution": self.attribution,
            "preferred_language": self.preferred_language,
            "preferred_sources": list(self.preferred_sources),
            "criteria_matches": [dict(record) for record in self.criteria_matches],
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
        return f"{backends.REDLIB_LOCAL_URL}/search?q={quote_plus(query)}"
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


_SNIPPET_MAX_CHARS = 300

# Jina Reader renders a DuckDuckGo result block as::
#
#     ## [Title](//duckduckgo.com/l/?uddg=...)
#
#     [![Image 1](//external-content.duckduckgo.com/ip3/host.ico)](//duckduckgo.com/l/?uddg=...)[host/path](//duckduckgo.com/l/?uddg=...)
#
#     [**Snippet** text ...](//duckduckgo.com/l/?uddg=...)
#
# so the snippet is the link *text* of a line that starts a markdown link but is
# not the image line and not the displayed URL line.  Everything below reads
# only what the response actually contains; no snippet is ever composed.
_INLINE_LINK_RE = re.compile(r"^\[(?!!\[)(.+)\]\((https?://[^)\s]+)\)$", re.S)
_DISPLAY_URL_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(/\S*)?$", re.I)


def _display_url_stem(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _is_display_url_line(text: str, hit_url: str) -> bool:
    """True for DuckDuckGo's grey breadcrumb line, which is a URL, not prose."""
    candidate = text.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return False
    if candidate == hit_url or candidate.rstrip("/") == hit_url.rstrip("/"):
        return True
    if candidate.rstrip("/") == _display_url_stem(hit_url).rstrip("/"):
        return True
    return bool(_DISPLAY_URL_RE.match(candidate)) and "." in candidate.split("/")[0]


def _clean_snippet_text(text: str) -> str:
    """Reduce snippet markup to the literal text, keeping the words verbatim."""
    text = html.unescape(text)
    # DuckDuckGo bolds matched terms; Jina renders that as **term** / __term__.
    text = text.replace("**", "").replace("__", "")
    # Backslash escapes that survive the reader pass.
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!])", r"\1", text)
    # "¶" is the source page's heading-anchor glyph, not snippet prose.
    text = text.replace("¶", " ")
    return re.sub(r"\s+", " ", text).strip()


def _snippet_from_block(lines: list[str], start: int, hit_url: str) -> str:
    """Read the snippet text that belongs to the block starting at ``start``.

    The search window stops at the next ``##`` heading, so one block can never
    borrow text from the following result.
    """
    parts: list[str] = []
    for raw_line in lines[start + 1 : start + 8]:
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            break
        if not stripped:
            if parts:
                break
            continue
        if stripped.startswith("[!"):  # favicon / image line
            continue
        link = _INLINE_LINK_RE.match(stripped)
        if link is None and stripped.startswith("[") and ("](" in stripped or "**" in stripped):
            # A line that opens a markdown link/highlight but never closes it is
            # a truncated tail of the reader response, not snippet prose.
            continue
        text = link.group(1) if link else stripped
        if _is_display_url_line(text, hit_url):
            continue
        cleaned = _clean_snippet_text(text)
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)[:_SNIPPET_MAX_CHARS]


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
        snippet = _snippet_from_block(lines, i, url)
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
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


# ── Explicit, caller-supplied relevance criteria ──────────────────────────
#
# Ordering is driven only by what the caller asks for and by what the result URL
# literally contains: a language segment or a domain.  Nothing here reads the
# query text, counts characters of a script, or infers a language from keywords —
# a Chinese query with no criteria keeps the backend order.

#: ISO 639-1 codes recognised as a URL language segment.  Codes outside this set
#: are treated as "unknown" even when they appear in a path segment.
_LANGUAGE_CODES = frozenset(
    """
    af am ar az be bg bn bs ca cs cy da de el en eo es et eu fa fi fil fo fr ga gl
    gu ha he hi hr ht hu hy id is it ja jv ka kk km kn ko ky la lb lo lt lv mg mi
    mk ml mn mr ms mt my ne nl no ny or pa pl ps pt ro ru si sk sl sm sn so sq sr
    st su sv sw ta te tg th tk tl tr tt ug uk ur uz vi xh yi yo zh zu
    """.split()
)

#: Hosts whose leftmost label may be a language (``es.wikipedia.org``).
_URL_HOST_LANGUAGE_MIN_LABELS = 3


def _normalize_language_tag(tag: str) -> str:
    return tag.strip().lower().replace("_", "-")


def language_from_url(url: str) -> str:
    """Return the language tag a URL literally advertises, or ``""``.

    Rules, in order:
    1. the first path segment, if it is a recognised ISO 639-1 code, optionally
       with a region subtag (``/es/``, ``/zh-cn/``, ``/pt-BR/``);
    2. otherwise the leftmost host label when the host has at least three labels
       and that label is a recognised code (``es.wikipedia.org``).
    """
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments:
        candidate = _normalize_language_tag(segments[0])
        base = candidate.split("-")[0]
        if base in _LANGUAGE_CODES and re.fullmatch(r"[a-z]{2}(-[a-z0-9]{2,8})?", candidate):
            return candidate
    labels = parsed.netloc.lower().split(":")
    host = labels[0]
    parts = host.split(".")
    if len(parts) >= _URL_HOST_LANGUAGE_MIN_LABELS and parts[0] in _LANGUAGE_CODES:
        return parts[0]
    return ""


def language_matches(url_language: str, wanted: str) -> bool:
    """URL tag must be at least as specific as the request.

    ``zh`` matches ``zh-cn``; ``zh-cn`` also matches a request for ``zh``;
    ``zh-hans`` and ``zh-cn`` never match each other (no script/region folding).
    """
    have = _normalize_language_tag(url_language)
    want = _normalize_language_tag(wanted)
    if not have or not want:
        return False
    return have == want or have.startswith(want + "-")


def normalize_source(source: str) -> str:
    """Reduce a caller's source hint to a bare lower-case host."""
    candidate = source.strip().lower()
    if "://" in candidate:
        candidate = urlparse(candidate).netloc.lower()
    candidate = candidate.split("/")[0].split(":")[0]
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate


def source_matches(url: str, source: str) -> bool:
    """Domain match: equal host, or a real subdomain of the requested source."""
    wanted = normalize_source(source)
    host = urlparse(url.strip()).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not wanted or not host:
        return False
    return host == wanted or host.endswith("." + wanted)


def order_hits_by_criteria(
    hits: Sequence[SearchHit],
    *,
    preferred_language: str = "",
    preferred_sources: Sequence[str] = (),
) -> tuple[tuple[SearchHit, ...], tuple[dict, ...]]:
    """Stable-partition hits on the caller's criteria; never invents a rank.

    Every hit that satisfies the active criteria keeps its backend order relative
    to the others that satisfy them too.  Precedence is language first, then
    domain, then untouched backend order.  With no criteria the input order is
    returned unchanged.
    """
    sources = tuple(normalize_source(source) for source in preferred_sources if normalize_source(source))
    records: list[dict] = []
    keyed: list[tuple[tuple[int, int], SearchHit, dict]] = []
    want_language = _normalize_language_tag(preferred_language)
    for hit in hits:
        language = language_from_url(hit.url)
        language_match = language_matches(language, want_language) if want_language else False
        matched_sources = tuple(source for source in sources if source_matches(hit.url, source))
        record = {
            "url": hit.url,
            "url_language": language,
            "language_match": language_match,
            "source_matches": list(matched_sources),
        }
        records.append(record)
        key = (
            0 if (not want_language or language_match) else 1,
            0 if (not sources or matched_sources) else 1,
        )
        keyed.append((key, hit, record))
    if not want_language and not preferred_sources:
        return tuple(hits), tuple(records)
    ordered = sorted(keyed, key=lambda item: item[0])  # sorted() is stable
    return tuple(item[1] for item in ordered), tuple(item[2] for item in ordered)


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
        caveat = "Prefer the local Redlib instance first; browser/cookie auth requires approval."
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
            recommended_tool="Local Redlib instance, reddit-search, web_search, or hermes-trailhead --execute site search",
            direct_url=_search_url("redlib", query),
            site_query=_site_query("reddit.com", query),
            frontend_url=backends.REDLIB_LOCAL_URL,
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


def execute_action(
    action: SearchAction,
    *,
    limit: int = 5,
    fetch: Fetch | None = None,
    reach_adapter: object | None = None,
    preferred_language: str = "",
    preferred_sources: Sequence[str] = (),
) -> SearchExecution:
    executed_query = action.site_query or action.query
    fetcher = fetch or _fetch_text
    evidence_state = "discovered_links_only" if action.status == "gap" or action.approval_required else "search_hits"
    # The chain always receives a fetcher (the real default above), so `fetch is
    # None` cannot be re-derived downstream.  Decide here, where an injected
    # fixture fetcher is still distinguishable, and pass both signals explicitly.
    trusted_runtime = fetch is None and _fetch_text is _ORIGINAL_FETCH_TEXT
    backend_result = backends.execute_backend_chain(
        action.platform,
        action.query,
        limit=limit,
        fetch=fetcher,
        allow_native=trusted_runtime,
        allow_reach=trusted_runtime,
        reach_adapter=reach_adapter,
    )
    status: ExecutionStatus = "ok" if backend_result.hits else ("gap" if backend_result.saw_response else "blocked")
    error = "" if backend_result.hits else backend_result.error
    # Ordering is a caller preference over URL evidence only.  With no criteria
    # this returns the backend order untouched.
    ordered_hits, criteria_matches = order_hits_by_criteria(
        backend_result.hits,
        preferred_language=preferred_language,
        preferred_sources=preferred_sources,
    )
    # Stamp the query onto each hit so downstream extraction/scoring can judge
    # evidence relevance without changing their signatures.
    hits = tuple(
        SearchHit(title=hit.title, url=hit.url, snippet=hit.snippet, query=action.query)
        for hit in ordered_hits
    )
    return SearchExecution(
        platform=action.platform,
        status=status,
        query=action.query,
        executed_query=executed_query,
        engine=backend_result.engine,
        result_count=len(hits),
        hits=hits,
        action_status=action.status,
        approval_required=action.approval_required,
        evidence_state=evidence_state,
        caveat=action.caveat,
        error=error,
        attempts=tuple(backend_result.attempts),
        attribution=backend_result.attribution,
        preferred_language=_normalize_language_tag(preferred_language),
        preferred_sources=tuple(
            source for source in (normalize_source(s) for s in preferred_sources) if source
        ),
        criteria_matches=criteria_matches,
    )


def execute_search(
    platform: Platform,
    query: str,
    *,
    live: bool = False,
    limit: int = 5,
    fetch: Fetch | None = None,
    reach_adapter: object | None = None,
    preferred_language: str = "",
    preferred_sources: Sequence[str] = (),
) -> ExecutedSearchRun:
    plan = search_run(platform, query, live=live)
    executions = tuple(
        execute_action(
            action,
            limit=limit,
            fetch=fetch,
            reach_adapter=reach_adapter,
            preferred_language=preferred_language,
            preferred_sources=preferred_sources,
        )
        for action in plan.actions
    )
    return ExecutedSearchRun(plan=plan, executions=executions)
