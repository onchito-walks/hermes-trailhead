import json

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.search import SearchHit
from hermes_trailhead.extract import (
    ExtractionResult,
    ExtractedHit,
    _classify_source_type,
    _reddit_frontend_url,
    _youtube_video_id,
    extract_one,
    extract_hits,
)


def test_classify_source_type_github():
    assert _classify_source_type("https://github.com/NousResearch/hermes-agent/issues/42") == "github"


def test_classify_source_type_reddit():
    assert _classify_source_type("https://www.reddit.com/r/hermesagent/comments/abc123/") == "reddit"


def test_classify_source_type_x():
    assert _classify_source_type("https://x.com/nousresearch/status/123") == "x"


def test_classify_source_type_tiktok():
    assert _classify_source_type("https://www.tiktok.com/@user/video/123") == "tiktok"


def test_classify_source_type_youtube():
    assert _classify_source_type("https://www.youtube.com/watch?v=abc123") == "youtube"


def test_youtube_video_id_parses_common_url_shapes():
    assert _youtube_video_id("https://www.youtube.com/watch?v=abc123&t=10") == "abc123"
    assert _youtube_video_id("https://youtu.be/def456") == "def456"
    assert _youtube_video_id("https://www.youtube.com/shorts/ghi789") == "ghi789"
    assert _youtube_video_id("https://www.youtube.com/embed/jkl012") == "jkl012"


def test_youtube_extraction_uses_transcript_before_page_fetch(monkeypatch):
    monkeypatch.setattr(
        extract_mod,
        "_fetch_youtube_transcript",
        lambda url, timeout: "YouTube transcript for abc123\n\n[0.0s] first line\n[2.0s] second line",
    )

    def fake_fetch(url, timeout):
        raise AssertionError("page fetch should not be used when transcript succeeds")

    result = extract_one("https://www.youtube.com/watch?v=abc123", fetch=fake_fetch)
    assert result.status == "ok"
    assert result.source_type == "youtube"
    assert "transcript" in result.content.lower()


def test_classify_source_type_docs():
    assert _classify_source_type("https://docs.hermes-agent.nousresearch.com/config") == "docs"


def test_classify_source_type_forum():
    assert _classify_source_type("https://stackoverflow.com/questions/123") == "forum"


def test_classify_source_type_generic():
    assert _classify_source_type("https://example.com/blog/post") == "web"


def test_classify_source_type_pdf():
    assert _classify_source_type("https://example.com/report.pdf") == "pdf"


def test_tiktok_oembed_extraction_works_with_content():
    """TikTok now extracts via oEmbed when JSON content is available."""
    import json as _json
    oembed_data = _json.dumps({"title": "Cool video with enough caption text to count as a useful TikTok summary for research.", "author_name": "user"})
    result = extract_one("https://www.tiktok.com/@user/video/123", fetch=lambda u, t: oembed_data)
    assert result.status == "ok"
    assert result.source_type == "tiktok"


def test_instagram_source_type_is_preserved():
    # Instagram extraction now uses browser‑harness; may succeed on real machines.
    # The invariant is correct source_type classification.
    result = extract_one("https://www.instagram.com/p/abc123/")
    assert result.source_type == "instagram"


def test_extraction_success(monkeypatch):
    def fake_web_extract(url, timeout):
        return "This is real content from a web page. " * 10

    def fake_fetch(url, timeout):
        raise AssertionError("direct fetch should not be used when web_extract succeeds")

    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", fake_web_extract)
    result = extract_one("https://example.com/article", fetch=fake_fetch)
    assert result.status == "ok"
    assert result.content_length > 100
    assert result.source_type == "web"
    assert result.usable is True


def test_extraction_direct_fetch_is_fallback(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: (_ for _ in ()).throw(OSError("web_extract unavailable")))

    def fake_fetch(url, timeout):
        return "This is real content from a web page. " * 10

    result = extract_one("https://example.com/article", fetch=fake_fetch)
    assert result.status == "ok"
    assert result.content_length > 100
    assert result.source_type == "web"
    assert result.usable is True


def test_extraction_too_short_is_not_usable(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: "short")

    def fake_fetch(url, timeout):
        return "short"

    result = extract_one("https://example.com/empty", fetch=fake_fetch)
    assert result.status == "error"
    assert not result.usable


def test_extraction_network_error_falls_to_error(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: (_ for _ in ()).throw(OSError("web_extract failed")))

    def fake_fetch(url, timeout):
        raise OSError("Connection refused")

    result = extract_one("https://example.com/dead", fetch=fake_fetch)
    assert result.status == "error"
    assert "Could not extract" in result.error_message


def test_reddit_extraction_network_error_reports_reddit_source_type(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: (_ for _ in ()).throw(OSError("web_extract failed")))

    def fake_fetch(url, timeout):
        raise OSError("Connection refused")

    result = extract_one("https://www.reddit.com/r/VORONDesign/comments/abc123/", fetch=fake_fetch)
    assert result.status == "error"
    assert result.source_type == "reddit"
    assert not result.usable


def test_reddit_extraction_uses_redlib_frontend_before_generic_extract(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: (_ for _ in ()).throw(AssertionError("generic extract should not run")))

    seen = []

    def fake_fetch(url, timeout):
        seen.append(url)
        return "Redlib thread content about StealthChanger build. " * 5

    result = extract_one("https://www.reddit.com/r/VORONDesign/comments/abc123/title/", fetch=fake_fetch)
    assert result.status == "ok"
    assert result.source_type == "reddit"
    assert seen == ["https://redlib.perennialte.ch/r/VORONDesign/comments/abc123/title/"]


def test_reddit_frontend_url_preserves_path():
    assert _reddit_frontend_url("https://www.reddit.com/r/VORONDesign/comments/abc123/title/") == "https://redlib.perennialte.ch/r/VORONDesign/comments/abc123/title/"


def test_extraction_result_to_dict():
    result = ExtractionResult(status="ok", content="hello world", content_length=11, source_type="web")
    d = result.to_dict()
    assert d["status"] == "ok"
    assert d["content_length"] == 11
    assert d["source_type"] == "web"


def test_extracted_hit_from_search_hit():
    hit = SearchHit(title="Test", url="https://example.com", snippet="A test")
    eh = ExtractedHit.from_search_hit(hit)
    assert eh.title == "Test"
    assert eh.url == "https://example.com"
    assert eh.extraction.status == "not_attempted"


def test_extracted_hit_to_dict():
    eh = ExtractedHit(
        title="Test",
        url="https://example.com",
        snippet="Snippet",
        extraction=ExtractionResult(status="ok", content="hello", content_length=5, source_type="web"),
    )
    d = eh.to_dict()
    assert set(d) == {"title", "url", "snippet", "extraction"}
    assert d["extraction"]["status"] == "ok"


def test_extract_hits_respects_limit():
    def fake_fetch(url, timeout):
        return "Real content from a webpage that is long enough to pass. " * 5

    hits = tuple(
        SearchHit(title=f"Hit {i}", url=f"https://example.com/{i}", snippet=f"Snippet {i}")
        for i in range(10)
    )
    results = extract_hits(hits, limit=3, fetch=fake_fetch)
    assert len(results) == 3


def test_extract_hits_can_handle_higher_limits():
    def fake_fetch(url, timeout):
        return "Real content from a webpage that is long enough to pass. " * 5

    hits = tuple(
        SearchHit(title=f"Hit {i}", url=f"https://example.com/{i}", snippet=f"Snippet {i}")
        for i in range(10)
    )
    results = extract_hits(hits, limit=5, fetch=fake_fetch)
    assert len(results) == 5


def test_extract_hits_empty_input():
    results = extract_hits((), limit=5)
    assert len(results) == 0


def test_instagram_login_shell_is_blocked_not_summary(monkeypatch):
    from hermes_trailhead import extract as extract_mod

    monkeypatch.setattr(extract_mod, "_fetch_instagram_api", lambda url, timeout: (_ for _ in ()).throw(RuntimeError("oEmbed failed")))
    monkeypatch.setattr(extract_mod, "_fetch_stealth_chrome", lambda *a, **k: "InstagramLog inerrorPost isn't availableThe link may be broken, or the profile may have been removed.Sign up for Instagram")
    monkeypatch.setattr(extract_mod, "_fetch_browser_harness", lambda *a, **k: "This page isn’t working HTTP ERROR 429")

    result = extract_mod.extract_one("https://www.instagram.com/reel/DQj40znkasX/", timeout=1)

    assert result.status == "blocked"
    assert result.source_type == "instagram"
    assert result.content == ""
    assert result.video_evidence is not None
    assert result.video_evidence.caption_transcript_status == "not_available"


def test_github_repo_summary_extraction(monkeypatch):
    import json
    from hermes_trailhead import extract as extract_mod

    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({
                "full_name": "owner/repo",
                "description": "Useful repo description.",
                "homepage": "https://example.com",
                "stargazers_count": 123,
                "forks_count": 4,
                "open_issues_count": 5,
                "language": "Python",
            }).encode()

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())

    result = extract_mod.extract_one("https://github.com/owner/repo/wiki", timeout=1)

    assert result.status == "ok"
    assert result.source_type == "github"
    assert "GitHub repository: owner/repo" in result.content
    assert "Useful repo description." in result.content
    assert "Requested path: /wiki" in result.content
