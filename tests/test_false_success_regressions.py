"""Regression tests for false-success extraction / evidence-scoring defects.

These encode the audited failures observed on live probes:

1. The extractor's own failure narration ("Extraction failed: web_extract is
   configured to use ...") was reported as a successful extraction.
2. A client-rendered HTML/JS shell (e.g. new Reddit) was accepted as readable
   content and scored as a practitioner source.
3. A requested GitHub release/blob page returned only repository metadata
   (stars/forks) instead of the release notes / file body that was asked for.
4. A media caption/description was reported as a successful transcript.
"""
import json

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    ExtractedHit,
    ExtractionResult,
    VideoEvidence,
    _fetch_github_summary,
    _fetch_hermes_web_extract,
    _is_html_shell,
    _is_usable_page_text,
    _looks_like_extraction_error,
    extract_one,
)
from hermes_trailhead.scoring import ScoredHit, SourceQuality, score_hit


# ── 1. Extraction-error text is not a successful extraction ─────────────

WEB_EXTRACT_ERROR = (
    'Extraction failed: web_extract is configured to use \u201ctavily,\u201d '
    'but no registered web extract provider has that name.'
)


def test_looks_like_extraction_error_detects_narration():
    assert _looks_like_extraction_error(WEB_EXTRACT_ERROR) is True
    assert _looks_like_extraction_error("Real article content about agents.") is False
    assert _looks_like_extraction_error("") is False


def test_usable_page_text_rejects_extraction_error():
    assert _is_usable_page_text(WEB_EXTRACT_ERROR) is False


def test_fetch_hermes_web_extract_raises_on_error_narration(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = WEB_EXTRACT_ERROR
        stderr = ""

    monkeypatch.setattr(extract_mod.subprocess, "run", lambda *a, **k: FakeProc())

    raised = False
    try:
        _fetch_hermes_web_extract("https://www.reddit.com/r/x/comments/1/y/")
    except RuntimeError as exc:
        raised = True
        assert "reported failure" in str(exc)
    assert raised, "extraction-error narration must not be returned as content"


def test_extract_one_error_narration_is_not_ok(monkeypatch):
    # web_extract is the last-resort path and relays the error narration.
    class FakeProc:
        returncode = 0
        stdout = WEB_EXTRACT_ERROR
        stderr = ""

    monkeypatch.setattr(extract_mod.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr(extract_mod, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(OSError("no jina")))

    def failing_fetch(url, timeout):
        raise OSError("Connection refused")

    result = extract_one("https://www.reddit.com/r/HermesDefi/comments/segyz6/x/", fetch=failing_fetch, timeout=1)
    assert result.status == "error"
    assert result.content == ""
    assert not result.usable


def test_scoring_error_text_summary_is_not_practitioner():
    # Even if a caller hands scoring an "ok" result whose text is the extractor's
    # error message, it must not inherit the Reddit domain's practitioner quality.
    eh = ExtractedHit(
        title="The NEW Official Roadmap",
        url="https://www.reddit.com/r/HermesDefi/comments/segyz6/x/",
        snippet="",
        extraction=ExtractionResult(status="ok", content=WEB_EXTRACT_ERROR,
                                    content_length=len(WEB_EXTRACT_ERROR), source_type="reddit"),
    )
    scored = score_hit(ScoredHit.from_extracted_hit(eh))
    assert scored.scoring.quality == SourceQuality.PLATFORM_SHELL
    assert scored.scoring.score == 0


# ── 2. Client-rendered HTML shells are not readable evidence ────────────

REDDIT_SHELL = (
    'Welcome to Reddit <script type="module" nonce="abc" '
    'src="data:text/javascript,let%20navPromise%3Dnull"></script>'
    '<div id="shreddit-app">app shell</div>' + " nav " * 400
)

REAL_HTML = (
    "<html><body><article>" + " ".join(f"distinctword{i}" for i in range(80)) + "</article></body></html>"
)


def test_is_html_shell_flags_reddit_shell():
    assert _is_html_shell(REDDIT_SHELL) is True


def test_is_html_shell_does_not_flag_real_prose():
    assert _is_html_shell(REAL_HTML) is False
    assert _is_html_shell("Plain text article with enough distinct readable words " * 5) is False


def test_extract_one_reddit_shell_is_blocked_not_ok(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda *a, **k: (_ for _ in ()).throw(OSError("no web_extract")))

    result = extract_one(
        "https://www.reddit.com/r/hermesagent/comments/1t4efcb/x/",
        fetch=lambda url, timeout: REDDIT_SHELL,
        timeout=1,
    )
    assert result.status == "blocked"
    assert result.content == ""
    assert not result.usable
    assert "shell" in result.error_message.lower()


def test_scoring_blocked_shell_is_platform_shell():
    eh = ExtractedHit(
        title="Reddit",
        url="https://www.reddit.com/r/hermesagent/comments/1t4efcb/x/",
        snippet="",
        extraction=ExtractionResult(status="blocked", content="", content_length=0, source_type="reddit"),
    )
    scored = score_hit(ScoredHit.from_extracted_hit(eh))
    assert scored.scoring.quality == SourceQuality.PLATFORM_SHELL
    assert scored.scoring.score == 0


# ── 3. GitHub requested release/page evidence ──────────────────────────

class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


RELEASE_JSON = json.dumps([
    {
        "tag_name": "v0.21.6",
        "name": "Hermes Agent v0.21.6",
        "published_at": "2026-10-08T00:00:00Z",
        "body": "Patch release rolling up ~2,100 PRs since v0.21.5. Security fix groups included.",
    },
    {
        "tag_name": "v0.21.5",
        "name": "Hermes Agent v0.21.5",
        "published_at": "2026-09-24T00:00:00Z",
        "body": "460 merged PRs rolled into a stable tag.",
    },
])

REPO_JSON = json.dumps({
    "full_name": "NousResearch/hermes-agent",
    "description": "The agent that grows with you",
    "homepage": "https://hermes-agent.nousresearch.com",
    "stargazers_count": 252813,
    "forks_count": 54746,
    "open_issues_count": 48013,
    "language": "Python",
})


def test_github_release_url_yields_release_body_not_metadata(monkeypatch):
    def fake_urlopen(req, timeout=15):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/releases" in url:
            return _FakeResp(RELEASE_JSON.encode())
        return _FakeResp(REPO_JSON.encode())

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", fake_urlopen)

    content = _fetch_github_summary("https://github.com/NousResearch/hermes-agent/releases")
    assert "Release v0.21.6" in content
    assert "Patch release rolling up" in content
    assert "Release v0.21.5" in content
    # Must not be the repository stats page.
    assert "Stars:" not in content


def test_github_blob_url_yields_file_content(monkeypatch):
    file_body = b"# Kanban Skill\n\nMulti-agent workflow instructions for Hermes Kanban."

    def fake_urlopen(req, timeout=15):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "raw.githubusercontent.com" in url
        return _FakeResp(file_body)

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", fake_urlopen)

    content = _fetch_github_summary("https://github.com/angelife/hermes-skills/blob/main/kanban/SKILL.md")
    assert "Multi-agent workflow instructions" in content
    assert "GitHub file angelife/hermes-skills/main/kanban/SKILL.md" in content


def test_github_release_without_releases_raises_not_metadata(monkeypatch):
    def fake_urlopen(req, timeout=15):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/releases" in url:
            return _FakeResp(b"[]")
        return _FakeResp(REPO_JSON.encode())

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", fake_urlopen)

    raised = False
    try:
        _fetch_github_summary("https://github.com/NousResearch/hermes-agent/releases")
    except RuntimeError:
        raised = True
    assert raised, "an empty releases API must not fall back to repo metadata as release evidence"


def test_github_repo_root_still_returns_metadata(monkeypatch):
    def fake_urlopen(req, timeout=15):
        return _FakeResp(REPO_JSON.encode())

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", fake_urlopen)

    content = _fetch_github_summary("https://github.com/NousResearch/hermes-agent")
    assert "GitHub repository: NousResearch/hermes-agent" in content


# ── 4. Media captions are not transcripts ──────────────────────────────

def test_tiktok_caption_is_not_reported_as_transcript(monkeypatch):
    oembed = json.dumps({
        "title": "Cool video with enough caption text to count as a useful TikTok summary.",
        "author_name": "user",
    })
    monkeypatch.setattr(extract_mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no subprocess")))

    result = extract_one("https://www.tiktok.com/@user/video/123", fetch=lambda u, timeout=0: oembed)
    assert result.status == "ok"
    ve = result.video_evidence
    assert ve is not None
    assert ve.caption_status == "ok"
    assert ve.caption_transcript_status == "not_attempted"

    d = ve.to_dict()
    assert "caption_status" in d and "caption_text" in d
    assert d["caption_status"] == "ok"
    assert d["caption_transcript_status"] == "not_attempted"


def test_scored_tiktok_caption_top_level_transcript_is_honest():
    ve = VideoEvidence(
        caption_status="ok",
        caption_text="TikTok by @user: caption only",
        caption_transcript_status="not_attempted",
        audio_transcript_status="not_configured",
    )
    eh = ExtractedHit(
        title="TikTok",
        url="https://www.tiktok.com/@user/video/123",
        snippet="caption only",
        extraction=ExtractionResult(status="ok", content="TikTok by @user: caption only",
                                    content_length=32, source_type="tiktok", video_evidence=ve),
    )
    d = score_hit(ScoredHit.from_extracted_hit(eh)).to_dict()
    assert d["transcript_status"] != "ok"
    assert d["transcript_status"] == "not_attempted"
    assert d["video_evidence"]["caption_status"] == "ok"


def test_youtube_transcript_still_reports_ok(monkeypatch):
    monkeypatch.setattr(
        extract_mod, "_fetch_ytdlp_transcript",
        lambda url, timeout: "YouTube auto-captions for abc123\n\nreal spoken transcript content here",
    )
    result = extract_one("https://www.youtube.com/watch?v=abc123")
    assert result.status == "ok"
    ve = result.video_evidence
    assert ve is not None
    assert ve.caption_transcript_status == "ok"
    assert score_hit(ScoredHit.from_extracted_hit(
        ExtractedHit(title="v", url="https://www.youtube.com/watch?v=abc123", snippet="",
                     extraction=result)
    )).to_dict()["transcript_status"] == "ok"
