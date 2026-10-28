"""Hermes Trailhead source-quality scoring — rank search hits by likely usefulness.

After ``search --execute`` returns hits, this module classifies each hit by source
quality and assigns a score. Higher scores go to maintainer/official/canonical
sources, practitioner firsthand reports, current discussion, and GitHub issues/PRs.
Lower scores go to SEO farms, listicles, empty platform shells, and dead links.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import re
from urllib.parse import urlparse

from .extract import ExtractedHit, _is_html_shell, _looks_like_extraction_error, classify_page_shell


def _clean_summary_text(text: str) -> str:
    """Return a compact usable summary, stripping obvious HTML/script chrome."""
    text = text or ""
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _best_summary(content: str, snippet: str, title: str = "") -> str:
    """Prefer clean extracted content; fall back to discovery snippet/caption/title."""
    raw = content or ""
    snippet = (snippet or "").strip()
    title = (title or "").strip()
    snippet_lower = snippet.lower()
    bad_snippet = (
        "javascript is not available" in snippet_lower
        or "enable javascript or switch to a supported browser" in snippet_lower
        or "we cannot provide a description for this page right now" in snippet_lower
    )
    fallback = title if bad_snippet else (snippet or title)
    lower = raw[:2000].lower()
    looks_like_shell = (
        "<!doctype html" in lower
        or "<html" in lower
        or "data-app-env=\"prod\"" in lower
        or "youtube transcript:\n\ncomments" in lower
        or "javascript is not available" in lower
        or "enable javascript or switch to a supported browser" in lower
        or "red lib" in lower
        or "main feeds" in lower
    )
    cleaned = _clean_summary_text(raw)
    # Platform shells (Redlib feeds, X JS blockers, YouTube bot walls) produce
    # useless cleaned text — navigation menus, trending garbage.  Always use
    # the search snippet for these.
    platform_shell = any(m in lower for m in (
        "red lib", "main feeds", "youtube transcript:\n\ncomments",
        "javascript is not available", "enable javascript or switch to a supported browser",
    ))
    if platform_shell:
        return fallback[:1200]
    # Regular HTML (web pages, docs) — try cleaned text first.
    if looks_like_shell:
        if len(cleaned) >= 80:
            return cleaned[:1200] + ("..." if len(cleaned) > 1200 else "")
        return fallback[:1200]
    if len(cleaned) >= 80:
        return cleaned[:1200] + ("..." if len(cleaned) > 1200 else "")
    if fallback:
        return fallback[:1200]
    return cleaned


@dataclass(frozen=True)
class EvidenceAssessment:
    """Usability + query relevance for one hit's retrieved text.

    Extraction ``status == "ok"`` only proves the transport worked.  This
    assessment answers the next question — can the text be cited for *this*
    query? — without changing or hiding the extraction status.
    """
    usable: bool
    relevance: str = "unknown"  # relevant | partial | unrelated | unknown
    reasons: tuple[str, ...] = ()
    transport_ok: bool = False

    def to_dict(self) -> dict:
        return {
            "usable": self.usable,
            "relevance": self.relevance,
            "reasons": list(self.reasons),
            "transport_ok": self.transport_ok,
        }


# Words that carry no topical signal in a search query.  Deliberately small:
# dropping too much risks treating a real topic word as noise.
_QUERY_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "what", "when", "where", "which", "who", "why",
    "with", "vs", "versus", "about", "latest", "best", "new", "news",
})

# Profile URL shapes: path with a single handle segment.
_SOCIAL_PROFILE_HOSTS = frozenset({
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com",
    "x.com", "www.x.com",
    "twitter.com", "www.twitter.com", "mobile.twitter.com",
})
_IG_RESERVED_ROOTS = frozenset({
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "about",
    "developer", "developers", "legal", "directory", "web", "emails",
})
_X_RESERVED_ROOTS = frozenset({
    "i", "home", "search", "explore", "settings", "messages", "notifications",
    "compose", "login", "logout", "signup", "intent", "share", "hashtag",
    "tos", "privacy", "about", "download", "jobs",
})

# A profile URL with no content still transports cleanly.  Only *content*
# markers count: an explicit "no posts/no videos" phrase or a literal zero
# posts/videos count.  Follower and following counts are deliberately excluded —
# an account with 0 followers and 0 following can still have a full feed of real
# posts, so those numbers alone never mean "no content".
_EMPTY_PROFILE_MARKERS = (
    re.compile(r"\bno (?:posts?|videos?)\b"),
    re.compile(r"\b0 (?:posts?|videos?)\b"),
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Split a query run at script boundaries: "华为Mate60" -> "华为" + "Mate60".
_MIXED_SCRIPT_SPLIT = re.compile(r"[0-9A-Za-z]+|[\u4e00-\u9fff]+")
_MIN_CJK_OVERLAP = 2


def _normalize_term(term: str) -> str:
    """Lowercase a token and fold the most common English inflections."""
    term = term.lower().strip("'’-")
    term = re.sub(r"['’]s$", "", term)
    if len(term) > 4 and term.endswith("ies"):
        term = term[:-3] + "y"
    elif len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        term = term[:-1]
    return term


def _tokenize(text: str) -> set[str]:
    """Topical tokens for relevance matching (hyphens/punctuation split)."""
    return {_normalize_term(tok) for tok in re.findall(r"[0-9A-Za-z\u4e00-\u9fff]+", text or "")}


def _query_terms(query: str) -> tuple[str, ...]:
    """Meaningful query terms, in order, deduplicated.  Empty query -> ().

    Runs are split at Latin/CJK boundaries (``华为Mate60`` -> ``华为``,
    ``mate60``) so spaced text still matches.  A pure-CJK run stays whole: CJK
    is not whitespace-delimited, and the run is matched through contiguous
    sub-strings in :func:`assess_relevance`.
    """
    terms: list[str] = []
    for run in re.findall(r"[0-9A-Za-z\u4e00-\u9fff]+", query or ""):
        for raw in _MIXED_SCRIPT_SPLIT.findall(run):
            low = raw.lower()
            if low in _QUERY_STOPWORDS:
                continue
            if len(low) < 2 and not _CJK_RE.search(raw):
                continue
            norm = _normalize_term(raw)
            if norm and norm not in terms:
                terms.append(norm)
    return tuple(terms)


def _term_present(term: str, text_lower: str, tokens: set[str]) -> bool:
    if _CJK_RE.search(term):
        return term in text_lower
    return term in tokens


def _longest_cjk_overlap(term: str, text_lower: str) -> str:
    """Longest contiguous CJK sub-string of ``term`` (>=2 chars) present in text.

    Returns "" when nothing overlaps.  A shared sub-string proves topical
    overlap only, never that the text is about the whole query term.
    """
    best = ""
    for start in range(len(term)):
        for end in range(start + _MIN_CJK_OVERLAP, len(term) + 1):
            candidate = term[start:end]
            if len(candidate) > len(best) and candidate in text_lower:
                best = candidate
    return best


def assess_relevance(text: str, query: str) -> tuple[str, tuple[str, ...]]:
    """Conservative query relevance for one hit's text.

    Token-level, not exact-string: "Agent Reach" matches "Agent-Reach",
    "agent reach", and plural/possessive variants.  CJK terms additionally
    match through contiguous sub-strings of two or more characters (茅台 inside
    茅台股价), so unspaced Chinese text is not read as unrelated.

    Only a *full* term match is ``relevant``.  A shared CJK sub-string is
    ``partial``: a generic overlap (智能 inside 智能手表 for query 人工智能)
    cannot certify the hit is about the query, and callers must not read it as
    certain support.  Zero matches is ``unrelated``.
    """
    terms = _query_terms(query)
    if not terms:
        return "unknown", ()
    text_lower = (text or "").lower()
    tokens = _tokenize(text)
    matched = [t for t in terms if _term_present(t, text_lower, tokens)]
    overlaps = [
        (t, _longest_cjk_overlap(t, text_lower))
        for t in terms
        if t not in matched and _CJK_RE.search(t)
    ]
    overlaps = [(t, overlap) for t, overlap in overlaps if overlap]
    if not matched and not overlaps:
        return "unrelated", (f"off-query: 0/{len(terms)} query terms in hit text",)
    if len(matched) == len(terms):
        return "relevant", (f"on-query: {len(matched)}/{len(terms)} query terms matched",)
    reason = f"partial query match: {len(matched)}/{len(terms)} query terms matched"
    if overlaps:
        sample = ", ".join(f"{term}~{overlap}" for term, overlap in overlaps[:3])
        reason += f"; CJK sub-string overlap only ({sample})"
    return "partial", (reason,)


def _looks_like_social_profile(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    if host not in _SOCIAL_PROFILE_HOSTS:
        return False
    parts = [p for p in parsed.path.split("/") if p]
    if host in {"instagram.com", "www.instagram.com"}:
        return len(parts) == 1 and parts[0].lower() not in _IG_RESERVED_ROOTS
    if host in {"tiktok.com", "www.tiktok.com"}:
        return len(parts) == 1 and parts[0].startswith("@")
    if len(parts) != 1:
        return False
    return parts[0].lower() not in _X_RESERVED_ROOTS


def is_empty_social_profile(url: str, text: str) -> bool:
    """True for a profile URL whose retrieved text says it has no posts/videos.

    Follower/following counts are never considered: they describe audience, not
    content, and a 0-follower account with real posts is perfectly usable.
    """
    if not _looks_like_social_profile(url):
        return False
    low = (text or "").lower()
    return any(pattern.search(low) for pattern in _EMPTY_PROFILE_MARKERS)


def _evidence_text(hit: "ScoredHit") -> str:
    return " ".join(part for part in (hit.title, hit.summary, hit.snippet) if part)


def assess_evidence(hit: "ScoredHit", *, query: str | None = None) -> EvidenceAssessment:
    """Judge whether a hit's retrieved text is usable evidence for the query."""
    effective_query = hit.query if query is None else query
    text = _evidence_text(hit)
    transport_ok = hit.extraction_status == "ok"
    relevance, rel_reasons = assess_relevance(text, effective_query)

    if hit.extraction_status in ("blocked", "error"):
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=("extraction transport failed — discovery lead only",) + rel_reasons,
            transport_ok=False,
        )
    if hit.extraction_status == "not_attempted":
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=("extraction not attempted — discovery lead only",) + rel_reasons,
            transport_ok=False,
        )
    # Transport succeeded from here on — usability is a separate question.
    if is_empty_social_profile(hit.url, text):
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=(
                "empty social profile (0 posts/0 videos) — transport succeeded but no content to cite",
            ) + rel_reasons,
            transport_ok=True,
        )
    if (
        _looks_like_extraction_error(hit.summary)
        or _is_html_shell(hit.summary)
        or classify_page_shell(hit.summary) is not None
    ):
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=("extraction produced no readable source text",) + rel_reasons,
            transport_ok=True,
        )
    if not text.strip():
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=("no readable text in title/summary/snippet",),
            transport_ok=True,
        )
    if relevance == "unrelated":
        return EvidenceAssessment(
            usable=False,
            relevance=relevance,
            reasons=rel_reasons,
            transport_ok=True,
        )
    return EvidenceAssessment(usable=True, relevance=relevance, reasons=rel_reasons, transport_ok=True)


def _derive_transcript_status(video_evidence: object | None) -> str:
    """Top-level transcript status: honest about which lane produced text."""
    if video_evidence is None:
        return "not_applicable"
    caption = getattr(video_evidence, "caption_transcript_status", "not_applicable")
    audio = getattr(video_evidence, "audio_transcript_status", "not_configured")
    if caption == "ok" or audio == "ok":
        return "ok"
    for status in (caption, audio):
        if status in ("blocked", "not_available"):
            return status
    return caption if caption != "not_applicable" else audio


class SourceQuality(str, Enum):
    CANONICAL = "canonical"       # Official docs, repos, maintainer statements
    PRACTITIONER = "practitioner" # Reddit threads, forums, firsthand reports
    CURRENT = "current"           # Recent maintainer posts, X/Twitter, active issues
    TECHNICAL = "technical"       # GitHub issues/PRs, changelogs, release notes
    COMMUNITY = "community"       # YouTube, TikTok demos, visual evidence
    GENERIC = "generic"           # Blog, article, general web page
    SEO = "seo"                   # SEO farm, listicle, content mill
    PLATFORM_SHELL = "platform_shell"  # TikTok/Instagram link with no readable content
    DEAD = "dead"                 # Unreachable, blocked, empty
    UNKNOWN = "unknown"


# Domain/pattern scoring rules: (regex, quality, base_score, label)
DOMAIN_RULES: list[tuple[str, SourceQuality, int, str]] = [
    # Query-specific high-signal official/project sources.
    (r"stealthchanger\.com", SourceQuality.CANONICAL, 82, "StealthChanger official site"),
    (r"sdylewski\.github\.io/stealthchanger", SourceQuality.CANONICAL, 80, "StealthChanger docs"),
    (r"ldomotion\.com/products/stealth-changer", SourceQuality.CANONICAL, 78, "LDO Stealth Changer product page"),

    # Canonical — official docs, repos
    (r"github\.com/[^/]+/[^/]+/(issues|pull)/\d+", SourceQuality.TECHNICAL, 85, "GitHub issue/PR"),
    (r"github\.com/[^/]+/[^/]+/releases/tag/", SourceQuality.TECHNICAL, 80, "GitHub release"),
    (r"github\.com/[^/]+/[^/]+/commit/", SourceQuality.TECHNICAL, 75, "GitHub commit"),
    (r"github\.com/[^/]+/[^/]+$", SourceQuality.CANONICAL, 70, "GitHub repo root"),
    (r"github\.com/[^/]+/[^/]+/", SourceQuality.CANONICAL, 68, "GitHub repo page"),
    # Specific official domains must be matched before the broad /docs/ path
    # rule below, so the canonical project domain outranks generic mirrors.
    (r"hermes-agent\.nousresearch\.com", SourceQuality.CANONICAL, 78, "Hermes Agent docs"),
    (r"nousresearch\.com", SourceQuality.CANONICAL, 75, "Nous Research"),
    (r"docs\.", SourceQuality.CANONICAL, 75, "Documentation site"),
    (r"readthedocs\.io", SourceQuality.CANONICAL, 75, "ReadTheDocs"),
    (r"help\.[^/]+/", SourceQuality.CANONICAL, 72, "Official help docs"),
    (r"arxiv\.org", SourceQuality.CANONICAL, 80, "arXiv paper"),
    (r"doi\.org", SourceQuality.CANONICAL, 80, "DOI reference"),
    (r"\.pdf($|[?#])", SourceQuality.CANONICAL, 70, "PDF/whitepaper"),
    (r"/docs/", SourceQuality.CANONICAL, 72, "Documentation path"),
    (r"documentation", SourceQuality.CANONICAL, 70, "Documentation"),

    # Practitioner — firsthand experience
    (r"reddit\.com/r/", SourceQuality.PRACTITIONER, 65, "Reddit community"),
    (r"stackoverflow\.com/questions/", SourceQuality.PRACTITIONER, 68, "StackOverflow question"),
    (r"stackexchange\.com/questions/", SourceQuality.PRACTITIONER, 65, "StackExchange question"),
    (r"discourse\.", SourceQuality.PRACTITIONER, 60, "Discourse forum"),
    (r"forum\.", SourceQuality.PRACTITIONER, 58, "Forum"),
    (r"openrouter\.ai/blog", SourceQuality.PRACTITIONER, 55, "OpenRouter blog"),

    # Current — X/Twitter, maintainer activity
    (r"x\.com/[^/]+/status/", SourceQuality.CURRENT, 55, "X/Twitter post"),
    (r"twitter\.com/[^/]+/status/", SourceQuality.CURRENT, 55, "Twitter post"),
    (r"x\.com/i/communities/", SourceQuality.CURRENT, 50, "X community"),
    (r"x\.com/[^/]+$", SourceQuality.CURRENT, 40, "X profile (discovery only; posts outrank profiles)"),
    (r"twitter\.com/[^/]+$", SourceQuality.CURRENT, 40, "Twitter profile (discovery only; posts outrank profiles)"),

    # Community — video demos, visual evidence
    (r"youtube\.com/watch", SourceQuality.COMMUNITY, 45, "YouTube video"),
    (r"youtu\.be/", SourceQuality.COMMUNITY, 45, "YouTube short link"),
    (r"tiktok\.com/@", SourceQuality.COMMUNITY, 30, "TikTok video (discovery only)"),
    (r"instagram\.com/(p|reel)/", SourceQuality.COMMUNITY, 25, "Instagram post (discovery only)"),

    # SEO / content-mill signals
    (r"medium\.com/", SourceQuality.SEO, 20, "Medium (often SEO)"),
    (r"towardsdatascience\.com", SourceQuality.SEO, 15, "TDS (SEO risk)"),
    (r"dev\.to/", SourceQuality.SEO, 25, "dev.to (mixed quality)"),
    (r"\.blogspot\.", SourceQuality.SEO, 10, "Blogspot"),
    (r"hubspot\.com", SourceQuality.SEO, 10, "HubSpot content"),
]

# Official/canonical GitHub owners whose repos must strictly outrank forks of
# the same project. A fork mirrors the full path shape (releases/, /docs), so a
# plain path-based tie lets a fork sort above the upstream release/docs. We
# boost recognized upstream-owner repo pages so the official source always wins.
CANONICAL_GITHUB_OWNERS: frozenset[str] = frozenset({"nousresearch"})
OFFICIAL_OWNER_BONUS = 6

# URL keywords that signal high quality regardless of domain
HIGH_SIGNAL_KEYWORDS = [
    "changelog", "release", "migration", "breaking", "deprecated",
    "security", "advisory", "cve", "vulnerability", "fix", "patch",
    "benchmark", "comparison", "vs", "alternative",
]

# URL keywords that signal low quality
LOW_SIGNAL_KEYWORDS = [
    "top-10", "best-of", "ultimate-guide", "definitive-guide",
    "you-wont-believe", "shocking", "viral",
]


@dataclass(frozen=True)
class SourceScore:
    quality: SourceQuality
    score: int  # 0-100
    reasons: tuple[str, ...]
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "quality": self.quality.value,
            "score": self.score,
            "reasons": list(self.reasons),
            "label": self.label,
        }


@dataclass(frozen=True)
class ScoredHit:
    title: str
    url: str
    snippet: str = ""
    extraction_status: str = ""
    extraction_length: int = 0
    scoring: SourceScore = field(default_factory=lambda: SourceScore(
        quality=SourceQuality.UNKNOWN, score=0, reasons=tuple(), label=""
    ))
    summary: str = ""
    video_evidence: object | None = None  # VideoEvidence from extraction
    query: str = ""  # query this hit was retrieved for (relevance context)
    assessment: EvidenceAssessment = field(
        default_factory=lambda: EvidenceAssessment(
            usable=False, relevance="unknown", reasons=("not assessed",), transport_ok=False
        )
    )

    def to_dict(self) -> dict:
        assessment = self.assessment
        d = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "summary": self.summary or self.snippet,
            "extraction_status": self.extraction_status,
            "extraction_length": self.extraction_length,
            "scoring": self.scoring.to_dict(),
            "query": self.query,
            # Transport success and evidence usability are reported separately.
            "evidence_usable": assessment.usable,
            "evidence_relevance": assessment.relevance,
            "evidence_reasons": list(assessment.reasons),
            "transport_ok": assessment.transport_ok,
        }
        if self.video_evidence is not None and hasattr(self.video_evidence, "to_dict"):
            d["video_evidence"] = self.video_evidence.to_dict()
        # Surface transcript/description/caption status at top level for easy consumption.
        d["transcript_status"] = _derive_transcript_status(self.video_evidence)
        d["visual_analysis_status"] = (
            getattr(self.video_evidence, "visual_analysis_status", "not_applicable")
            if self.video_evidence is not None else "not_applicable"
        )
        # summary_available tracks the summary string actually emitted above;
        # description_available tracks any retrieved descriptive text, which also
        # includes a video caption/description.  Previously both keys were computed
        # from the same expression, so a caption-only hit reported "no description".
        emitted_summary = (self.summary or self.snippet or "").strip()
        caption = ""
        if self.video_evidence is not None:
            caption = str(getattr(self.video_evidence, "caption_text", "") or "").strip()
        d["description_available"] = bool(emitted_summary or caption)
        d["summary_available"] = bool(emitted_summary)
        return d

    @classmethod
    def from_extracted_hit(cls, eh: ExtractedHit) -> ScoredHit:
        summary = _best_summary(eh.extraction.content, eh.snippet, eh.title)
        hit = cls(
            title=eh.title,
            url=eh.url,
            snippet=eh.snippet,
            summary=summary,
            extraction_status=eh.extraction.status,
            extraction_length=eh.extraction.content_length,
            video_evidence=eh.extraction.video_evidence,
            query=getattr(eh, "query", ""),
        )
        return replace(hit, assessment=assess_evidence(hit))


def _parse_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _scored(
    hit: ScoredHit,
    assessment: EvidenceAssessment,
    *,
    quality: SourceQuality,
    score: int,
    reasons: tuple[str, ...],
    label: str = "",
) -> ScoredHit:
    return ScoredHit(
        title=hit.title,
        url=hit.url,
        snippet=hit.snippet,
        summary=hit.summary,
        extraction_status=hit.extraction_status,
        extraction_length=hit.extraction_length,
        video_evidence=hit.video_evidence,
        query=hit.query,
        scoring=SourceScore(
            quality=quality,
            score=max(0, min(100, score)),
            reasons=tuple(reasons),
            label=label,
        ),
        assessment=assessment,
    )


def score_hit(hit: ScoredHit, *, query: str | None = None) -> ScoredHit:
    """Score a single hit based on URL patterns and extraction state.

    ``query`` may be supplied explicitly; otherwise the query carried on the hit
    (propagated from ``SearchHit``) is used.  Relevance is only judged when a
    query is known, so callers that score offline fixtures keep prior scores.
    """
    if query is not None and query != hit.query:
        hit = replace(hit, query=query)
    assessment = assess_evidence(hit)
    reasons: list[str] = []
    url_lower = hit.url.lower()
    parsed = urlparse(url_lower)
    github_reserved_roots = {
        "features",
        "topics",
        "marketplace",
        "pricing",
        "login",
        "search",
        "mcp",
        "settings",
        "collections",
        "orgs",
        "about",
        "apps",
        "sponsors",
        "explore",
        "pulls",
        "issues",
        "discussions",
        "security",
        "enterprise",
        "solutions",
        "product",
        "customer-stories",
    }

    # Check extraction state first
    if hit.extraction_status == "blocked" and hit.video_evidence is not None:
        # Video sources with discovery evidence — not pure platform shells
        reasons = ("Video content discovered; deep extraction requires browser/session or transcript lane",)
        return _scored(
            hit,
            assessment,
            quality=SourceQuality.COMMUNITY,
            score=25,
            reasons=tuple(reasons),
            label="Video discovery (transcript/browser extraction available)",
        )

    if hit.extraction_status == "blocked":
        return _scored(
            hit,
            assessment,
            quality=SourceQuality.PLATFORM_SHELL,
            score=0,
            reasons=("Content blocked — requires browser or account session",),
            label="Platform shell (discovery only)",
        )

    if hit.extraction_status == "error" and hit.extraction_length < 50:
        return _scored(
            hit,
            assessment,
            quality=SourceQuality.DEAD,
            score=0,
            reasons=("Content unreachable or empty",),
            label="Dead link",
        )

    # A profile whose page says it has no posts is transport-ok but not evidence:
    # a matching handle is a name collision, not content about the query.
    if hit.extraction_status == "ok" and is_empty_social_profile(hit.url, _evidence_text(hit)):
        return _scored(
            hit,
            assessment,
            quality=SourceQuality.PLATFORM_SHELL,
            score=0,
            reasons=("Empty social profile (0 posts/0 videos) — handle exists, content does not",),
            label="Empty profile (discovery only)",
        )

    # A nominally successful extraction whose text is actually the extractor's own
    # failure narration or a client-rendered HTML shell is not evidence: never let
    # it inherit the URL's domain quality.
    if hit.extraction_status == "ok" and (
        _looks_like_extraction_error(hit.summary)
        or _is_html_shell(hit.summary)
        or classify_page_shell(hit.summary) is not None
    ):
        return _scored(
            hit,
            assessment,
            quality=SourceQuality.PLATFORM_SHELL,
            score=0,
            reasons=("Extraction produced no readable source text",),
            label="Platform shell (discovery only)",
        )

    # GitHub needs explicit path-aware handling so marketing and nav pages
    # never outrank actual repos/issues/PRs.
    github_repo_page = False
    if parsed.netloc == "github.com":
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] in github_reserved_roots:
            quality = SourceQuality.GENERIC
            score = 35
            reasons.append("GitHub non-repository page")
        elif len(parts) == 2:
            quality = SourceQuality.CANONICAL
            score = 70
            github_repo_page = True
            reasons.append("GitHub repo root")
        elif len(parts) >= 4 and parts[2] in {"issues", "pull"} and parts[3].isdigit():
            quality = SourceQuality.TECHNICAL
            score = 85
            github_repo_page = True
            reasons.append("GitHub issue/PR")
        elif len(parts) >= 3 and parts[2] == "releases":
            # Release index, tagged release, or asset download — all official
            # release notes/artifacts. Must outrank third-party doc mirrors.
            quality = SourceQuality.TECHNICAL
            score = 80
            github_repo_page = True
            reasons.append("GitHub release")
        elif len(parts) >= 3 and parts[2] == "commit":
            quality = SourceQuality.TECHNICAL
            score = 75
            github_repo_page = True
            reasons.append("GitHub commit")
        elif len(parts) >= 3 and parts[2] == "docs":
            # Official docs directory inside the repository (index + subpages).
            quality = SourceQuality.CANONICAL
            score = 76
            github_repo_page = True
            reasons.append("GitHub official docs")
        elif len(parts) >= 4 and parts[2] in {"tree", "blob"} and "docs" in parts:
            # Docs files served from the repo source tree — authoritative source.
            quality = SourceQuality.CANONICAL
            score = 76
            github_repo_page = True
            reasons.append("GitHub official docs")
        elif len(parts) >= 3 and parts[2] in {"tree", "blob", "wiki", "discussions"}:
            quality = SourceQuality.CANONICAL
            score = 68
            github_repo_page = True
            reasons.append("GitHub repo page")
        else:
            quality = SourceQuality.GENERIC
            score = 35
            reasons.append("Generic GitHub page")

        # Owner-aware boost: official/canonical owner repos strictly outrank
        # forks of the same project. A fork URL (github.com/<other-user>/repo/)
        # shares the same path shape and, without owner awareness, ties the
        # official page on score and can sort above it (stable rank keeps input
        # order). Recognized upstream owners always beat their forks.
        if github_repo_page and parts and parts[0].lower() in CANONICAL_GITHUB_OWNERS:
            score += OFFICIAL_OWNER_BONUS
            reasons.append("Official GitHub owner (not a fork)")
    else:
        for pattern, quality, base_score, label in DOMAIN_RULES:
            if re.search(pattern, url_lower):
                reasons.append(label)
                score = base_score
                break
        else:
            quality = SourceQuality.GENERIC
            score = 35
            reasons.append("Generic web page")

    # Boost for high-signal keywords in URL
    keyword_boost = 0
    allow_keyword_boost = not (parsed.netloc == "github.com" and reasons and reasons[0] == "GitHub non-repository page")
    for kw in HIGH_SIGNAL_KEYWORDS:
        if allow_keyword_boost and kw in url_lower:
            keyword_boost += 3
            reasons.append(f"High-signal keyword: {kw}")

    # Penalize low-signal keywords
    for kw in LOW_SIGNAL_KEYWORDS:
        if kw in url_lower:
            score -= 10
            reasons.append(f"Low-signal keyword: {kw}")

    # Extraction bonus: successfully extracted pages get a modest boost
    if hit.extraction_status == "ok" and hit.extraction_length > 500:
        score += 5
        reasons.append("Successfully extracted (long content)")

    score = max(0, min(100, score + keyword_boost))
    # Off-query text is not evidence for this query no matter how canonical the
    # URL: keep the source-quality signal but cap the score so unrelated hits
    # cannot outrank usable evidence.
    if assessment.relevance == "unrelated":
        score = min(score, 10)
        reasons.append("Off-query: no query terms in title/summary")
    quality_label = reasons[0] if reasons else "Unknown"

    return _scored(
        hit,
        assessment,
        quality=quality,
        score=score,
        reasons=tuple(reasons),
        label=quality_label,
    )


def score_hits(hits: list[ScoredHit], *, query: str | None = None) -> list[ScoredHit]:
    """Score a list of hits.  Pass ``query`` to judge relevance for that query."""
    return [score_hit(hit, query=query) for hit in hits]


def rank_hits(scored: list[ScoredHit]) -> list[ScoredHit]:
    """Sort by evidence usability, then score, descending.

    Usable evidence always outranks a discovery-only lead with a flattering URL,
    so a transport-success-but-useless hit cannot top the list on domain alone.
    """
    return sorted(scored, key=lambda h: (h.assessment.usable, h.scoring.score), reverse=True)
