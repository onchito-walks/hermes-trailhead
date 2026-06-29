"""Hermes Trailhead source-quality scoring — rank search hits by likely usefulness.

After ``search --execute`` returns hits, this module classifies each hit by source
quality and assigns a score. Higher scores go to maintainer/official/canonical
sources, practitioner firsthand reports, current discussion, and GitHub issues/PRs.
Lower scores go to SEO farms, listicles, empty platform shells, and dead links.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from urllib.parse import urlparse

from .extract import ExtractedHit


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
    # If extraction is raw HTML/app chrome, try cleaning it.  If the cleaned
    # text is substantial, prefer it over the search snippet/title which is
    # often just a one-line label.
    if looks_like_shell:
        if len(cleaned) >= 80:
            return cleaned[:1200] + ("..." if len(cleaned) > 1200 else "")
        return fallback[:1200]
    if len(cleaned) >= 80:
        return cleaned[:1200] + ("..." if len(cleaned) > 1200 else "")
    if fallback:
        return fallback[:1200]
    return cleaned


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
    (r"nousresearch\.com", SourceQuality.CANONICAL, 75, "Nous Research"),
    (r"hermes-agent\.nousresearch\.com", SourceQuality.CANONICAL, 78, "Hermes Agent docs"),

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

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "summary": self.summary or self.snippet,
            "extraction_status": self.extraction_status,
            "extraction_length": self.extraction_length,
            "scoring": self.scoring.to_dict(),
        }
        if self.video_evidence is not None and hasattr(self.video_evidence, "to_dict"):
            d["video_evidence"] = self.video_evidence.to_dict()
        # Surface transcript/description status at top level for easy consumption.
        d["transcript_status"] = getattr(self.video_evidence, "caption_transcript_status", "not_applicable") if self.video_evidence is not None else "not_applicable"
        d["description_available"] = self.extraction_length > 50
        d["summary_available"] = bool((self.summary or self.snippet or "").strip())
        return d

    @classmethod
    def from_extracted_hit(cls, eh: ExtractedHit) -> ScoredHit:
        summary = _best_summary(eh.extraction.content, eh.snippet, eh.title)
        return cls(
            title=eh.title,
            url=eh.url,
            snippet=eh.snippet,
            summary=summary,
            extraction_status=eh.extraction.status,
            extraction_length=eh.extraction.content_length,
            video_evidence=eh.extraction.video_evidence,
        )


def _parse_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def score_hit(hit: ScoredHit) -> ScoredHit:
    """Score a single hit based on URL patterns and extraction state."""
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
        return ScoredHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            summary=hit.summary,
            extraction_status=hit.extraction_status,
            extraction_length=hit.extraction_length,
            video_evidence=hit.video_evidence,
            scoring=SourceScore(
                quality=SourceQuality.COMMUNITY,
                score=25,
                reasons=reasons,
                label="Video discovery (transcript/browser extraction available)",
            ),
        )

    if hit.extraction_status == "blocked":
        return ScoredHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            summary=hit.summary,
            extraction_status=hit.extraction_status,
            extraction_length=hit.extraction_length,
            scoring=SourceScore(
                quality=SourceQuality.PLATFORM_SHELL,
                score=0,
                reasons=("Content blocked — requires browser or account session",),
                label="Platform shell (discovery only)",
            ),
        )

    if hit.extraction_status == "error" and hit.extraction_length < 50:
        return ScoredHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            summary=hit.summary,
            extraction_status=hit.extraction_status,
            extraction_length=hit.extraction_length,
            video_evidence=hit.video_evidence,
            scoring=SourceScore(
                quality=SourceQuality.DEAD,
                score=0,
                reasons=("Content unreachable or empty",),
                label="Dead link",
            ),
        )

    # GitHub needs explicit path-aware handling so marketing and nav pages
    # never outrank actual repos/issues/PRs.
    if parsed.netloc == "github.com":
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] in github_reserved_roots:
            quality = SourceQuality.GENERIC
            score = 35
            reasons.append("GitHub non-repository page")
        elif len(parts) == 2:
            quality = SourceQuality.CANONICAL
            score = 70
            reasons.append("GitHub repo root")
        elif len(parts) >= 4 and parts[2] in {"issues", "pull"} and parts[3].isdigit():
            quality = SourceQuality.TECHNICAL
            score = 85
            reasons.append("GitHub issue/PR")
        elif len(parts) >= 4 and parts[2] == "releases" and parts[3] == "tag":
            quality = SourceQuality.TECHNICAL
            score = 80
            reasons.append("GitHub release")
        elif len(parts) >= 3 and parts[2] == "commit":
            quality = SourceQuality.TECHNICAL
            score = 75
            reasons.append("GitHub commit")
        elif len(parts) >= 3 and parts[2] in {"tree", "blob", "wiki", "discussions"}:
            quality = SourceQuality.CANONICAL
            score = 68
            reasons.append("GitHub repo page")
        else:
            quality = SourceQuality.GENERIC
            score = 35
            reasons.append("Generic GitHub page")
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
    quality_label = reasons[0] if reasons else "Unknown"

    return ScoredHit(
        title=hit.title,
        url=hit.url,
        snippet=hit.snippet,
        summary=hit.summary,
        extraction_status=hit.extraction_status,
        extraction_length=hit.extraction_length,
        video_evidence=hit.video_evidence,
        scoring=SourceScore(
            quality=quality,
            score=score,
            reasons=tuple(reasons),
            label=quality_label,
        ),
    )


def score_hits(hits: list[ScoredHit]) -> list[ScoredHit]:
    """Score a list of hits."""
    return [score_hit(hit) for hit in hits]


def rank_hits(scored: list[ScoredHit]) -> list[ScoredHit]:
    """Sort scored hits by score descending."""
    return sorted(scored, key=lambda h: h.scoring.score, reverse=True)
