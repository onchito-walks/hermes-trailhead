from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Route:
    key: str
    task: str
    primary: str
    fallbacks: tuple[str, ...]
    avoid: tuple[str, ...]
    approval_required: bool
    rationale: str
    evidence_needed: tuple[str, ...]
    competitor_lesson: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["fallbacks"] = list(self.fallbacks)
        data["avoid"] = list(self.avoid)
        data["evidence_needed"] = list(self.evidence_needed)
        return data


ROUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "known-url-read": ("url", "link", "page", "pdf", "markdown", "read", "fetch"),
    "discovery-search": ("search", "discover", "find", "research", "sources", "unknown", "current"),
    "structured-extraction": ("schema", "extract", "parse", "structured", "json", "table", "fields"),
    "interactive-browser": ("login", "session", "account", "form", "click", "browser", "dashboard", "captcha", "checkout"),
    "social-current-signal": ("social", "x", "twitter", "reddit", "instagram", "insta", "tiktok", "youtube", "maintainer", "community", "posts", "thread", "sentiment", "creator", "viral"),
    "external-tool-enable": ("install", "enable", "configure", "setup", "tool", "mcp", "server", "package"),
}

# Terms that, when present in the query, penalise a route (demotion signal).
# Each match subtracts 5 from the score. Applied before priority sorting.
NEGATIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interactive-browser": ("read", "fetch", "extract", "pdf", "url", "markdown"),
    "social-current-signal": ("login", "session", "fill", "form", "checkout"),
    "known-url-read": ("discover", "social", "community", "sentiment"),
    "discovery-search": ("login", "fill", "form", "click", "checkout"),
    "structured-extraction": ("login", "search", "discover"),
    "external-tool-enable": ("read", "fetch", "extract", "search"),
}

# Higher number wins when mixed intents touch safety-sensitive surfaces.
ROUTE_PRIORITY: dict[str, int] = {
    "interactive-browser": 100,
    "social-current-signal": 90,
    "external-tool-enable": 80,
    "structured-extraction": 50,
    "known-url-read": 40,
    "discovery-search": 10,
}


ROUTES: tuple[Route, ...] = (
    Route(
        key="known-url-read",
        task="Known URL/page/PDF → readable markdown",
        primary="Hermes web_extract",
        fallbacks=("Jina Reader URL prefix", "Firecrawl scrape/extract", "Crawl4AI markdown generation"),
        avoid=("browser automation as first resort", "custom BeautifulSoup scraper before trying extraction tools"),
        approval_required=False,
        rationale="Known URL reading is a fetch/extract job, not a browser-control job. Keep it cheap and deterministic first.",
        evidence_needed=("source URL", "extractor output", "failure reason if extraction fails"),
        competitor_lesson="Jina Reader wins by making URL→markdown trivial; Crawl4AI wins with deterministic no-LLM extraction.",
    ),
    Route(
        key="discovery-search",
        task="Unknown sources / broad discovery",
        primary="Hermes web_search with primary-source query variation",
        fallbacks=("Exa semantic/deep search", "Firecrawl /agent for autonomous discovery", "social-search in parallel"),
        avoid=("single search query", "SEO snippets as evidence", "crawl before search saturation"),
        approval_required=False,
        rationale="Discovery needs breadth first, then extraction. Search results are leads, not evidence.",
        evidence_needed=("query count", "result count", "extracted page count", "source breakdown"),
        competitor_lesson="Exa’s search tiers and highlights are the right model: choose latency/depth explicitly.",
    ),
    Route(
        key="structured-extraction",
        task="Extract a schema from pages/sites",
        primary="web_extract then schema-specific parser",
        fallbacks=("Firecrawl /extract", "Crawl4AI CSS/XPath/Regex strategies", "Stagehand extract for dynamic pages"),
        avoid=("LLM-only extraction without deterministic selector attempts", "manual scraping with no fixture"),
        approval_required=False,
        rationale="Structured extraction should produce repeatable evidence and tests. Use LLMs after deterministic methods fail or for messy natural-language fields.",
        evidence_needed=("schema", "sample output", "fixture URL", "parser failure modes"),
        competitor_lesson="Firecrawl and Crawl4AI are stronger than Hermes Reach here; Hermes Reach should route to them rather than pretend to be a crawler.",
    ),
    Route(
        key="interactive-browser",
        task="Login/session/form/visual browser work",
        primary="Hermes browser tools for live supervised actions",
        fallbacks=("Browserbase contexts", "Stagehand act/observe/extract/agent", "browser-use for autonomous browser tasks"),
        avoid=("headless scraping of logged-in sites without consent", "cookie extraction as a default"),
        approval_required=True,
        rationale="Interactive browser work can cross account and credential boundaries. It needs explicit human approval and observable execution.",
        evidence_needed=("target site", "account boundary", "allowed actions", "screenshot/log proof"),
        competitor_lesson="Browserbase wins on managed persistent contexts; Stagehand wins on browser primitives. Hermes Reach should be the policy gate before either.",
    ),
    Route(
        key="social-current-signal",
        task="Current social/maintainer/community signal across X, Reddit, TikTok, Instagram, YouTube, and the public web",
        primary="x_search/Nitter for X, Redlib/reddit-search for Reddit, yt-dlp/media tools for YouTube, privacy-frontends or supervised browser for TikTok/Instagram",
        fallbacks=("social-search", "Nitter profile pagination", "reddit-search with structured metadata", "ProxiTok/alternative TikTok frontends when available", "Bibliogram/Instagram frontends when available", "web_search site:x.com/site:reddit.com/site:tiktok.com/site:instagram.com"),
        avoid=("posting", "cookie auth", "claiming all posts from one page", "thin social-search Reddit output for newsletters", "reporting TikTok/Instagram coverage when no frontend/API/browser path is configured"),
        approval_required=True,
        rationale="The goal is broad, reliable social search coverage. Prefer read-only public/privacy frontends and accountless routes first; escalate to browser/account paths only with approval.",
        evidence_needed=("platforms checked", "handles/subreddits/queries", "time window", "retrieved count per platform", "dead-link/coverage caveat"),
        competitor_lesson="Agent-Reach/OpenCLI emphasize practical access to difficult sources; Hermes Reach should make platform coverage visible and route to the best available reader without overstating coverage.",
    ),
    Route(
        key="external-tool-enable",
        task="Install/enable external capability tool",
        primary="Hermes Reach plan + explicit approval",
        fallbacks=("sandbox venv", "temporary clone", "MCP catalog candidate import"),
        avoid=("global npm/pip installs by default", "credentials in plaintext", "installer docs as proof of safety"),
        approval_required=True,
        rationale="External capability tools change the system and may touch credentials. They need a plan, sandbox, doctor result, and rollback story.",
        evidence_needed=("license", "install commands", "credential surfaces", "doctor output", "rollback command"),
        competitor_lesson="Composio/Pipedream/Arcade solve breadth with managed platforms; Hermes Reach should import candidates but keep local governance.",
    ),
)


def all_routes() -> tuple[Route, ...]:
    return ROUTES


def match_routes(query: str) -> list[Route]:
    tokens = [token for token in query.lower().replace("/", " ").replace("-", " ").split() if token]
    scored: list[tuple[int, int, Route]] = []
    for route in ROUTES:
        haystack = " ".join([route.key, route.task, route.primary, route.rationale, " ".join(route.fallbacks)]).lower()
        text_score = sum(1 for token in tokens if re.search(r'\b' + re.escape(token) + r'\b', haystack))
        keyword_score = sum(3 for token in tokens if token in ROUTE_KEYWORDS.get(route.key, ()))
        negative_score = sum(5 for token in tokens if token in NEGATIVE_KEYWORDS.get(route.key, ()))
        score = text_score + keyword_score - negative_score
        if score:
            scored.append((score, ROUTE_PRIORITY.get(route.key, 0), route))
    if not scored:
        return []
    return [route for _, _, route in sorted(scored, key=lambda pair: (-pair[0], -pair[1], pair[2].key))]


def route_for_ranked(query: str, top: int = 3) -> list[Route]:
    matches = match_routes(query)
    if matches:
        return matches[:top]
    return [ROUTES[1]]  # discovery-search is the safest default for unknown research intents


def route_for(query: str) -> Route:
    return route_for_ranked(query, top=1)[0]
