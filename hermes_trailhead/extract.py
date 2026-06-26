"""Hermes Trailhead evidence extraction — follow-through for search hits.

After ``search --execute`` returns hits, this module extracts actual page content
from URLs and reports what was readable, how much content was retrieved, and
what failed.  The product goal is to turn "5 links found" into "3 pages extracted,
2 blocked — here's what they actually say."
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import subprocess
import time
import urllib.request
from urllib.parse import parse_qs, urlparse
from typing import Callable, Literal

from .search import SearchHit

ExtractionStatus = Literal["ok", "blocked", "error", "not_attempted"]
TranscriptAttemptStatus = Literal["ok", "blocked", "not_available", "not_attempted"]
SourceType = Literal[
    "web", "x", "reddit", "tiktok", "instagram", "youtube", "github",
    "docs", "forum", "pdf", "unknown",
]

FetchFn = Callable[[str, int], str]


@dataclass(frozen=True)
class VideoEvidence:
    """First-class video-only evidence for sources where page text is not the primary content."""
    caption_transcript_status: TranscriptAttemptStatus = "not_attempted"
    caption_transcript: str = ""
    caption_transcript_length: int = 0
    caption_transcript_error: str = ""
    visual_analysis_status: str = "not_attempted"
    visual_analysis_summary: str = ""
    audio_transcript_status: str = "not_configured"
    audio_transcript: str = ""
    metadata_url: str = ""
    metadata_title: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if len(d.get("caption_transcript", "")) > 2000:
            d["caption_transcript"] = d["caption_transcript"][:2000] + "..."
        if len(d.get("audio_transcript", "")) > 2000:
            d["audio_transcript"] = d["audio_transcript"][:2000] + "..."
        if len(d.get("visual_analysis_summary", "")) > 2000:
            d["visual_analysis_summary"] = d["visual_analysis_summary"][:2000] + "..."
        return d


@dataclass(frozen=True)
class ExtractionResult:
    status: ExtractionStatus
    content: str = ""
    content_length: int = 0
    source_type: SourceType = "unknown"
    error_message: str = ""
    transcript_attempted: bool = False
    transcript_error: str = ""
    video_evidence: VideoEvidence | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Truncate content to a reasonable preview length for JSON output
        if len(d.get("content", "")) > 2000:
            d["content"] = d["content"][:2000] + "..."
        if self.video_evidence is not None:
            d["video_evidence"] = self.video_evidence.to_dict()
        return d

    @property
    def usable(self) -> bool:
        return self.status == "ok" and self.content_length > 50


@dataclass(frozen=True)
class ExtractedHit:
    title: str
    url: str
    snippet: str = ""
    extraction: ExtractionResult = ExtractionResult(status="not_attempted")

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "extraction": self.extraction.to_dict(),
        }

    @classmethod
    def from_search_hit(cls, hit: SearchHit) -> ExtractedHit:
        return cls(title=hit.title, url=hit.url, snippet=hit.snippet)


def _classify_source_type(url: str) -> SourceType:
    """Heuristic URL classification to set source type for extraction context."""
    url_lower = url.lower()
    if "github.com" in url_lower:
        return "github"
    if "x.com" in url_lower or "twitter.com" in url_lower:
        return "x"
    if "reddit.com" in url_lower:
        return "reddit"
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "instagram.com" in url_lower:
        return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if url_lower.endswith(".pdf"):
        return "pdf"
    if any(d in url_lower for d in ["docs.", "documentation", "readthedocs", "wiki"]):
        return "docs"
    if any(f in url_lower for f in ["forum.", "community.", "discourse", "stackoverflow", "stackexchange"]):
        return "forum"
    return "web"


def _fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Hermes Trailhead/0.2 (extraction)",
            "Accept": "text/plain,text/markdown,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        # Try UTF-8, fall back to replacement
        return raw.decode("utf-8", errors="replace")


def _fetch_jina(url: str, timeout: int = 20) -> str:
    """Fetch via Jina Reader for markdown conversion."""
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(
        jina_url,
        headers={
            "User-Agent": "Mozilla/5.0 Hermes Trailhead/0.2 (jina)",
            "Accept": "text/markdown,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _youtube_video_id(url: str) -> str:
    """Extract a YouTube video id from watch, youtu.be, shorts, or embed URLs."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.split("/") if p]
    if "youtu.be" in host and path_parts:
        return path_parts[0]
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            return path_parts[1]
    return ""


def _fetch_youtube_transcript(url: str, timeout: int = 20) -> str:
    """Fetch YouTube captions/transcript using the mature youtube-transcript-api package."""
    video_id = _youtube_video_id(url)
    if not video_id:
        raise RuntimeError("Could not parse YouTube video id")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("youtube-transcript-api is not installed") from exc

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=("en", "en-US", "en-GB"))
    snippets = getattr(fetched, "snippets", fetched)
    lines: list[str] = []
    for item in snippets:
        if isinstance(item, dict):
            text = item.get("text", "")
            start = item.get("start")
        else:
            text = getattr(item, "text", "")
            start = getattr(item, "start", None)
        text = " ".join(str(text).split())
        if not text:
            continue
        if start is None:
            lines.append(text)
        else:
            lines.append(f"[{float(start):.1f}s] {text}")
    content = "\n".join(lines).strip()
    if not content:
        raise RuntimeError("YouTube transcript was empty")
    return f"YouTube transcript for {video_id}\n\n{content}"


def _reddit_frontend_url(url: str) -> str:
    """Convert Reddit URLs to the configured Redlib privacy frontend."""
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc.lower():
        return url
    return f"https://redlib.perennialte.ch{parsed.path}"


def _strip_hermes_web_extract_output(output: str) -> str:
    """Normalize Hermes CLI output down to extracted markdown content."""
    lines = output.splitlines()

    if lines and lines[0].startswith("session_id:"):
        lines = lines[1:]

    if lines and re.match(r"^Readable markdown content from .+:$", lines[0].strip()):
        lines = lines[1:]

    while lines and not lines[0].strip():
        lines = lines[1:]

    return "\n".join(lines).strip()


def _fetch_hermes_web_extract(url: str, timeout: int = 30) -> str:
    """Fetch readable markdown using Hermes' native web_extract tool path."""
    prompt = (
        "Use the native web_extract tool on the URL below and return only the "
        "extracted markdown content, with no explanation, no preamble, and no "
        "code fencing.\n\n"
        f"URL: {json.dumps(url)}"
    )
    cmd = [
        "hermes",
        "chat",
        "-q",
        prompt,
        "-t",
        "web",
        "-Q",
        "--ignore-rules",
        "--ignore-user-config",
        "--safe-mode",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(timeout, 30))
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"hermes chat failed with exit code {proc.returncode}")

    content = _strip_hermes_web_extract_output(proc.stdout)
    if not content:
        raise RuntimeError("hermes web_extract returned empty content")
    return content


def _exception_summary(exc: Exception) -> str:
    """Return a compact human-readable summary of an exception."""
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return f"{type(exc).__name__}: {msg}"

# ── Browser Harness backend ──────────────────────────────────────────

def _fetch_browser_harness(url: str, timeout: int = 30) -> str:
    """Fetch page content through the local browser-harness daemon (Chrome CDP).

    Uses the running Chrome instance on CDP port 9222.  Navigates to the URL,
    waits for page settle, then extracts visible text.  This is the extraction
    path for platforms that block direct HTTP / headless requests (TikTok,
    Instagram) and for YouTube caption fallback when the transcript API is
    blocked by VPS IP.
    """
    script = _BROWSER_EXTRACT_SCRIPT.replace("{url}", url).replace("{timeout}", str(timeout))
    proc = subprocess.run(
        ["browser-harness"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"browser-harness failed with exit {proc.returncode}")
    out = proc.stdout.strip()
    if not out or len(out) < 20:
        raise RuntimeError("browser-harness returned empty page content")
    return out


_BROWSER_EXTRACT_SCRIPT = """
import time as _t

ensure_real_tab()
result = goto_url("{url}")
if not result or not result.get('loaderId'):
    print("NAVIGATE_FAILED")
    exit(1)

# Wait for dynamic content to settle (TikTok/Instagram JS hydration, YouTube page load)
body_text = ""
for attempt in range(1, 15):
    _t.sleep(0.8)
    body_text = js("(document.body && document.body.innerText) || ''")
    if body_text and len(body_text) > 50:
        break

if not body_text or len(body_text) < 10:
    print("NO_VISIBLE_TEXT")
    exit(2)

# Truncate to reasonable extract size
if len(body_text) > 8000:
    body_text = body_text[:8000] + "..."

# Include page title for context
title_text = js("document.title || ''")
if title_text:
    print(f"TITLE: {title_text}")
print(body_text)
"""


def extract_one(url: str, *, extract: FetchFn | None = None, fetch: FetchFn | None = None, timeout: int = 15, title: str = "") -> ExtractionResult:
    """Extract content from a single URL. Tries Hermes web_extract first, then direct fetch, then Jina Reader.

    For video-only sources (TikTok, YouTube, Instagram), returns structured
    video_evidence alongside any plain-text content that was retrievable.
    """
    fetcher = fetch or _fetch_text
    source_type = _classify_source_type(url)

    # TikTok / Instagram: try browser extraction before declaring blocked.
    if source_type in ("tiktok", "instagram"):
        # TikTok oEmbed: try metadata extraction without rendering the full page.
        if source_type == "tiktok":
            try:
                oembed_url = f"https://www.tiktok.com/oembed?url={url}"
                content = fetcher(oembed_url, timeout=timeout)
                if content and len(content) > 50:
                    import json as _json
                    try:
                        data = _json.loads(content)
                        title_text = data.get("title", "")
                        author = data.get("author_name", "")
                        desc = f"TikTok by @{author}: {title_text}" if author else title_text
                        if desc and len(desc) > 30:
                            return ExtractionResult(
                                status="ok",
                                content=desc[:2000],
                                content_length=len(desc),
                                source_type=source_type,
                                video_evidence=VideoEvidence(
                                    caption_transcript_status="not_attempted",
                                    visual_analysis_status="available",
                                    metadata_url=url,
                                    metadata_title=desc[:200],
                                ),
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        # Browser extraction for public-page content (works for Instagram, limited for TikTok).
        if source_type == "instagram":
            try:
                content = _fetch_browser_harness(url, timeout=timeout)
                if content and len(content) > 50:
                    return ExtractionResult(
                        status="ok",
                        content=content[:5000],
                        content_length=len(content),
                        source_type=source_type,
                        video_evidence=VideoEvidence(
                            caption_transcript_status="not_available",
                            visual_analysis_status="available",
                            visual_analysis_summary=content[:2000],
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass  # Fall through to blocked status below

        return ExtractionResult(
            status="blocked",
            source_type=source_type,
            error_message=(
                f"{source_type} content requires browser/session for full extraction; "
                "browser-harness attempt also failed; use video_analyze for visual summary"
            ),
            video_evidence=VideoEvidence(
                caption_transcript_status="not_attempted" if source_type == "tiktok" else "not_available",
                visual_analysis_status="available",
                visual_analysis_summary="Title, snippet, and video URL preserved as discovery evidence; call video_analyze() for visual summary.",
                audio_transcript_status="not_configured",
                metadata_url=url,
                metadata_title=title,
            ),
        )

    # YouTube: try captions/transcript first, report outcome explicitly.
    if source_type == "youtube":
        transcript_attempted = True
        transcript_error = ""
        video_ev = VideoEvidence(
            metadata_url=url,
            metadata_title=title,
            visual_analysis_status="available",
            visual_analysis_summary="Title, snippet, and video URL preserved; call video_analyze() for visual summary.",
        )
        try:
            content = _fetch_youtube_transcript(url, timeout=timeout)
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                    transcript_attempted=True,
                    video_evidence=VideoEvidence(
                        caption_transcript_status="ok",
                        caption_transcript=content,
                        caption_transcript_length=len(content),
                        visual_analysis_status="available",
                        audio_transcript_status="ok",
                        metadata_url=url,
                        metadata_title=title,
                    ),
                )
        except Exception as exc:
            transcript_error = f"YouTube transcript blocked or unavailable: {_exception_summary(exc)}"
            video_ev = VideoEvidence(
                caption_transcript_status="blocked",
                caption_transcript_error=transcript_error,
                visual_analysis_status="available",
                audio_transcript_status="not_configured",
                metadata_url=url,
                metadata_title=title,
            )

        # Fallback 1: browser-harness to grab page text + auto-captions from DOM.
        if transcript_error:
            try:
                content = _fetch_browser_harness(url, timeout=timeout)
                if content and len(content) > 50:
                    return ExtractionResult(
                        status="ok",
                        content=content[:5000],
                        content_length=len(content),
                        source_type=source_type,
                        transcript_attempted=True,
                        transcript_error=transcript_error,
                        video_evidence=video_ev,
                    )
            except Exception:
                pass

        # Fallback 2: direct page fetch for metadata/title/description
        try:
            content = fetcher(url, timeout)
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content[:5000],
                    content_length=len(content),
                    source_type=source_type,
                    transcript_attempted=transcript_attempted,
                    transcript_error=transcript_error,
                    video_evidence=video_ev,
                )
        except Exception:
            pass

        # No page content either
        return ExtractionResult(
            status="blocked",
            source_type=source_type,
            error_message=f"YouTube page and transcript both unreachable: {transcript_error or 'IP blocked or video unavailable'}",
            transcript_attempted=transcript_attempted,
            transcript_error=transcript_error,
            video_evidence=video_ev,
        )

    # Reddit often blocks direct fetches; try Redlib before generic page extraction.
    if source_type == "reddit":
        try:
            content = fetcher(_reddit_frontend_url(url), timeout)
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                )
        except Exception:
            pass  # Fall through to Hermes/Jina/direct fetch

    # Try direct fetch first (fast, no subprocess).
    try:
        content = fetcher(url, timeout)
        if content and len(content) > 50:
            return ExtractionResult(
                status="ok",
                content=content,
                content_length=len(content),
                source_type=source_type,
            )
    except Exception:
        pass  # Fall through to Jina

    # Try Jina Reader for markdown.
    if fetch is None:  # Only try Jina when not testing
        try:
            content = _fetch_jina(url, timeout=timeout)
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                )
        except Exception:
            pass

    # Try Hermes native web_extract last (slow subprocess).
    try:
        content = (extract or _fetch_hermes_web_extract)(url, timeout)
        if content and len(content) > 50:
            return ExtractionResult(
                status="ok",
                content=content,
                content_length=len(content),
                source_type=source_type,
            )
    except Exception:
        pass  # Fall through to error

    return ExtractionResult(
        status="error",
        source_type=source_type,
        error_message=f"Could not extract content from {url} via Hermes web_extract, direct fetch, or Jina fetch",
    )


def extract_hits(
    hits: tuple[SearchHit, ...],
    *,
    limit: int = 5,
    extract: FetchFn | None = None,
    fetch: FetchFn | None = None,
    timeout: int = 15,
) -> tuple[ExtractedHit, ...]:
    """Extract content from search hits. Returns ExtractedHit objects with extraction results."""
    extracted: list[ExtractedHit] = []
    for hit in hits[:limit]:
        result = extract_one(hit.url, extract=extract, fetch=fetch, timeout=timeout, title=hit.title)
        eh = ExtractedHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            extraction=result,
        )
        extracted.append(eh)
    return tuple(extracted)
