"""Hermes Trailhead evidence extraction — follow-through for search hits.

After ``search --execute`` returns hits, this module extracts actual page content
from URLs and reports what was readable, how much content was retrieved, and
what failed.  The product goal is to turn "5 links found" into "3 pages extracted,
2 blocked — here's what they actually say."
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from urllib.parse import parse_qs, quote, urlparse
from typing import Callable, Literal

from .search import SearchHit
from .paths import hermes_secrets_dir, hermes_state_dir, resolve_hermes_home
from .backends import REDLIB_LOCAL_URL, _github_request_headers

ExtractionStatus = Literal["ok", "blocked", "error", "not_attempted"]
TranscriptAttemptStatus = Literal["ok", "blocked", "not_available", "not_attempted"]
SourceType = Literal[
    "web", "x", "reddit", "tiktok", "instagram", "youtube", "github",
    "docs", "forum", "pdf", "unknown",
]

FetchFn = Callable[[str, int], str]


@dataclass(frozen=True)
class VideoEvidence:
    """First-class video-only evidence for sources where page text is not the primary content.

    Caption and transcript are deliberately separate: a platform caption/description
    ("TikTok by @user: ...") is NOT a transcript.  ``caption_status`` reports the
    caption/description we actually retrieved; ``caption_transcript_status`` reports a
    real spoken/auto transcript.  Conflating them let a caption be reported as a
    successful transcript.
    """
    caption_status: TranscriptAttemptStatus = "not_attempted"
    caption_text: str = ""
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
        if len(d.get("caption_text", "")) > 2000:
            d["caption_text"] = d["caption_text"][:2000] + "..."
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


def _fetch_text_tiered(url: str, timeout: int = 15) -> str:
    """Tiered HTTP fetch — escalates from free/direct to proxy/residential.

    Tier 1: _fetch_text (datacenter IP, free, fast — works for 80% of pages)
    Tier 2: _fetch_proxy (residential IP, free* — handles bot-hostile sites)
    Tier 3: raises RuntimeError (page unreachable → escalation to Browser Harness)

    This is the default fetcher for all web extraction. It transparently
    upgrades to residential IP when datacenter gets blocked, with zero
    configuration changes needed at call sites.
    """
    # Tier 1: direct
    try:
        result = _fetch_text(url, timeout=timeout)
        if result and len(result) > 200:
            return result
    except Exception:
        pass

    # Tier 2: proxy
    try:
        result = _fetch_proxy(url, timeout=timeout)
        if result and len(result) > 200:
            return result
    except Exception:
        pass

    # Tier 3: dead end — upstream should escalate to Browser Harness
    raise RuntimeError(
        f"Tiered fetch failed for {url} — both direct and proxy exhausted"
    )


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


def _get_groq_key() -> str:
    """GROQ_API_KEY from the process env or $HERMES_HOME/.env (runtime only).

    Used for the free-tier Whisper ASR tier; the value is never logged or
    returned by any lane tool.
    """
    import os as _os

    key = _os.environ.get("GROQ_API_KEY", "")
    if key:
        return key
    env_path = resolve_hermes_home() / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GROQ_API_KEY="):
                    return line.split("=", 1)[1].strip("\"' \t")
        except OSError:
            pass
    return ""


def _groq_multipart(filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Minimal multipart/form-data body for the Groq audio upload (no deps).

    Returns (body, content_type).
    """
    import os as _os

    boundary = "----trailhead" + _os.urandom(8).hex()
    b = boundary.encode()
    body = b""
    for name, value in (("model", "whisper-large-v3-turbo"), ("response_format", "json")):
        body += b"--" + b + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += b"--" + b + b"\r\n"
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: audio/mp4\r\n\r\n"
    ).encode()
    body += file_bytes + b"\r\n--" + b + b"--\r\n"
    return body, f"multipart/form-data; boundary={boundary}"


def _transcribe_audio_groq(audio_path: str, api_key: str, timeout: int = 150) -> str:
    """Transcribe an audio file with Groq's Whisper endpoint (free tier).

    NOTE: api.groq.com is behind Cloudflare — the default urllib UA gets a
    403 (error code 1010).  A browser UA + Origin/Referer passes (same
    signature as the opencode.ai GO tier); keep them on every request.
    """
    with open(audio_path, "rb") as f:
        audio = f.read()
    body, content_type = _groq_multipart("audio.m4a", audio)
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Origin": "https://console.groq.com",
            "Referer": "https://console.groq.com/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return (data.get("text") or "").strip()


def _fetch_youtube_asr(url: str, timeout: int = 30) -> str:
    """ASR fallback for videos without captions (Groq Whisper, free tier).

    Downloads bestaudio (m4a) through the proxy pool and transcribes it.
    Cached with a separate ``.asr.txt`` key so repeats are instant.
    """
    import glob as _glob
    import os as _os

    video_id = _youtube_video_id(url)
    if not video_id:
        raise RuntimeError("Could not parse YouTube video id")

    cache_dir = hermes_state_dir() / "trailhead-transcripts"
    cache_file = cache_dir / f"{video_id}.asr.txt"
    try:
        if cache_file.exists():
            cached = cache_file.read_text(encoding="utf-8")
            if len(cached) > 50:
                return cached
    except Exception:
        pass

    api_key = _get_groq_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not configured — ASR tier unavailable")

    out_base = f"/tmp/yt-audio-{video_id}"
    audio_path: str | None = None
    last_error = ""
    for proxy in _proxy_failover_plan():
        cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "--no-playlist",
            "-o", out_base + ".%(ext)s",
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(url)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(timeout, 60))
        except subprocess.TimeoutExpired:
            last_error = "audio download timed out"
            continue
        if proc.returncode != 0:
            last_error = f"audio download failed: {proc.stderr.strip()[:160]}"
            continue
        hits = sorted(_glob.glob(out_base + ".*"))
        if hits:
            audio_path = hits[0]
            break
        last_error = "no audio file produced"

    if not audio_path:
        raise RuntimeError(f"ASR: {last_error or 'audio download failed on every route'}")

    try:
        size = _os.path.getsize(audio_path)
        if size > 24 * 1024 * 1024:
            raise RuntimeError(f"ASR: audio too large ({size // (1024 * 1024)}MB > 24MB cap)")
        text = _transcribe_audio_groq(audio_path, api_key)
    finally:
        try:
            _os.remove(audio_path)
        except Exception:
            pass
    if not text or len(text) < 40:
        raise RuntimeError("ASR: transcript too short or empty")

    result = f"YouTube ASR transcript for {video_id}\n\n{text}"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(result, encoding="utf-8")
    except Exception:
        pass
    return result


def _reddit_frontend_url(url: str) -> str:
    """Convert Reddit URLs to old.reddit.com for proxy-backed extraction.

    The local Redlib instance is attempted first (see `_redlib_thread_url`);
    old.reddit.com remains the fallback — it serves full HTML without auth
    when fetched through a residential proxy with proper browser headers.
    """
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc.lower():
        return url
    # Use old.reddit.com which returns clean HTML with full post + comments
    return f"https://old.reddit.com{parsed.path}"


def _redlib_thread_url(url: str) -> str:
    """Map a reddit URL onto the local Redlib instance for readable HTML.

    The self-hosted Redlib frontend serves post + comment HTML from localhost
    without auth, OAuth, or a residential proxy (verified 2026-10-14).
    """
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc.lower():
        return url
    return f"{REDLIB_LOCAL_URL}{parsed.path or '/'}"


def _fetch_redlib(url: str, timeout: int = 15) -> str:
    """Fetch through the local Redlib instance (direct localhost HTTP)."""
    return _fetch_text(url, timeout=timeout)


_REDDIT_THREAD_ID_RE = re.compile(r"/comments/([a-z0-9]{4,10})", re.IGNORECASE)


def _reddit_thread_id(url: str) -> str:
    """Extract the base36 thread id from a reddit permalink ('' if absent)."""
    m = _REDDIT_THREAD_ID_RE.search(urlparse(url).path or url)
    return m.group(1) if m else ""


def _http_json(url: str, timeout: int = 15):
    """GET a JSON endpoint and decode it (raises on failure)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Hermes-Trailhead/1.0 (evidence-first research)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# Pushshift successors — both ingest Reddit's public data and serve it to any
# IP (no Reddit-IP dependency, no auth).  Verified reachable from this host
# 2026-10-14 with real post+comment JSON; the web-research consensus names
# exactly these two as the surviving Pushshift replacements in 2026.
_PUSHSHIFT_SUBMISSION_URLS = {
    "pullpush": "https://api.pullpush.io/reddit/search/submission/?ids={tid}",
    "arctic-shift": "https://arctic-shift.photon-reddit.com/api/posts/ids?ids={tid}",
}
_PUSHSHIFT_COMMENT_URLS = {
    "pullpush": "https://api.pullpush.io/reddit/search/comment/?link_id={tid}&size=50",
    "arctic-shift": "https://arctic-shift.photon-reddit.com/api/comments/search?link_id={tid}&limit=50",
}


def _compose_pushshift_thread(tid: str, post: dict, comments: list[dict]) -> str:
    """Compose readable thread text from Pushshift-successor JSON.

    Both services return Reddit's own JSON shape ({'data': [...]}); comments
    are ranked by score locally (the APIs return ingest order).
    """
    title = (post.get("title") or "").strip()
    sub = post.get("subreddit_name_prefixed") or (
        f"r/{post.get('subreddit')}" if post.get("subreddit") else ""
    )
    author = post.get("author") or "?"
    score = post.get("score")
    parts = [f"Reddit thread {tid} — {title}"]
    header = " · ".join(
        x
        for x in (
            sub,
            f"u/{author}",
            f"score {score}" if score is not None else "",
            f"{post.get('num_comments')} comments" if post.get("num_comments") else "",
        )
        if x
    )
    if header:
        parts.append(header)
    selftext = (post.get("selftext") or "").strip()
    if selftext and selftext not in ("[removed]", "[deleted]"):
        parts.append(selftext[:4000])
    ranked = sorted(
        (c for c in comments if isinstance(c, dict)),
        key=lambda c: c.get("score") or 0,
        reverse=True,
    )
    lines: list[str] = []
    for c in ranked:
        body = (c.get("body") or "").strip().replace("\n", " ")
        if not body or body in ("[removed]", "[deleted]"):
            continue
        lines.append(f"[{c.get('score', 0)}↑] u/{c.get('author', '?')}: {body[:400]}")
        if len(lines) >= 20:
            break
    if lines:
        parts.append(f"Top comments ({len(lines)}):")
        parts.extend(lines)
    return "\n\n".join(parts)[:15000]


def _fetch_pushshift_thread(url: str, timeout: int = 20, *, service: str = "pullpush") -> str:
    """Fetch a Reddit thread (post + top comments) via a Pushshift successor.

    The always-on content backbone for the reddit lane when Redlib's upstream
    window is shut and old.reddit serves anti-bot shells.
    """
    tid = _reddit_thread_id(url)
    if not tid:
        raise ValueError(f"no reddit thread id in {url}")
    post_json = _http_json(_PUSHSHIFT_SUBMISSION_URLS[service].format(tid=tid), timeout)
    comment_json = _http_json(_PUSHSHIFT_COMMENT_URLS[service].format(tid=tid), timeout)
    posts = post_json.get("data") or []
    comments = comment_json.get("data") or []
    if not posts:
        raise RuntimeError(f"{service} has no submission data for {tid}")
    text = _compose_pushshift_thread(tid, posts[0], comments)
    if len(text) < 120:
        raise RuntimeError(f"{service} produced too little content for {tid}")
    return text


def _fetch_pullpush(url: str, timeout: int = 20) -> str:
    return _fetch_pushshift_thread(url, timeout, service="pullpush")


def _fetch_arctic_shift(url: str, timeout: int = 20) -> str:
    return _fetch_pushshift_thread(url, timeout, service="arctic-shift")


# ── Lane-native content methods (probed + verified 2026-10-14) ──────────────
# Structured text per platform without whole-page reader bloat:
# FxTwitter (tweets), local Nitter (tweet + replies), TikWM (TikTok metadata),
# Instagram's loginless embed (caption + social proof).

_FXTWITTER_RE = re.compile(r"(?:x|twitter)\.com/[^/]+/status(?:es)?/(\d+)")


def _http_text(url: str, timeout: int = 15, headers: dict | None = None) -> str:
    """GET a text body with an explicit UA (defaults to a neutral bot UA)."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_fxtwitter(url: str, timeout: int = 20) -> str:
    """Tweet content via FxTwitter's public API (free, no auth, any IP)."""
    m = _FXTWITTER_RE.search(url)
    if not m:
        raise ValueError(f"no tweet id in {url}")
    data = _http_json(f"https://api.fxtwitter.com/status/{m.group(1)}", timeout)
    tweet = data.get("tweet") or {}
    text = (tweet.get("text") or "").strip()
    if not text:
        raise RuntimeError("fxtwitter: empty tweet text")
    author = (tweet.get("author") or {}).get("screen_name") or "?"
    parts = [f"Tweet by @{author} ({tweet.get('created_at', '')}):", text]
    stats = " · ".join(
        x
        for x in (
            f"{tweet.get('likes', 0)} likes",
            f"{tweet.get('retweets', 0)} retweets",
            f"{tweet.get('replies', 0)} replies",
            f"{tweet.get('views', 0)} views" if tweet.get("views") else "",
        )
        if x
    )
    if stats:
        parts.append(stats)
    quote = tweet.get("quote") or {}
    if quote.get("text"):
        parts.append(
            f"Quoted @{(quote.get('author') or {}).get('screen_name', '?')}: {quote['text'][:400]}"
        )
    media = tweet.get("media") or {}
    n_photos = len(media.get("photos") or [])
    n_videos = len(media.get("videos") or [])
    if n_photos or n_videos:
        parts.append(f"Media: {n_photos} photo(s), {n_videos} video(s)")
    return "\n\n".join(parts)


def _fetch_nitter(url: str, timeout: int = 15) -> str:
    """Tweet + top replies from the local Nitter instance (no proxy, no auth)."""
    parsed = urlparse(url)
    if "x.com" not in parsed.netloc and "twitter.com" not in parsed.netloc:
        raise ValueError("not an x/twitter URL")
    stripped = parsed.path.strip("/")
    handle = stripped.split("/")[0] if stripped else "?"
    html = _fetch_text(f"http://127.0.0.1:8788{parsed.path}", timeout=timeout)
    if not html or "tweet-content" not in html:
        raise RuntimeError("nitter: no tweet content in page")
    blocks = re.findall(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', html, re.S)
    texts = []
    for b in blocks:
        t = " ".join(re.sub(r"<[^>]+>", " ", b).split())
        if t and len(t) > 8:
            texts.append(t)
    if not texts:
        raise RuntimeError("nitter: empty tweet content")
    out = f"X post by @{handle} (via local Nitter):\n{texts[0][:2000]}"
    if len(texts) > 1:
        out += "\n\nReplies:\n" + "\n".join(f"- {t[:300]}" for t in texts[1:6])
    return out


def _fetch_tikwm(url: str, timeout: int = 25) -> str:
    """TikTok video metadata via the public TikWM API (free, no auth, any IP)."""
    data = _http_json(f"https://www.tikwm.com/api/?url={quote(url, safe='')}", timeout)
    if data.get("code") != 0:
        raise RuntimeError(f"tikwm error: {data.get('msg')}")
    d = data.get("data") or {}
    desc = (d.get("title") or "").strip() or (d.get("content_desc") or "").strip()
    author = (d.get("author") or {}).get("unique_id") or "?"
    parts = [f"TikTok by @{author}: {desc[:1200]}"]
    stats = " · ".join(
        f"{label}: {d.get(key)}"
        for key, label in (
            ("play_count", "plays"),
            ("digg_count", "likes"),
            ("comment_count", "comments"),
            ("share_count", "shares"),
            ("collect_count", "saves"),
        )
        if d.get(key) is not None
    )
    if stats:
        parts.append(stats)
    music = (d.get("music_info") or {}).get("title")
    if music:
        parts.append(f"Music: {music}")
    if d.get("duration"):
        parts.append(f"Duration: {d['duration']}s")
    # Top comments — rich conversation context via TikWM's comment endpoint
    # (verified 2026-10-14). Best-effort: never fatal to the metadata result.
    try:
        c = _http_json(
            f"https://www.tikwm.com/api/comment/list?url={quote(url, safe='')}&count=20", timeout
        )
        comments = (c.get("data") or {}).get("comments") or []
        ranked = sorted(
            (cm for cm in comments if isinstance(cm, dict)),
            key=lambda cm: cm.get("digg_count") or 0,
            reverse=True,
        )
        lines: list[str] = []
        for cm in ranked:
            body = (cm.get("text") or "").strip().replace("\n", " ")
            if not body:
                continue
            lines.append(f"[{cm.get('digg_count', 0)}↑] {body[:300]}")
            if len(lines) >= 10:
                break
        if lines:
            parts.append(f"Top comments ({len(lines)}):")
            parts.extend(lines)
    except Exception:
        pass
    return "\n\n".join(parts)


def _tiktok_video_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else ""


def _download_small_media(url: str, out_base: str, timeout: int = 45, max_bytes: int = 24 * 1024 * 1024) -> str:
    """Download a small media file with a byte cap; single pass, proxy pool fallback."""
    import urllib.request as _urllib_request

    last_error = ""
    for proxy in _proxy_failover_plan():
        path = out_base + ".mp4"
        try:
            req = _urllib_request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "*/*",
                },
            )
            proxies = {"http": proxy, "https": proxy} if proxy else {}
            with _urllib_request.build_opener(_urllib_request.ProxyHandler(proxies)).open(req, timeout=timeout) as resp:
                declared = resp.headers.get("Content-Length")
                if declared and int(declared) > max_bytes:
                    raise RuntimeError(f"media too large ({int(declared) // (1024 * 1024)}MB)")
                total = 0
                with open(path, "wb") as fh:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise RuntimeError(f"media too large (> {max_bytes // (1024 * 1024)}MB)")
                        fh.write(chunk)
            return path
        except Exception as exc:
            last_error = str(exc)[:140]
            try:
                os.remove(path)
            except Exception:
                pass
    raise RuntimeError(f"media download failed: {last_error or 'no route'}")


def _fetch_tiktok_transcript(url: str, timeout: int = 60) -> str:
    """ASR transcript for a TikTok video (Groq Whisper, free tier).

    Downloads the no-watermark MP4 via TikWM's ``play`` URL (proxy-pool
    fallback; whisper accepts mp4 directly) and caches per video id.
    Verified 2026-10-14; honest failure on music-only / photo posts.
    """
    vid = _tiktok_video_id(url)
    if not vid:
        raise RuntimeError("Could not parse TikTok video id")
    cache_dir = hermes_state_dir() / "trailhead-transcripts"
    cache_file = cache_dir / f"tt-{vid}.asr.txt"
    try:
        if cache_file.exists():
            cached = cache_file.read_text(encoding="utf-8")
            if len(cached) > 50:
                return cached
    except Exception:
        pass
    api_key = _get_groq_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not configured — ASR tier unavailable")
    data = _http_json(f"https://www.tikwm.com/api/?url={quote(url, safe='')}", timeout)
    d = data.get("data") or {}
    candidates = [
        c for c in (d.get("play"), d.get("wmplay"), d.get("hdplay"))
        if isinstance(c, str) and c.startswith("http")
    ]
    if not candidates:
        raise RuntimeError("TikTok ASR: no downloadable video URL (photos post?)")
    out_base = f"/tmp/tt-media-{vid}"
    media_path = None
    last_error = ""
    for cand in candidates:
        try:
            media_path = _download_small_media(cand, out_base, timeout=max(timeout, 45))
            break
        except Exception as exc:
            last_error = str(exc)[:140]
    if not media_path:
        raise RuntimeError(f"TikTok ASR: {last_error or 'download failed'}")
    try:
        text = _transcribe_audio_groq(media_path, api_key)
    finally:
        try:
            os.remove(media_path)
        except Exception:
            pass
    if not text or len(text) < 40:
        raise RuntimeError("TikTok ASR: transcript too short or empty (music only?)")
    result = f"TikTok ASR transcript for {vid}\n\n{text}"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(result, encoding="utf-8")
    except Exception:
        pass
    return result


def _fetch_instagram_embed(url: str, timeout: int = 20) -> str:
    """Public Instagram content via the loginless /embed/captioned/ page.

    The embed is meant for third-party embedding: it serves the full caption
    + author (+ social proof) without login from any IP.  The static variant
    appears for non-browser user agents (verified 2026-10-14); a browser UA
    gets a JS shell instead, hence the explicit UA.
    """
    short = _instagram_shortcode(url)
    if not short:
        raise ValueError(f"no instagram shortcode in {url}")
    kind = "reel" if "/reel" in url else "p"
    embed_url = f"https://www.instagram.com/{kind}/{short}/embed/captioned/?_fb_noscript=1"
    html = _http_text(embed_url, timeout=timeout)
    i = html.find('class="Caption"')
    if i < 0:
        raise RuntimeError("instagram embed: no caption block (blocked or removed?)")
    user_m = re.search(r"CaptionUsername[^>]*>([^<]{1,60})</a>", html[i : i + 2000])
    user = user_m.group(1).strip() if user_m else "?"
    j = html.find('class="SocialProof"', i)
    seg = html[i : j if j > 0 else i + 4000]
    seg = re.sub(r"<br\s*/?>", " ", seg)
    caption = " ".join(re.sub(r"<[^>]+>", " ", seg).split())
    if caption.startswith("class="):
        caption = caption.split(">", 1)[1].lstrip() if ">" in caption else caption
    import html as _html

    caption = _html.unescape(caption)
    if user != "?":
        caption = re.sub(rf"^\s*{re.escape(user)}\s*", "", caption)
    out = [f"Instagram {'reel' if kind == 'reel' else 'post'} by @{user}:", caption]
    if j > 0:
        proof = " ".join(re.sub(r"<[^>]+>", " ", html[j : j + 1200]).split())
        if proof:
            out.append(proof[:500])
    text = "\n\n".join(out)
    if len(text) < 60:
        raise RuntimeError("instagram embed: caption too short")
    return text


# ── Camofox authenticated session tier (Instagram profiles, Facebook) ──
# Fetches through the local Camofox browser server's persistent profile,
# whose logged-in session cookies carry onto every tab it opens. Verified
# live 2026-10-14: Instagram profile metadata (e.g. @nasa) and Facebook
# pages return authenticated content. Disable by pointing
# TRAILHEAD_CAMOFOX_API at an unreachable port.

_CAMOFOX_API = os.environ.get("TRAILHEAD_CAMOFOX_API", "http://127.0.0.1:9377")
_CAMOFOX_USER = os.environ.get("TRAILHEAD_CAMOFOX_USER", "<profile-id>")
_CAMOFOX_TAB_GROUP = "trailhead"

_CAMOFOX_EXTRACT_JS = (
    "(function(){try{"
    "var d=document.querySelector('meta[property=\"og:description\"]')||document.querySelector('meta[name=\"description\"]');"
    "var t=document.querySelector('meta[property=\"og:title\"]');"
    "return JSON.stringify({title:document.title||'',og:(t&&t.content)||'',desc:(d&&d.content)||'',"
    "text:((document.body&&document.body.innerText)||'').slice(0,9000)});"
    "}catch(e){return JSON.stringify({error:String(e)});}})()"
)


def _camofox_req(path: str, payload: dict | None = None, method: str = "GET", timeout: int = 20) -> dict:
    """Minimal JSON client for the Camofox control API on localhost."""
    import urllib.request as _urllib_request

    data = json.dumps(payload).encode() if payload is not None else None
    req = _urllib_request.Request(
        _CAMOFOX_API + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with _urllib_request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
    return json.loads(body) if body.strip().startswith(("{", "[")) else {"raw": body}


def _camofox_session_fetch(url: str, timeout: int = 30) -> str:
    """Fetch page content through the Camofox persistent profile (authenticated session).

    Opens a short-lived tab in the dedicated ``trailhead`` tab group, extracts
    title / meta description / body text, then closes the tab again."""
    created = _camofox_req(
        "/tabs",
        {"userId": _CAMOFOX_USER, "sessionKey": _CAMOFOX_TAB_GROUP, "url": url},
        method="POST",
        timeout=min(max(timeout, 10), 25),
    )
    tab = str(created.get("tabId") or "")
    if not tab:
        raise RuntimeError(f"camofox: could not open tab ({str(created)[:120]})")
    try:
        data = None
        for _attempt in range(2):
            time.sleep(3)
            try:
                ev = _camofox_req(
                    f"/tabs/{tab}/evaluate",
                    {"userId": _CAMOFOX_USER, "expression": _CAMOFOX_EXTRACT_JS},
                    method="POST",
                    timeout=20,
                )
            except Exception:
                continue
            res = ev.get("result")
            if isinstance(res, str) and res.startswith("{"):
                data = json.loads(res)
                break
        if not data:
            raise RuntimeError("camofox: no page data returned")
        text = str(data.get("text") or "")
        if "Log into Instagram" in text[:2000] and "Mobile number" in text[:2600]:
            raise RuntimeError("camofox: session is not logged in")
        head = str(data.get("title") or "") or str(data.get("og") or "")
        parts = [p for p in (head, str(data.get("desc") or ""), text) if p]
        content = "\n\n".join(parts).strip()
        if len(content) < 120:
            raise RuntimeError("camofox: content too short")
        return content
    finally:
        try:
            _camofox_req(f"/tabs/{tab}?userId={_CAMOFOX_USER}", method="DELETE", timeout=10)
        except Exception:
            pass


def _github_api_json(api: str, timeout: int = 15):
    """GET a GitHub JSON API URL and decode it (raises on failure).

    Uses GITHUB_TOKEN when present (5,000 req/hr vs 60 anonymous).
    """
    req = urllib.request.Request(api, headers=_github_request_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _github_repo_metadata(owner: str, repo: str, parts: list[str], timeout: int) -> str:
    """Repository-level metadata (the best non-auth evidence for a bare repo URL)."""
    api = f"https://api.github.com/repos/{owner}/{repo}"
    data = _github_api_json(api, timeout)
    full_name = data.get('full_name') or f"{owner}/{repo}"
    lines = [f"GitHub repository: {full_name}"]
    desc = data.get("description") or ""
    if desc:
        lines.append(desc)
    homepage = data.get("homepage") or ""
    if homepage:
        lines.append(f"Homepage: {homepage}")
    lines.append(
        f"Stars: {data.get('stargazers_count', 0)} | Forks: {data.get('forks_count', 0)} | Open issues: {data.get('open_issues_count', 0)} | Language: {data.get('language') or 'unknown'}"
    )
    if len(parts) >= 3:
        lines.append(f"Requested path: /{'/'.join(parts[2:])}")
    # README excerpt — real content beyond stats (best-effort, never fatal).
    try:
        import base64

        readme = _github_api_json(f"{api}/readme", timeout)
        raw = base64.b64decode(readme.get("content") or "", validate=False).decode(
            "utf-8", "replace"
        )
        clean = re.sub(r"\n{3,}", "\n\n", raw).strip()
        if clean:
            lines.append("")
            lines.append("README excerpt:")
            lines.append(clean[:1200])
    except Exception:
        pass
    return "\n".join(lines)


def _fetch_github_releases(owner: str, repo: str, rest: list[str], timeout: int) -> str:
    """Fetch real release notes/body for a /releases page (not repo stats)."""
    base = f"https://api.github.com/repos/{owner}/{repo}/releases"
    if len(rest) >= 3 and rest[1] == "tag":
        api = f"{base}/tags/{rest[2]}"
    elif len(rest) >= 2 and rest[1] == "latest":
        api = f"{base}/latest"
    else:
        api = f"{base}?per_page=10"
    data = _github_api_json(api, timeout)
    releases = data if isinstance(data, list) else [data]
    releases = [r for r in releases if isinstance(r, dict)]
    if not releases:
        raise RuntimeError(f"GitHub returned no releases for {owner}/{repo}")
    lines = [f"GitHub releases for {owner}/{repo}"]
    for r in releases:
        tag = r.get("tag_name") or r.get("name") or ""
        name = r.get("name") or ""
        published = (r.get("published_at") or "")[:10]
        body = (r.get("body") or "").strip()
        header = f"Release {tag}"
        if name and name != tag:
            header += f" — {name}"
        if published:
            header += f" ({published})"
        lines.append(f"\n---\n{header}")
        lines.append(body[:4000] if body else "(no release notes body)")
    return "\n".join(lines)


def _fetch_github_file(owner: str, repo: str, ref: str, path: str, timeout: int) -> str:
    """Fetch the requested repository file's actual content."""
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    try:
        req = urllib.request.Request(
            raw, headers={"User-Agent": "Hermes-Trailhead", "Accept": "text/plain,*/*"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        # Fallback: contents API (base64-encoded file body).
        import base64 as _b64
        api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        data = _github_api_json(api, timeout)
        if not isinstance(data, dict) or "content" not in data:
            raise RuntimeError(f"Could not read GitHub file {owner}/{repo}/{ref}/{path}")
        text = _b64.b64decode(data["content"]).decode("utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError(f"GitHub file {owner}/{repo}/{ref}/{path} was empty")
    return f"GitHub file {owner}/{repo}/{ref}/{path}\n\n{text}"


def _fetch_github_tree(owner: str, repo: str, ref: str, path: str, timeout: int) -> str:
    """Fetch a directory listing for a /tree page."""
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    data = _github_api_json(api, timeout)
    if isinstance(data, dict):  # it was actually a file path
        return _fetch_github_file(owner, repo, ref, path, timeout)
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"GitHub returned no directory listing for {owner}/{repo}/{ref}/{path}")
    names = [f"{e.get('type', '')}: {e.get('name', '')}" for e in data if isinstance(e, dict)]
    return f"GitHub directory {owner}/{repo}/{ref}/{path}\n\n" + "\n".join(names)


def _fetch_github_summary(url: str, timeout: int = 15) -> str:
    """Fetch the resource the GitHub URL actually requests.

    A requested release/releases page yields release notes, and a requested
    blob/tree page yields the file/directory content.  When the specifically
    requested resource cannot be retrieved we raise rather than silently
    returning repository metadata, which would misrepresent the page as the
    evidence that was asked for.
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        raise RuntimeError("Not a GitHub URL")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise RuntimeError("GitHub URL does not identify a repository")
    owner, repo = parts[0], parts[1]
    rest = parts[2:]

    if rest and rest[0] == "releases":
        return _fetch_github_releases(owner, repo, rest, timeout)
    if len(rest) >= 3 and rest[0] in {"blob", "raw"}:
        return _fetch_github_file(owner, repo, rest[1], "/".join(rest[2:]), timeout)
    if len(rest) >= 2 and rest[0] == "tree":
        return _fetch_github_tree(owner, repo, rest[1], "/".join(rest[2:]), timeout)
    return _github_repo_metadata(owner, repo, parts, timeout)



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


# Optional per-invocation route pin for the helper run below. The helper runs
# with ``--ignore-user-config``, so without an explicit pin it inherits
# ``hermes chat``'s built-in default route. Setting one or both variables
# appends the corresponding supported CLI argument for that invocation only;
# left unset (the default for every other caller) the command is exactly the
# historical built-in behavior.
HERMES_WEB_EXTRACT_MODEL_ENV = "TRAILHEAD_HERMES_EXTRACT_MODEL"
HERMES_WEB_EXTRACT_PROVIDER_ENV = "TRAILHEAD_HERMES_EXTRACT_PROVIDER"


def _hermes_web_extract_route_args() -> list[str]:
    """Return ``-m``/``--provider`` args when the optional env pin is set."""
    import os as _os

    route_args: list[str] = []
    model = (_os.environ.get(HERMES_WEB_EXTRACT_MODEL_ENV) or "").strip()
    provider = (_os.environ.get(HERMES_WEB_EXTRACT_PROVIDER_ENV) or "").strip()
    if model:
        route_args += ["-m", model]
    if provider:
        route_args += ["--provider", provider]
    return route_args


def _fetch_hermes_web_extract(url: str, timeout: int = 30) -> str:
    """Fetch readable markdown using Hermes' native web_extract tool path.

    The helper run is tagged ``--source tool`` so it stays out of the
    operator's session lists.  When ``TRAILHEAD_HERMES_EXTRACT_MODEL`` /
    ``TRAILHEAD_HERMES_EXTRACT_PROVIDER`` are set (e.g. by the weekly
    social-digest cron), the helper is pinned to that explicit route;
    unset keeps ``hermes chat``'s built-in default.
    """
    prompt = (
        "Use the native web_extract tool on the URL below and return only the "
        "extracted markdown content, with no explanation, no preamble, and no "
        "code fencing.\n\n"
        f"URL: {json.dumps(url)}"
    )
    cmd = [
        "hermes",
        "chat",
        *_hermes_web_extract_route_args(),
        "-q",
        prompt,
        "-t",
        "web",
        "-Q",
        "--ignore-rules",
        "--ignore-user-config",
        "--source",
        "tool",
        "--safe-mode",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(timeout, 30))
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"hermes chat failed with exit code {proc.returncode}")

    content = _strip_hermes_web_extract_output(proc.stdout)
    if not content:
        raise RuntimeError("hermes web_extract returned empty content")
    if _looks_like_extraction_error(content):
        # The subprocess relayed its own failure narration as "content".
        raise RuntimeError(f"hermes web_extract reported failure: {content[:200]}")
    return content


def _exception_summary(exc: Exception) -> str:
    """Return a compact human-readable summary of an exception."""
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return f"{type(exc).__name__}: {msg}"


# Hermes' native web_extract subprocess relays its own failure narration as the
# "content" (provider misconfiguration, tool error).  That text is tool output,
# never page evidence — reporting it as a successful extraction is a false success.
_EXTRACTION_ERROR_MARKERS = (
    "extraction failed",
    "no registered web extract provider",
    "web_extract is configured to use",
    "web_extract returned empty content",
)

_HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _looks_like_extraction_error(text: str) -> bool:
    """True when ``text`` is the extractor's own failure message, not content."""
    head = re.sub(r"\s+", " ", (text or "").strip().lower())[:200]
    if not head:
        return False
    return any(marker in head for marker in _EXTRACTION_ERROR_MARKERS)


def _clean_html_text(text: str) -> str:
    text = _HTML_SCRIPT_STYLE_RE.sub(" ", text or "")
    text = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_html_shell(content: str) -> bool:
    """Detect client-rendered HTML/JS shells that carry no readable source text.

    A genuine fetched HTML page (docs, article, forum thread) keeps a large
    share of unique words once tags and scripts are stripped.  Platform shells
    (new Reddit, X, JS-only apps) leave only navigation/boilerplate that
    collapses to a handful of repeated tokens — that is not evidence.
    """
    raw = content or ""
    low = raw.lower()
    if not any(t in low for t in ("<!doctype html", "<html", "<body", "<script", "<div")):
        return False
    cleaned = _clean_html_text(raw)
    words = [w for w in cleaned.split() if any(c.isalnum() for c in w)]
    if len(words) < 25:
        return True
    unique = len({w.lower() for w in words})
    return (unique / len(words)) < 0.2


def _is_usable_page_text(content: str) -> bool:
    """True when fetched text is genuine, readable source text.

    Rejects the extractor's own failure narration and client-rendered HTML
    shells so they are never reported (or scored) as successful extraction.
    """
    if not content or len(content) <= 50:
        return False
    if _looks_like_extraction_error(content):
        return False
    if _is_html_shell(content):
        return False
    return True


def _is_platform_shell(source_type: str, content: str) -> bool:
    """Detect login/error shells that are not usable source summaries."""
    text = re.sub(r"\s+", " ", (content or "").strip().lower())
    if not text:
        return True
    if source_type == "instagram":
        bad = (
            "instagramlog inerrorpost isn't available",
            "post isn't availablethe link may be broken",
            "this page isn’t working",
            "this page isn't working",
            "http error 429",
        )
        # Only flag as a shell if NONE of these positive markers exist
        # (real content indicators that prove this isn't just a login page)
        positive = (
            "voron", "stealthchanger", "3dprint", "build", "toolchanger",
            "comment", "reply", "like", "share", "save", "follow",
        )
        if any(marker in text for marker in bad):
            # It has error markers — but check if it also has real content
            if not any(p in text for p in positive):
                return True
        # Also check: if the text is purely the app shell with zero unique content
        if len(text) < 30:
            return True
        return False
    if source_type == "youtube":
        bad = (
            "sign in to confirm you’re not a bot",
            "sign in to confirm you're not a bot",
            "unusual traffic",
            "captcha",
        )
        return any(marker in text for marker in bad)
    return False

# ── Stealth Chrome backend (primary) ──────────────────────────────────

_STEALTH_EXTRACT_SCRIPT = str(
    __import__("pathlib").Path(__file__).resolve().parent.parent / "stealth-extract.js"
)

def _fetch_stealth_chrome(url: str, timeout: int = 30, cookies: str | None = None) -> str:
    """Fetch page content through puppeteer-extra + stealth plugin Chrome.

    Stealth-patched Chrome passes bot detection on YouTube, Instagram, and
    TikTok.  Returns clean page text.  For YouTube URLs, also attempts to
    extract auto-generated captions from the DOM.

    Requires: node, puppeteer-extra, puppeteer-extra-plugin-stealth
    """
    cmd = [
        "node", _STEALTH_EXTRACT_SCRIPT, url,
        "--timeout", str(max(timeout, 15) * 1000),
    ]
    proxy = _get_proxy_url()
    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies and __import__("os").path.exists(cookies):
        cmd.extend(["--cookies", cookies])
    if "youtube.com" in url or "youtu.be" in url:
        cmd.append("--transcript")

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"stealth-extract failed with exit {proc.returncode}")

    try:
        result = __import__("json").loads(proc.stdout)
    except Exception:
        raise RuntimeError(f"stealth-extract returned invalid JSON: {proc.stdout[:200]}")

    if not result.get("ok"):
        raise RuntimeError(result.get("error", "stealth-extract failed"))

    text = result.get("text", "")
    if not text or len(text) < 20:
        raise RuntimeError("stealth-extract returned empty page content")

    # For YouTube, prefix transcript if available
    transcript = result.get("transcript")
    if transcript:
        text = f"YouTube transcript:\n\n{transcript}\n\n---\n\nPage text:\n\n{text}"

    return text


# ── yt-dlp transcript backend ────────────────────────────────────────

def _fetch_ytdlp_transcript(url: str, timeout: int = 30) -> str:
    """Fetch YouTube auto-generated subtitles using yt-dlp.

    yt-dlp is battle-tested and uses multiple extraction methods to bypass
    YouTube restrictions.  Downloads English auto-subs as SRT, converts to
    plain text.  This is the PRIMARY YouTube transcript path since
    youtube-transcript-api is IP-blocked on datacenter IPs.
    """
    video_id = _youtube_video_id(url)
    if not video_id:
        raise RuntimeError("Could not parse YouTube video id")

    # yt-dlp's subtitle download+convert needs headroom: CLI extract budgets
    # pass ~10s which starves every attempt (transcript exists, route works,
    # but the call times out → false "blocked"). Floor per-attempt timeout.
    timeout = max(timeout, 30)

    # Transcript cache: repeat queries never re-hit YouTube — fewer caption
    # 429 windows and instant re-extraction of videos seen before.
    cache_dir = hermes_state_dir() / "trailhead-transcripts"
    try:
        cached_file = cache_dir / f"{video_id}.txt"
        if cached_file.exists():
            cached_text = cached_file.read_text(encoding="utf-8")
            if len(cached_text) > 50:
                return cached_text
    except Exception:
        pass

    out_path = f"/tmp/yt-trailhead-{video_id}"

    # Proxy failover: prefer the round-robin proxy, but if a residential
    # route has died (e.g. expired auth -> 407), fall back to every other
    # enabled proxy BEFORE giving up.  A dead route should never block a
    # transcript while a working residential route still exists.
    proxy_plan = _proxy_failover_plan()

    last_error: str | None = None
    node = shutil.which("node")
    if not node:
        from pathlib import Path as _P
        for cand in sorted((_P.home() / ".hermes" / "tools").glob("node-*/bin/node")):
            node = str(cand)
            break
    js_args: list[str] = []
    if node:
        # Newer YouTube extraction needs a JS runtime for challenge solving
        # ("No supported JavaScript runtime could be found") — node exists on
        # this host; without this flag many videos fail despite captions
        # existing. Harmless (ignored) if yt-dlp predates the option.
        js_args = ["--js-runtimes", f"node:{node}"]
    for proxy in proxy_plan:
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-subs",
            "--sub-lang", "en",
            "--convert-subs", "srt",
            "-o", out_path,
            *js_args,
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(url)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last_error = f"yt-dlp timed out (proxy: {_proxy_host(proxy)})"
            continue
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if "Video unavailable" in stderr or "Private video" in stderr:
                raise RuntimeError(f"YouTube: Video unavailable or private")
            last_error = f"yt-dlp failed: {stderr[:200]}"
            # A transport/auth failure on one proxy doesn't mean the video
            # is unwritable — try the next route.
            continue

        # Read the downloaded SRT file
        import glob as _glob
        srt_files = _glob.glob(f"{out_path}.en.srt")
        if not srt_files:
            last_error = "yt-dlp: no subtitle file produced (video may lack auto-captions)"
            continue

        raw = ""
        try:
            with open(srt_files[0], "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception as exc:
            last_error = f"yt-dlp: could not read subtitle file: {exc}"
            continue
        finally:
            try:
                __import__("os").remove(srt_files[0])
            except Exception:
                pass

        # ---- successful proxy route produced an SRT — parse and return ----
        lines: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.isdigit():
                continue  # sequence number
            if "-->" in line:
                continue  # timestamp
            if line.startswith("[") and line.endswith("]"):
                continue  # music/sound effect tags
            lines.append(line)

        prev = ""
        deduped_lines: list[str] = []
        for line in lines:
            clean = line.strip(" ,;.!?-")
            if not clean:
                continue
            if prev and clean.startswith(prev):
                suffix = clean[len(prev):].strip()
                if suffix:
                    deduped_lines.append(suffix)
                    prev = clean
            elif prev and prev.startswith(clean):
                pass
            else:
                deduped_lines.append(line)
                prev = clean

        content = " ".join(deduped_lines).strip()
        if not content or len(content) < 30:
            last_error = "yt-dlp: subtitle content too short or empty"
            continue

        result = f"YouTube auto-captions for {video_id}\n\n{content}"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{video_id}.txt").write_text(result, encoding="utf-8")
        except Exception:
            pass
        return result

    # All proxy routes failed (including the direct/no-proxy route when
    # proxy_plan is empty).
    raise RuntimeError(last_error or "yt-dlp: no proxy route produced a transcript")


# ── Browser Harness backend (legacy fallback) ─────────────────────────

def _fetch_browser_harness(url: str, timeout: int = 30) -> str:
    """Fetch page content through the repo-local Chrome CDP adapter.

    The adapter is invoked by absolute path rather than relying on a
    ``browser-harness`` executable being installed in PATH. Its CDP endpoint
    is configured with ``TRAILHEAD_BROWSER_CDP_URL`` (the HP worker tunnel by
    default).
    """
    from pathlib import Path

    script = _BROWSER_EXTRACT_SCRIPT.replace("{url}", url).replace("{timeout}", str(timeout))
    # The legacy DSL hard-coded 14 settle attempts. Keep the adapter's CDP
    # wait budget aligned with the caller's timeout (one 0.8s attempt/second).
    script = script.replace("range(1, 15)", f"range(1, {max(2, timeout + 1)})")
    adapter = Path(__file__).resolve().parent.parent / "scripts" / "browser-harness.js"
    proc = subprocess.run(
        ["node", str(adapter)],
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


# ── Apify backend (primary for Instagram / TikTok) ─────────────────────

_ApifyClient = None  # lazy import


def _get_apify_token() -> str | None:
    """Read Apify API token from secrets file or environment."""
    import os as _os
    token = _os.environ.get("APIFY_API_KEY")
    if token:
        return token
    token_path = hermes_secrets_dir() / "apify-api-key.txt"
    try:
        with open(token_path) as f:
            token = f.read().strip()
            if token:
                return token
    except Exception:
        pass
    return None


def _get_apify_client():
    """Lazy-init Apify client. Returns None if no API key configured."""
    global _ApifyClient
    token = _get_apify_token()
    if not token:
        return None
    if _ApifyClient is None:
        from apify_client import ApifyClient as _AC
        _ApifyClient = _AC
    return _ApifyClient(token)


def _instagram_shortcode(url: str) -> str:
    """Extract shortcode from Instagram URL like /p/DDaO4kPyB7W/."""
    import re as _re
    m = _re.search(r'instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else ""


def _get_proxy_url() -> str | None:
    """Read and rotate through residential proxy URLs.

    Reads from the canonical Hermes secrets dir
    (``<hermes-home>/secrets/trailhead-proxy-url.txt`` — one URL per line).
    Rotates roundrobin across all configured proxies using a counter stored
    in the canonical Hermes state dir so successive calls cycle through
    different residential IPs.  Resolution follows ``HERMES_HOME`` (see
    ``hermes_trailhead.paths``) instead of raw ``~`` expansion, so proxy
    lookup works from the normal host shell where ``$HOME`` is not the
    Hermes home.

    Also respects TRAILHEAD_PROXY_URL env var (single proxy, no rotation).
    """
    import os as _os
    proxy = _os.environ.get("TRAILHEAD_PROXY_URL")
    if proxy:
        return proxy

    proxy_path = hermes_secrets_dir() / "trailhead-proxy-url.txt"
    proxy_urls: list[str] = []
    try:
        with open(proxy_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    proxy_urls.append(line)
    except Exception:
        pass

    if not proxy_urls:
        return None
    if len(proxy_urls) == 1:
        return proxy_urls[0]

    # Roundrobin rotation
    counter_path = hermes_state_dir() / "trailhead-proxy-round.txt"
    idx = 0
    try:
        with open(counter_path) as f:
            idx = int(f.read().strip() or "0")
    except Exception:
        pass

    chosen = proxy_urls[idx % len(proxy_urls)]
    try:
        _os.makedirs(_os.path.dirname(counter_path), exist_ok=True)
        with open(counter_path, "w") as f:
            f.write(str((idx + 1) % 10000))  # wrap to avoid unbounded growth
    except Exception:
        pass

    return chosen


def _enabled_proxy_urls() -> list[str]:
    """Read every enabled residential proxy URL (no rotation).

    Honors TRAILHEAD_PROXY_URL env var as a single-proxy list.  Reads one
    URL per line from the canonical Hermes secrets file.  Secrets are never
    logged or printed by this module — only handed to yt-dlp as a ``--proxy``
    value.  The list keeps the proxy components, order, and values intact.
    """
    import os as _os
    env = _os.environ.get("TRAILHEAD_PROXY_URL")
    if env:
        return [env]
    proxy_path = hermes_secrets_dir() / "trailhead-proxy-url.txt"
    urls: list[str] = []
    try:
        with open(proxy_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except Exception:
        pass
    return urls


def _proxy_host(proxy: str | None) -> str:
    """Return host:port of a proxy URL for logging, without credentials."""
    if not proxy:
        return "direct"
    # http://user:pass@host:port  -> host:port
    after_scheme = proxy.split("://", 1)[-1]
    host_part = after_scheme.split("@", 1)[-1]
    return host_part


def _proxy_failover_plan() -> list[str | None]:
    """Build the ordered proxy list for a yt-dlp transcript attempt.

    Starts with the round-robin-chosen proxy (or None for direct), then
    appends the remaining enabled proxies, deduplicated.  If no proxy is
    configured, returns [None] so the fetch still attempts a direct route.
    This is what lets a transcript succeed even when the rotating proxy has
    died (e.g. expired residential auth returning 407) — the call falls back
    to another working residential route already in the config.
    """
    plan: list[str | None] = []
    first = _get_proxy_url()
    plan.append(first if first else None)
    for extra in _enabled_proxy_urls():
        if extra not in plan:
            plan.append(extra)
    return plan


_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_via_route(url: str, proxy, timeout: int = 15, *, opener_factory=None) -> str | None:
    """Fetch a URL through ONE specific route (a proxy URL, or None = direct).

    Returns the decoded body (capped at 50k chars) or None on any failure /
    insufficient content.  Shared by the proxy-pool fetch and by callers that
    need to inspect content per-route (e.g. skipping routes that serve shells).
    """
    try:
        if opener_factory is not None:
            opener = opener_factory(proxy)
        elif proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
        else:
            opener = urllib.request.build_opener()
        resp = opener.open(urllib.request.Request(url, headers=_FETCH_HEADERS), timeout=timeout)
        raw = resp.read()
        # Try UTF-8, fall back to latin-1
        try:
            text = raw.decode()
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        if text and len(text) > 200:
            return text[:50000]
    except Exception:
        pass
    return None


def _fetch_proxy(url: str, timeout: int = 15, *, opener_factory=None) -> str:
    """HTTP fetch through the residential proxy pool with failover.

    Handles sites that block datacenter IPs — sits between free web_extract
    (datacenter, fast, no JS) and Browser Harness (residential, heavy, JS).

    Routes come from `_proxy_failover_plan()` (round-robin pick first, then the
    remaining enabled proxies).  A dead route (e.g. expired residential auth
    returning 407) must not kill the proxy tier while another enabled proxy
    still works, and individual residential routes are observed to flake
    per-request — so the plan runs twice before giving up.  Falls back to a
    direct fetch when no proxy is configured, making it safe to use as a
    universal fetcher.
    """
    routes = [p for p in _proxy_failover_plan() if p]
    for _round in range(2):
        for proxy in routes:
            result = _fetch_via_route(url, proxy, timeout=timeout, opener_factory=opener_factory)
            if result:
                return result

    # Strategy 2: direct (datacenter IP — works for most sites)
    result = _fetch_via_route(url, None, timeout=timeout, opener_factory=opener_factory)
    if result:
        return result

    raise RuntimeError(
        f"Failed to fetch {url} — proxy pool and direct paths returned "
        f"insufficient content"
    )


def _get_instagram_session() -> str | None:
    """Read Instagram session cookie from the canonical Hermes secrets dir."""
    session_path = hermes_secrets_dir() / "instagram-session.txt"
    try:
        with open(session_path) as f:
            return f.read().strip()
    except Exception:
        return None


# ── Instagram internal API backend (NO AUTH, NO PROXY) ──────────────────

def _fetch_instagram_api(url: str, timeout: int = 15) -> str:
    """Extract Instagram content via internal API + proxy page fetch.

    Uses Instagram's own i.instagram.com REST API (still serves public data
    without auth) plus OG metadata from proxy-backed page fetches that
    bypass bot detection.  Discovered June 2026: the web_profile_info
    endpoint returns 12 posts with full captions from datacenter IPs with
    no session cookie.
    """
    import json as _json

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "X-IG-App-ID": "936619743392459",
        "Accept": "application/json",
    }

    proxy = _get_proxy_url()

    shortcode = _instagram_shortcode(url)
    if shortcode:
        is_reel = '/reel/' in url

        # Specific post/reel — try direct page fetch through proxy first.
        # Extracts OG title/description which carries the full caption for
        # public posts.  Reels are JS shells (no OG data) but the page
        # loads cleanly through proxy without a login wall.
        page_url = url.split('?')[0]
        page_headers = {**headers, "Accept": "text/html,application/xhtml+xml"}
        try:
            raw = _fetch_text_tiered(page_url, timeout=timeout)
            if raw and not _is_platform_shell("instagram", raw):
                import re as _re2
                og_title = _re2.findall(
                    r'<meta\s+property="og:title"\s+content="([^"]*)"', raw
                )
                og_desc = _re2.findall(
                    r'<meta\s+property="og:description"\s+content="([^"]*)"', raw
                )
                title_decoded = (og_title[0] if og_title else "").replace("&quot;", '"').replace("&#064;", "@")
                desc_decoded = (og_desc[0] if og_desc else "").replace("&quot;", '"').replace("&#064;", "@")
                if title_decoded:
                    author = ""
                    author_match = _re2.search(r'on Instagram: "', title_decoded)
                    if author_match:
                        author = title_decoded[:author_match.start()].strip()
                    caption = title_decoded[title_decoded.index('"') + 1:].rstrip('"').replace("\\n", "\n") if '"' in title_decoded else title_decoded
                    caption = caption.replace("&#xd;", "").replace("&#xc6d4;", "월").replace("&#xc77c;", "일").replace("&#xc5d0;", "에").replace("&#xc2dc;", "시").replace("&#xc791;", "작").replace("&#xd558;", "하").replace("&#xc5ec;", "여").replace("&#xc870;", "조").replace("&#xb9bd;", "립").replace("&#xc644;", "완").replace("&#xb8cc;", "료")
                    return f"Instagram post by @{author}:\n\n{caption}" if author else f"Instagram caption:\n\n{caption}"
        except Exception:
            pass

        # Fallback: try oEmbed for posts (reels don't support it)
        if not is_reel:
            embed_url = quote(url.split('?')[0], safe='')
            req = urllib.request.Request(
                f"https://i.instagram.com/api/v1/oembed/?url={embed_url}",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = _json.loads(resp.read().decode())
                    title = data.get("title", "")
                    author = data.get("author_name", "")
                    if title:
                        return f"Instagram post by @{author}:\n\n{title}"
            except Exception:
                pass

        if is_reel:
            # Reels are JS shells — HTTP fetch gets no OG metadata.  Use
            # stealth Chrome with proxy to render the page and extract
            # captions from the live DOM.
            try:
                content = _fetch_stealth_chrome(url, timeout=max(timeout, 25))
                if content and len(content) > 50 and not _is_platform_shell("instagram", content):
                    return content
            except Exception:
                pass
            # Stealth Chrome failed or returned unusable content.
            # Discovery captions from search provide the fallback summary.
            return ""

        # Post — nothing worked; can't extract without auth
        raise RuntimeError(f"Could not fetch Instagram post {shortcode}")

    # Profile URL — extract username, hit web_profile_info
    import re as _re
    m = _re.search(r'instagram\.com/([A-Za-z0-9_.]+)', url)
    username = m.group(1) if m else ""
    if not username or username in ("p", "reel", "stories", "explore"):
        raise RuntimeError(f"Could not parse Instagram username from {url}")

    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    req = urllib.request.Request(api_url, headers=headers)

    # Small delay to respect rate limits (Instagram allows ~200 req/hr per IP)
    import time as _time
    _time.sleep(2)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "rate" in err_msg.lower():
            raise RuntimeError(
                f"Instagram rate limited — retry in 60s. "
                f"(Profile endpoint allows ~200 req/hr; use oEmbed for individual posts.)"
            )
        raise

    user = data.get("data", {}).get("user", {})
    if not user:
        raise RuntimeError(f"Instagram API returned no user data for @{username}")

    bio = user.get("biography", "")
    follower_count = user.get("edge_followed_by", {}).get("count", 0)
    lines = [f"Instagram profile: @{user.get('username', username)} ({follower_count} followers)"]
    if bio:
        lines.append(f"Bio: {bio}")

    edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])
    if not edges:
        if bio:
            return "\n".join(lines)
        raise RuntimeError(f"Instagram API returned no posts for @{username}")

    for edge in edges[:5]:
        node = edge.get("node", {})
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        if caption_edges:
            caption = caption_edges[0].get("node", {}).get("text", "")
            if caption:
                short = node.get("shortcode", "")
                likes = node.get("edge_liked_by", {}).get("count", 0)
                comments = node.get("edge_media_to_comment", {}).get("count", 0)
                lines.append(
                    f"\n---\n{caption}\n"
                    f"[{likes} likes, {comments} comments] "
                    f"instagram.com/p/{short}/"
                )

    if len(lines) == 1 or (len(lines) == 2 and bio):
        raise RuntimeError(f"No captioned posts found for @{username}")
    return "\n".join(lines)


# ── Self-hosted Instagram backend (instaloader + curl_cffi) ─────────────

def _fetch_instaloader_instagram(url: str, timeout: int = 30) -> str:
    """Extract Instagram content via self-hosted instaloader.

    Uses instaloader + curl_cffi for TLS fingerprinting + optional residential
    proxy.  Requires either a session cookie or login credentials in secrets.
    Falls back to anonymous access (heavy rate-limiting without proxy).
    """
    import instaloader as _il
    import os as _os

    proxy_url = _get_proxy_url()
    session_file = hermes_state_dir() / "instagram-sessionfile"

    L = _il.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    # Configure proxy if available
    if proxy_url:
        _os.environ["HTTP_PROXY"] = proxy_url
        _os.environ["HTTPS_PROXY"] = proxy_url

    try:
        # Try loading existing session
        if _os.path.exists(session_file):
            L.load_session_from_file(filename=session_file)

        shortcode = _instagram_shortcode(url)
        if shortcode:
            post = _il.Post.from_shortcode(L.context, shortcode)
            caption = post.caption or ""
            if caption:
                return f"Instagram post by @{post.owner_username}:\n\n{caption}"
            raise RuntimeError("Instagram post has no caption text")
        else:
            # Profile URL — extract username
            import re as _re
            m = _re.search(r'instagram\.com/([A-Za-z0-9_.]+)', url)
            username = m.group(1) if m else ""
            if not username:
                raise RuntimeError(f"Could not parse Instagram URL: {url}")

            profile = _il.Profile.from_username(L.context, username)
            posts = profile.get_posts()
            lines = [f"Instagram profile: @{username} ({profile.followers} followers)"]
            count = 0
            for post in posts:
                if count >= 5:
                    break
                if post.caption:
                    lines.append(f"\n---\n{post.caption[:500]}")
                    count += 1
            if count == 0:
                raise RuntimeError("No captioned posts found on profile")
            return "\n".join(lines)

    except Exception:
        raise
    finally:
        # Clean up proxy env
        if proxy_url:
            _os.environ.pop("HTTP_PROXY", None)
            _os.environ.pop("HTTPS_PROXY", None)


# ── TikTok rehydration blob backend (FREE, no proxy needed) ──────────


def _fetch_tiktok_rehydration(url: str, timeout: int = 15) -> str:
    """Extract TikTok content via __UNIVERSAL_DATA_FOR_REHYDRATION__ blob.

    TikTok embeds full video/profile metadata in a server-side JSON blob
    rendered BEFORE any JavaScript.  This works from datacenter IPs without
    proxy, auth, or accounts for single-video and single-profile lookups.

    Falls back to proxy-backed extraction when a proxy URL is configured,
    which bypasses TikTok's WAF for video pages on residential IPs.

    Returns the video caption/description as a string, or raises RuntimeError.
    """
    import json as _json
    import re as _re

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def _try_fetch(req_url: str, use_proxy: bool = False) -> str | None:
        """Attempt one fetch, returning HTML string or None."""
        try:
            if use_proxy:
                proxy = _get_proxy_url()
                if not proxy:
                    return None
                proxy_handler = urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy}
                )
                opener = urllib.request.build_opener(proxy_handler)
                req = urllib.request.Request(req_url, headers=headers)
                resp = opener.open(req, timeout=timeout)
            else:
                req = urllib.request.Request(req_url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read().decode()
        except Exception:
            return None

    # Strategy 1: direct (free, works from datacenter IPs for video pages)
    html = _try_fetch(url, use_proxy=False)
    # Strategy 2: proxy (bypasses WAF on residential IPs)
    if not html or len(html) < 5000:
        html = _try_fetch(url, use_proxy=True)

    if not html:
        raise RuntimeError(f"Failed to fetch TikTok page: {url}")

    # Extract rehydration blob FIRST — TikTok embeds full data even on WAF pages
    m = _re.search(
        r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
    )
    if not m:
        # No blob at all — genuine block or error page
        if "slardar" in html.lower() or ('waf' in html.lower() and len(html) < 3000):
            raise RuntimeError("TikTok WAF blocked the request — no rehydration blob")
        raise RuntimeError("No rehydration blob found in TikTok page")

    data = _json.loads(m.group(1))
    scope = data.get("__DEFAULT_SCOPE__", {})

    # ── Video detail ──
    vd = scope.get("webapp.video-detail", {})
    if vd.get("statusCode") == 0 and "itemInfo" in vd:
        v = vd["itemInfo"]["itemStruct"]
        desc = v.get("desc", "")
        stats = v.get("stats", {})
        author = v.get("author", {})
        music = v.get("music", {})
        hashtags = [
            t["hashtagName"]
            for t in v.get("textExtra", [])
            if t.get("hashtagName")
        ]

        lines = [f"TikTok by @{author.get('uniqueId', 'unknown')}: {desc}"]
        lines.append(
            f"  ❤️ {stats.get('diggCount', 0):,} | "
            f"👁 {stats.get('playCount', 0):,} | "
            f"💬 {stats.get('commentCount', 0):,} | "
            f"🔄 {stats.get('shareCount', 0):,}"
        )
        if hashtags:
            lines.append(f"  🏷 {' '.join('#' + t for t in hashtags)}")
        if music.get("title"):
            lines.append(f"  🎵 {music['title']}")
        return "\n".join(lines)

    # ── Profile detail ──
    ud = scope.get("webapp.user-detail", {})
    if ud.get("statusCode") == 0 and "userInfo" in ud:
        ui = ud["userInfo"]
        u = ui.get("user", {})
        stats = ui.get("stats", {})
        videos = ui.get("itemList", [])

        lines = [
            f"TikTok Profile: @{u.get('uniqueId', 'unknown')} "
            f"({u.get('nickname', '')})"
        ]
        lines.append(
            f"  {stats.get('followerCount', 0):,} followers | "
            f"{stats.get('followingCount', 0)} following | "
            f"{stats.get('videoCount', 0)} videos"
        )
        if u.get("signature"):
            lines.append(f"  Bio: {u['signature'][:300]}")
        for v in videos[:5]:
            vdesc = v.get("desc", "")
            vstats = v.get("stats", {})
            if vdesc:
                plays = vstats.get("playCount", "")
                line = f"  📹 {vdesc[:120]}"
                if plays:
                    line += f" [👁 {plays:,}]"
                lines.append(line)
        return "\n".join(lines)

    raise RuntimeError("TikTok page did not contain recognizable video or profile data")


# ── Self-hosted TikTok backend (tiktok-scraper npm package) ────────────

def _fetch_tiktok_scraper(url: str, timeout: int = 30) -> str:
    """Extract TikTok content via self-hosted tiktok-scraper.

    Uses the drawrowfly/tiktok-scraper npm package.  No login required —
    uses TikTok's public Web API.  Needs residential proxy for sustained
    use to avoid IP blocks.
    """
    import re as _re
    m = _re.search(r'tiktok\.com/@([A-Za-z0-9_.]+)', url)
    username = m.group(1) if m else ""

    if not username:
        # Try video ID extraction
        m = _re.search(r'tiktok\.com/.*?/video/(\d+)', url)
        if m:
            # For single video, use video metadata
            cmd = [
                "npx", "-y", "tiktok-scraper",
                "video", url,
                "--number", "1",
                "--no-download",
                "--json",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
            if proc.returncode == 0 and proc.stdout.strip():
                # Parse JSON output
                import json as _json
                try:
                    data = _json.loads(proc.stdout.strip().splitlines()[-1])
                    desc = data.get("text", "") or data.get("description", "")
                    if desc and len(desc) > 20:
                        return f"TikTok: {desc}"
                except Exception:
                    pass
        raise RuntimeError(f"Could not extract TikTok content from {url}")

    # Profile-level extraction
    cmd = [
        "npx", "-y", "tiktok-scraper",
        "user", username,
        "--number", "5",
        "--no-download",
        "--json",
    ]
    proxy = _get_proxy_url()
    if proxy:
        cmd.extend(["--proxy", proxy])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(stderr or f"tiktok-scraper failed with exit {proc.returncode}")

    # Parse JSON output — each line is a JSON object
    lines_out: list[str] = []
    for line in proc.stdout.strip().splitlines():
        import json as _json
        try:
            item = _json.loads(line)
            desc = item.get("text", "") or item.get("description", "")
            if desc:
                plays = item.get("playCount", "") or item.get("diggCount", "")
                entry = f"TikTok: {desc}"
                if plays:
                    entry += f"\n  [plays: {plays}]"
                lines_out.append(entry)
        except Exception:
            pass

    if not lines_out:
        raise RuntimeError("tiktok-scraper returned no usable content")
    return "\n\n".join(lines_out)


# ── Instagram / TikTok cookie paths ───────────────────────────────────

def _get_platform_cookies(platform: str) -> str | None:
    """Return path to burner-account cookies file if it exists.

    Lives in the canonical Hermes state dir so the path is the same from the
    normal host shell, agent sessions, and cron.
    """
    cookie_path = hermes_state_dir() / f"{platform}-cookies.json"
    return str(cookie_path) if cookie_path.exists() else None


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
    fetcher = fetch or _fetch_text_tiered
    source_type = _classify_source_type(url)

    if source_type == "github" and fetch is None:
        try:
            content = _fetch_github_summary(url, timeout=timeout)
            if content:
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                )
        except Exception:
            pass

    # TikTok / Instagram: Apify first (primary), then oEmbed, stealth Chrome,
    # then browser-harness fallback.
    # X/Twitter: lane-native structured content — FxTwitter API (tweet text +
    # engagement) then local Nitter (tweet + replies).  Replaces the old
    # whole-page Jina text (~150k chars of page chrome for a single tweet).
    if source_type == "x" and fetch is None:
        for _x_fetch in (_fetch_fxtwitter, _fetch_nitter):
            try:
                x_content = _x_fetch(url, timeout=max(timeout, 15))
                if x_content and len(x_content) > 80:
                    return ExtractionResult(
                        status="ok",
                        content=x_content[:8000],
                        content_length=len(x_content),
                        source_type=source_type,
                    )
            except Exception:
                pass
        # Fall through to generic tiers (Jina etc.)

    # ── Facebook: authenticated fetch through the Camofox persistent profile
    # (logged-in session). Facebook has no loginless extraction surface from
    # datacenter IPs — this tier is the lane's content path. ──
    if fetch is None and ("facebook.com" in url.lower() or "fb.watch" in url.lower()):
        try:
            content = _camofox_session_fetch(url, timeout=max(timeout, 30))
            if content and len(content) > 120:
                return ExtractionResult(
                    status="ok",
                    content=content[:8000],
                    content_length=len(content),
                    source_type=source_type,
                    video_evidence=VideoEvidence(
                        caption_status="ok",
                        caption_text=content[:2000],
                        caption_transcript_status="not_attempted",
                        visual_analysis_status="available",
                        visual_analysis_summary=content[:2000],
                        metadata_url=url,
                        metadata_title=title,
                    ),
                )
        except Exception:
            pass  # No session / camofox unreachable → generic tiers below

    if source_type in ("tiktok", "instagram"):

        # ── TikTok: TikWM public API — full metadata + engagement (free, no
        # auth, any IP; verified direct 2026-10-14) ──
        if source_type == "tiktok" and fetch is None:
            try:
                content = _fetch_tikwm(url, timeout=max(timeout, 20))
                if content and len(content) > 200:
                    # Video audio transcript (Groq Whisper via TikWM's play URL).
                    # Best-effort: metadata/comments never fail because of it.
                    transcript, tr_status, tr_error = "", "not_available", ""
                    try:
                        transcript = _fetch_tiktok_transcript(url, timeout=max(timeout, 60))
                        tr_status = "ok"
                    except Exception as exc:
                        tr_error = str(exc)[:140]
                    full = content + (f"\n\n{transcript}" if transcript else "")
                    return ExtractionResult(
                        status="ok",
                        content=full[:8000],
                        content_length=len(full),
                        source_type=source_type,
                        video_evidence=VideoEvidence(
                            caption_status="ok",
                            caption_text=content[:2000],
                            caption_transcript_status=tr_status,
                            caption_transcript=transcript[:4000],
                            caption_transcript_length=len(transcript),
                            caption_transcript_error=tr_error if tr_status != "ok" else "",
                            visual_analysis_status="available",
                            visual_analysis_summary=content[:2000],
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass  # TikWM unreachable → rehydration / oEmbed fallbacks

        # ── TikTok: rehydration blob (PRIMARY — free, works from datacenter IPs) ──
        if source_type == "tiktok" and fetch is None:
            try:
                content = _fetch_tiktok_rehydration(url, timeout=max(timeout, 20))
                if content and len(content) > 50:
                    return ExtractionResult(
                        status="ok",
                        content=content[:8000],
                        content_length=len(content),
                        source_type=source_type,
                        video_evidence=VideoEvidence(
                            caption_status="ok",
                            caption_text=content[:2000],
                            caption_transcript_status="not_attempted",
                            visual_analysis_status="available",
                            visual_analysis_summary=content[:2000],
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass  # Rehydration failed → fall through to oEmbed

        # TikTok oEmbed: reliable metadata extraction (works direct + proxy, never WAF'd)
        if source_type == "tiktok":
            # Try direct first (works from any IP, no proxy needed)
            try:
                oembed_url = f"https://www.tiktok.com/oembed?url={url}"
                content = fetcher(oembed_url, timeout=timeout)
                if content and len(content) > 40:
                    import json as _json3
                    try:
                        data = _json3.loads(content)
                        title_text = data.get("title", "")
                        author = data.get("author_name", "")
                        desc = f"TikTok by @{author}: {title_text}" if author else title_text
                        if desc and len(desc) > 10:
                            return ExtractionResult(
                                status="ok",
                                content=desc[:2000],
                                content_length=len(desc),
                                source_type=source_type,
                                video_evidence=VideoEvidence(
                                    caption_status="ok",
                                    caption_text=desc[:2000],
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

        # ── Instagram: loginless /embed/captioned/ page — full caption + author
        # + social proof, static variant for bot UAs (verified direct from this
        # host 2026-10-14) ──
        if source_type == "instagram" and fetch is None:
            try:
                content = _fetch_instagram_embed(url, timeout=max(timeout, 20))
                if content and len(content) > 120:
                    return ExtractionResult(
                        status="ok",
                        content=content[:8000],
                        content_length=len(content),
                        source_type=source_type,
                        video_evidence=VideoEvidence(
                            caption_status="ok",
                            caption_text=content[:2000],
                            caption_transcript_status="not_attempted",
                            visual_analysis_status="available",
                            visual_analysis_summary=content[:2000],
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass  # Embed unavailable → self-hosted / browser tiers

        # ── Instagram catch-all: authenticated fetch through the Camofox
        # persistent profile. Profiles have no /embed/ surface, and posts
        # whose static embed is blocked land here too (verified 2026-10-14). ──
        if source_type == "instagram" and fetch is None:
            try:
                content = _camofox_session_fetch(url, timeout=max(timeout, 30))
                if content and len(content) > 120:
                    return ExtractionResult(
                        status="ok",
                        content=content[:8000],
                        content_length=len(content),
                        source_type=source_type,
                        video_evidence=VideoEvidence(
                            caption_status="ok",
                            caption_text=content[:2000],
                            caption_transcript_status="not_attempted",
                            visual_analysis_status="available",
                            visual_analysis_summary=content[:2000],
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass  # camofox unavailable / not logged in → legacy tiers below

        # Primary: self-hosted scrapers (internal API for IG, tiktok-scraper for TT)
        try:
            if source_type == "instagram":
                content = _fetch_instagram_api(url, timeout=max(timeout, 15))
            else:
                content = _fetch_tiktok_scraper(url, timeout=max(timeout, 30))
            if content and len(content) > 50:
                return ExtractionResult(
                    status="ok",
                    content=content[:8000],
                    content_length=len(content),
                    source_type=source_type,
                    video_evidence=VideoEvidence(
                        caption_status="ok",
                        caption_text=content[:2000],
                        caption_transcript_status="not_attempted",
                        visual_analysis_status="available",
                        visual_analysis_summary=content[:2000],
                        metadata_url=url,
                        metadata_title=title,
                    ),
                )
        except Exception:
            pass  # Self-hosted failed → fall through

        # Stealth Chrome: primary browser extraction for Instagram/TikTok.
        cookies = _get_platform_cookies(source_type)
        try:
            content = _fetch_stealth_chrome(url, timeout=timeout, cookies=cookies)
            if content and len(content) > 50 and not _is_platform_shell(source_type, content):
                return ExtractionResult(
                    status="ok",
                    content=content[:8000],
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
            pass

        # Browser-harness: legacy fallback for platforms without stealth Chrome.
        if source_type == "instagram":
            try:
                content = _fetch_browser_harness(url, timeout=timeout)
                if content and len(content) > 50 and not _is_platform_shell(source_type, content):
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
                pass

        return ExtractionResult(
            status="blocked",
            source_type=source_type,
            error_message=(
                f"{source_type} content requires browser/session for full extraction; "
                "stealth Chrome and browser-harness both failed; "
                f"cookies {'available' if cookies else 'not configured'}"
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

    # YouTube: try yt-dlp captions first (primary transcript path), fall
    # back to youtube-transcript-api, then stealth Chrome for page content.
    if source_type == "youtube":
        transcript_attempted = True
        transcript_error = ""
        video_ev = VideoEvidence(
            metadata_url=url,
            metadata_title=title,
            visual_analysis_status="available",
            visual_analysis_summary="Title, snippet, and video URL preserved; call video_analyze() for visual summary.",
        )

        # Primary: yt-dlp auto-generated subtitles
        ytdlp_exc = None
        try:
            content = _fetch_ytdlp_transcript(url, timeout=timeout)
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
            ytdlp_exc = exc
            transcript_error = f"yt-dlp transcript failed: {_exception_summary(exc)}"

        # Fallback 1: youtube-transcript-api (legacy, may be IP-blocked)
        if transcript_error:
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
            except Exception as exc2:
                transcript_error = f"All transcript methods failed: yt-dlp: {_exception_summary(ytdlp_exc or exc2)}, api: {_exception_summary(exc2)}"

        # Fallback 1.5: ASR (Groq Whisper) — covers videos with no captions at
        # all and caption-endpoint windows.  Cached separately (.asr.txt).
        if transcript_error:
            try:
                content = _fetch_youtube_asr(url, timeout=max(timeout, 60))
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
            except Exception as exc_asr:
                transcript_error += f"; asr: {_exception_summary(exc_asr)}"

        # Fallback 2: stealth Chrome for page content + captions
        if transcript_error:
            try:
                content = _fetch_stealth_chrome(url, timeout=timeout)
                if content and len(content) > 50:
                    return ExtractionResult(
                        status="ok",
                        content=content[:8000],
                        content_length=len(content),
                        source_type=source_type,
                        transcript_attempted=True,
                        transcript_error=transcript_error,
                        video_evidence=VideoEvidence(
                            caption_transcript_status="blocked",
                            caption_transcript_error=transcript_error,
                            visual_analysis_status="available",
                            audio_transcript_status="not_configured",
                            metadata_url=url,
                            metadata_title=title,
                        ),
                    )
            except Exception:
                pass

        # Fallback 3: direct page fetch for metadata/title/description
        try:
            content = fetcher(url, timeout)
            if content and len(content) > 50 and not _is_platform_shell(source_type, content):
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

    # Reddit often blocks direct fetches.  The local Redlib instance serves
    # readable thread HTML (post + comments) straight from localhost — try it
    # first, then old.reddit.com through the proxy tiers, before generic fetch.
    shell_seen = False
    if source_type == "reddit":
        if fetch is None:
            try:
                redlib_content = _fetch_redlib(_redlib_thread_url(url), timeout=timeout)
                if _is_usable_page_text(redlib_content):
                    return ExtractionResult(
                        status="ok",
                        content=redlib_content,
                        content_length=len(redlib_content),
                        source_type=source_type,
                    )
            except Exception:
                pass  # Local Redlib not running — fall through to Pushshift successors
            # Pushshift successors (PullPush, Arctic Shift) serve post+comment
            # data to ANY IP — no Reddit-IP dependency, no auth.  The always-on
            # backbone when Redlib's upstream window is shut.
            for _ps_fetch in (_fetch_pullpush, _fetch_arctic_shift):
                try:
                    ps_content = _ps_fetch(url, timeout=max(timeout, 15))
                    if ps_content and len(ps_content) > 200:
                        return ExtractionResult(
                            status="ok",
                            content=ps_content,
                            content_length=len(ps_content),
                            source_type=source_type,
                        )
                except Exception:
                    pass
            # old.reddit: direct first, then every residential route in the
            # pool, taking the first route that returns USABLE content — some
            # routes serve a logged-out shell, which is skipped, not "won".
            try:
                content = _fetch_text(_reddit_frontend_url(url), timeout=timeout)
                if content and _is_usable_page_text(content):
                    return ExtractionResult(
                        status="ok",
                        content=content,
                        content_length=len(content),
                        source_type=source_type,
                    )
                if content and _is_html_shell(content):
                    shell_seen = True
            except Exception:
                pass
            for _round in range(2):
                for proxy in [p for p in _proxy_failover_plan() if p]:
                    content = _fetch_via_route(_reddit_frontend_url(url), proxy, timeout=timeout)
                    if content and _is_usable_page_text(content):
                        return ExtractionResult(
                            status="ok",
                            content=content,
                            content_length=len(content),
                            source_type=source_type,
                        )
                    if content and _is_html_shell(content):
                        shell_seen = True
            # Fall through to generic tiers (direct www, Jina, Hermes extract)
        else:
            try:
                content = fetcher(_reddit_frontend_url(url), timeout)
                if _is_usable_page_text(content):
                    return ExtractionResult(
                        status="ok",
                        content=content,
                        content_length=len(content),
                        source_type=source_type,
                    )
                if _is_html_shell(content):
                    shell_seen = True
            except Exception:
                pass  # Fall through to Hermes/Jina/direct fetch

    # Try direct fetch first (fast, no subprocess).
    try:
        content = fetcher(url, timeout)
        if _is_usable_page_text(content):
            return ExtractionResult(
                status="ok",
                content=content,
                content_length=len(content),
                source_type=source_type,
            )
        if _is_html_shell(content):
            shell_seen = True
    except Exception:
        pass  # Fall through to Jina

    # Try Jina Reader for markdown.
    if fetch is None:  # Only try Jina when not testing
        try:
            content = _fetch_jina(url, timeout=timeout)
            if _is_usable_page_text(content):
                return ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content),
                    source_type=source_type,
                )
            if _is_html_shell(content):
                shell_seen = True
        except Exception:
            pass

    # Try Hermes native web_extract last (slow subprocess).
    try:
        content = (extract or _fetch_hermes_web_extract)(url, timeout)
        if _is_usable_page_text(content):
            return ExtractionResult(
                status="ok",
                content=content,
                content_length=len(content),
                source_type=source_type,
            )
        if _is_html_shell(content):
            shell_seen = True
    except Exception:
        pass  # Fall through to error

    if shell_seen:
        return ExtractionResult(
            status="blocked",
            source_type=source_type,
            error_message=(
                f"Fetched {source_type} HTML is a client-rendered app shell with no "
                "readable source text; requires browser extraction."
            ),
        )

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
