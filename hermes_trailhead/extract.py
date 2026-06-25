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
SourceType = Literal[
    "web", "x", "reddit", "tiktok", "instagram", "youtube", "github",
    "docs", "forum", "pdf", "unknown",
]

FetchFn = Callable[[str, int], str]


@dataclass(frozen=True)
class ExtractionResult:
    status: ExtractionStatus
    content: str = ""
    content_length: int = 0
    source_type: SourceType = "unknown"
    error_message: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Truncate content to a reasonable preview length for JSON output
        if len(d.get("content", "")) > 2000:
            d["content"] = d["content"][:2000] + "…"
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


def extract_one(url: str, *, extract: FetchFn | None = None, fetch: FetchFn | None = None, timeout: int = 15) -> ExtractionResult:
    """Extract content from a single URL. Tries Hermes web_extract first, then direct fetch, then Jina Reader."""
    fetcher = fetch or _fetch_text
    source_type = _classify_source_type(url)

    # Skip platforms we know we can only discover, not deeply read
    if source_type in ("tiktok", "instagram"):
        return ExtractionResult(
            status="blocked",
            source_type=source_type,
            error_message=f"{source_type} content requires browser/session — discovery only",
        )

    # YouTube's page HTML is not enough; try captions/transcript first.
    if source_type == "youtube":
        try:
            content = _fetch_youtube_transcript(url, timeout=timeout)
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                )
        except Exception:
            pass  # Fall through to normal extraction for metadata/page text

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

    # Try Hermes native web_extract first.
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
        pass  # Fall through to direct fetch

    # Try direct fetch second.
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
        result = extract_one(hit.url, extract=extract, fetch=fetch, timeout=timeout)
        eh = ExtractedHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            extraction=result,
        )
        extracted.append(eh)
    return tuple(extracted)
