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


def test_tiktok_oembed_extraction_works_with_content(monkeypatch):
    """TikTok now extracts via oEmbed when JSON content is available."""
    import json as _json
    oembed_data = _json.dumps({"title": "Cool video with enough caption text to count as a useful TikTok summary for research.", "author_name": "user"})

    # Block subprocess so tiktok-scraper fallback doesn't run real binaries in test
    monkeypatch.setattr(extract_mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked in test")))

    result = extract_one("https://www.tiktok.com/@user/video/123", fetch=lambda u, timeout=0: oembed_data)
    assert result.status == "ok"
    assert result.source_type == "tiktok"


def test_instagram_source_type_is_preserved(monkeypatch):
    # Instagram extraction now uses browser‑harness; may succeed on real machines.
    # The invariant is correct source_type classification.
    import hermes_trailhead.extract as extract_mod

    # Keep the test hermetic: the embed tier is the first live attempt since
    # 2026-10-14; disable it so the test does not depend on Instagram network.
    monkeypatch.setattr(
        extract_mod,
        "_fetch_instagram_embed",
        lambda url, timeout=20: (_ for _ in ()).throw(RuntimeError("embed disabled in test")),
    )
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


def test_reddit_extraction_uses_old_reddit_frontend_before_generic_extract(monkeypatch):
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", lambda url, timeout: (_ for _ in ()).throw(AssertionError("generic extract should not run")))

    seen = []

    def fake_fetch(url, timeout):
        seen.append(url)
        return "old.reddit thread content about StealthChanger build. " * 5

    result = extract_one("https://www.reddit.com/r/VORONDesign/comments/abc123/title/", fetch=fake_fetch)
    assert result.status == "ok"
    assert result.source_type == "reddit"
    assert seen == ["https://old.reddit.com/r/VORONDesign/comments/abc123/title/"]


def test_reddit_extraction_uses_local_redlib_first(monkeypatch):
    from hermes_trailhead import extract as extract_mod

    seen = []

    def fake_redlib(url, timeout=15):
        seen.append(url)
        return "<html><body>" + ("Local Redlib thread content about StealthChanger build. " * 5) + "</body></html>"

    monkeypatch.setattr(extract_mod, "_fetch_redlib", fake_redlib)

    result = extract_mod.extract_one("https://www.reddit.com/r/VORONDesign/comments/abc123/title/")

    assert result.status == "ok"
    assert result.source_type == "reddit"
    assert seen == ["http://127.0.0.1:8789/r/VORONDesign/comments/abc123/title/"]


def test_redlib_thread_url_maps_reddit_paths():
    from hermes_trailhead.extract import _redlib_thread_url

    assert _redlib_thread_url("https://www.reddit.com/r/VORONDesign/comments/abc123/title/") == "http://127.0.0.1:8789/r/VORONDesign/comments/abc123/title/"
    assert _redlib_thread_url("https://example.com/x") == "https://example.com/x"


def test_reddit_extraction_skips_shell_routes_and_uses_usable_route(monkeypatch):
    """Routes that serve a logged-out shell must not win; the first route
    with usable content is used."""
    import hermes_trailhead.extract as extract_mod

    def dead_redlib(url, timeout=15):
        raise RuntimeError("redlib down")

    def dead_direct(url, timeout=15):
        raise RuntimeError("403 blocked")

    def fake_route(url, proxy, timeout=15, *, opener_factory=None):
        assert "old.reddit.com" in url
        if proxy == "http://shell.example:1":
            return "<html><body>" + ("reddit home popular login signup " * 400) + "</body></html>"
        usable = " ".join(f"word{i} content{i} detail{i}" for i in range(60))
        return f"<html><body>{usable}</body></html>"

    monkeypatch.setattr(extract_mod, "_fetch_redlib", dead_redlib)
    monkeypatch.setattr(extract_mod, "_fetch_text", dead_direct)
    # Pushshift-successor tiers sit between redlib and the route pool in the
    # live chain; disable them here so this test exercises the route-pool path.
    monkeypatch.setattr(extract_mod, "_fetch_pullpush", dead_redlib)
    monkeypatch.setattr(extract_mod, "_fetch_arctic_shift", dead_redlib)
    monkeypatch.setattr(extract_mod, "_proxy_failover_plan", lambda: ["http://shell.example:1", "http://good.example:1"])
    monkeypatch.setattr(extract_mod, "_fetch_via_route", fake_route)

    result = extract_mod.extract_one("https://www.reddit.com/r/LocalLLaMA/comments/abc123/title/")

    assert result.status == "ok"
    assert "word59 content59 detail59" in result.content


def test_reddit_thread_id_parsing():
    from hermes_trailhead.extract import _reddit_thread_id

    assert (
        _reddit_thread_id(
            "https://www.reddit.com/r/3Dprinting/comments/16eakw2/affordable_and_simple_5axis_mod_my_master_thesis/"
        )
        == "16eakw2"
    )
    assert _reddit_thread_id("https://old.reddit.com/r/x/comments/z1qsnz/slug/") == "z1qsnz"
    assert _reddit_thread_id("https://example.com/x") == ""


def test_reddit_extraction_falls_back_to_pullpush_when_redlib_down(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def dead_redlib(url, timeout=15):
        raise RuntimeError("redlib throttled")

    monkeypatch.setattr(extract_mod, "_fetch_redlib", dead_redlib)
    monkeypatch.setattr(
        extract_mod, "_fetch_pullpush", lambda url, timeout=20: "PullPush thread body. " * 20
    )

    result = extract_mod.extract_one(
        "https://www.reddit.com/r/3Dprinting/comments/16eakw2/affordable_simple_5axis_mod/"
    )
    assert result.status == "ok"
    assert "PullPush thread body" in result.content


def test_reddit_extraction_falls_back_to_arctic_when_pullpush_fails(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def dead_redlib(url, timeout=15):
        raise RuntimeError("redlib throttled")

    def dead_pullpush(url, timeout=20):
        raise RuntimeError("pullpush down")

    monkeypatch.setattr(extract_mod, "_fetch_redlib", dead_redlib)
    monkeypatch.setattr(extract_mod, "_fetch_pullpush", dead_pullpush)
    monkeypatch.setattr(
        extract_mod, "_fetch_arctic_shift", lambda url, timeout=20: "Arctic Shift thread body. " * 20
    )

    result = extract_mod.extract_one(
        "https://www.reddit.com/r/3Dprinting/comments/16eakw2/affordable_simple_5axis_mod/"
    )
    assert result.status == "ok"
    assert "Arctic Shift thread body" in result.content


def test_fetch_pullpush_composes_ranked_thread_text(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def fake_http_json(url, timeout=15):
        if "submission" in url:
            return {
                "data": [
                    {
                        "title": "Affordable and simple 5-axis mod",
                        "subreddit_name_prefixed": "r/3Dprinting",
                        "author": "andersonsjanis",
                        "score": 412,
                        "num_comments": 2,
                        "selftext": "My master thesis about a 5-axis mod.",
                    }
                ]
            }
        return {
            "data": [
                {"body": "low score comment", "score": 3, "author": "a"},
                {"body": "top comment about kinematics", "score": 99, "author": "b"},
                {"body": "[deleted]", "score": 50, "author": "c"},
            ]
        }

    monkeypatch.setattr(extract_mod, "_http_json", fake_http_json)
    text = extract_mod._fetch_pullpush(
        "https://www.reddit.com/r/3Dprinting/comments/16eakw2/affordable_simple_5axis_mod/"
    )
    assert "Affordable and simple 5-axis mod" in text
    assert "top comment about kinematics" in text
    assert "[deleted]" not in text
    assert text.index("top comment about kinematics") < text.index("low score comment")


def test_fetch_fxtwitter_composes_tweet_text(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def fake_http_json(url, timeout=15):
        assert url == "https://api.fxtwitter.com/status/2096236913044636091"
        return {
            "tweet": {
                "text": "5-axis 3D printing is pushing additive manufacturing beyond limits.",
                "author": {"screen_name": "ctorobotics"},
                "created_at": "Wed Oct 01 12:00:00 +0000 2026",
                "likes": 234,
                "retweets": 34,
                "replies": 4,
                "views": 12000,
                "media": {"photos": [{}], "videos": []},
            }
        }

    monkeypatch.setattr(extract_mod, "_http_json", fake_http_json)
    out = extract_mod._fetch_fxtwitter("https://x.com/ctorobotics/status/2096236913044636091")
    assert "Tweet by @ctorobotics" in out
    assert "5-axis 3D printing" in out
    assert "234 likes" in out
    assert "1 photo(s)" in out


def test_fetch_nitter_extracts_tweet_and_replies(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    html = (
        '<div class="tweet-content media-body">Great 5-axis build here</div>'
        '<div class="tweet-content media-body">First reply about kinematics</div>'
    )

    def fake_fetch_text(url, timeout=15):
        assert url == "http://127.0.0.1:8788/ctorobotics/status/2096236913044636091"
        return html

    monkeypatch.setattr(extract_mod, "_fetch_text", fake_fetch_text)
    out = extract_mod._fetch_nitter("https://x.com/ctorobotics/status/2096236913044636091")
    assert "X post by @ctorobotics" in out
    assert "Great 5-axis build here" in out
    assert "Replies:" in out
    assert "First reply about kinematics" in out


def test_fetch_tikwm_composes_metadata(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def fake_http_json(url, timeout=15):
        if "comment/list" in url:
            return {
                "code": 0,
                "data": {
                    "comments": [
                        {"text": "what are the benefits vs normal printing?", "digg_count": 14},
                        {"text": "minor question about tolerances", "digg_count": 2},
                    ]
                },
            }
        assert url.startswith("https://www.tikwm.com/api/?url=")
        return {
            "code": 0,
            "data": {
                "title": "Proof of non-planar 5-axis printing in action",
                "author": {"unique_id": "3dprintingdoctor"},
                "play_count": 118810,
                "digg_count": 3258,
                "comment_count": 123,
                "share_count": 45,
                "collect_count": 67,
                "music_info": {"title": "original sound - 3dprintingdoctor"},
                "duration": 37,
            },
        }

    monkeypatch.setattr(extract_mod, "_http_json", fake_http_json)
    out = extract_mod._fetch_tikwm(
        "https://www.tiktok.com/@3dprintingdoctor/video/7665567402905685261"
    )
    assert "TikTok by @3dprintingdoctor" in out
    assert "plays: 118810" in out
    assert "likes: 3258" in out
    assert "Duration: 37s" in out
    assert "Top comments (2):" in out
    assert "benefits vs normal printing" in out
    assert out.index("benefits vs normal printing") < out.index("minor question")  # score-ranked


def test_fetch_instagram_embed_maps_url_and_parses(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    captured = {}

    def fake_http_text(url, timeout=15, headers=None):
        captured["url"] = url
        return (
            '<div class="Caption">'
            '<a class="CaptionUsername" href="https://www.instagram.com/3dmartes/">3dmartes</a>'
            " 5-Axis 3D Printer made by Philip. This custom printer &amp; build.&#064;koaladeen"
            "</div>"
            '<div class="SocialProof">1,234 likes</div>'
        )

    monkeypatch.setattr(extract_mod, "_http_text", fake_http_text)
    out = extract_mod._fetch_instagram_embed("https://www.instagram.com/reel/DeFDW0wKa-3/")
    assert captured["url"].startswith(
        "https://www.instagram.com/reel/DeFDW0wKa-3/embed/captioned/"
    )
    assert "Instagram reel by @3dmartes" in out
    assert "5-Axis 3D Printer made by Philip" in out
    assert "@koaladeen" in out  # &#064; unescaped
    assert "1,234 likes" in out


def test_ytdlp_transcript_cache_hit(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)
    cache_dir = tmp_path / "hermes" / "state" / "trailhead-transcripts"
    cache_dir.mkdir(parents=True)
    (cache_dir / "abc123XYZ.txt").write_text(
        "YouTube auto-captions for abc123XYZ\n\ncached transcript content here"
    )

    def explode(*a, **k):
        raise AssertionError("subprocess.run must not run on cache hit")

    monkeypatch.setattr(extract_mod.subprocess, "run", explode)
    out = extract_mod._fetch_ytdlp_transcript(
        "https://www.youtube.com/watch?v=abc123XYZ", timeout=10
    )
    assert "cached transcript content here" in out


def test_github_repo_metadata_includes_readme_excerpt(monkeypatch):
    import base64

    import hermes_trailhead.extract as extract_mod

    def fake_json(api, timeout=15):
        if api.endswith("/readme"):
            content = base64.b64encode(
                b"# Open5x\nThis is a Github repository for 5-axis 3D printing"
            ).decode()
            return {"content": content}
        return {
            "full_name": "FreddieHong19/Open5x",
            "description": "5-axis 3D printing",
            "homepage": "",
            "stargazers_count": 1194,
            "forks_count": 178,
            "open_issues_count": 21,
            "language": "Python",
        }

    monkeypatch.setattr(extract_mod, "_github_api_json", fake_json)
    out = extract_mod._github_repo_metadata("FreddieHong19", "Open5x", ["FreddieHong19", "Open5x"], 10)
    assert "README excerpt" in out
    assert "5-axis 3D printing" in out


def test_groq_multipart_structure():
    from hermes_trailhead.extract import _groq_multipart

    body, content_type = _groq_multipart("a.m4a", b"AUDIOBYTES")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1].encode()
    assert b"--" + boundary in body
    assert b'name="model"' in body and b"whisper-large-v3-turbo" in body
    assert b"AUDIOBYTES" in body
    assert body.rstrip().endswith(b"--")


def test_fetch_youtube_asr_requires_groq_key(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(extract_mod, "resolve_hermes_home", lambda home=None: tmp_path)

    try:
        extract_mod._fetch_youtube_asr("https://www.youtube.com/watch?v=abc123XYZ")
        raise AssertionError("expected RuntimeError for missing key")
    except RuntimeError as exc:
        assert "GROQ_API_KEY" in str(exc)


def test_fetch_youtube_asr_downloads_transcribes_and_caches(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(extract_mod, "_proxy_failover_plan", lambda: [None])

    calls = {}

    class FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        out = cmd[cmd.index("-o") + 1].replace("%(ext)s", "m4a")
        with open(out, "wb") as f:
            f.write(b"fake-audio-bytes")
        calls["cmd"] = cmd
        return FakeProc()

    def fake_transcribe(path, key, timeout=150):
        calls["key"] = key
        return "This is the ASR transcript of the video with plenty of words. " * 3

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(extract_mod, "_transcribe_audio_groq", fake_transcribe)

    out = extract_mod._fetch_youtube_asr("https://www.youtube.com/watch?v=abc123XYZ")
    assert "YouTube ASR transcript for abc123XYZ" in out
    assert calls["key"] == "test-key"
    cache = tmp_path / "hermes" / "state" / "trailhead-transcripts" / "abc123XYZ.asr.txt"
    assert cache.exists()

    def explode(*a, **k):
        raise AssertionError("no download on cache hit")

    monkeypatch.setattr(extract_mod.subprocess, "run", explode)
    out2 = extract_mod._fetch_youtube_asr("https://www.youtube.com/watch?v=abc123XYZ")
    assert out2 == out


def test_youtube_extraction_falls_back_to_asr(monkeypatch):
    import hermes_trailhead.extract as extract_mod

    def dead(*a, **k):
        raise RuntimeError("no captions")

    monkeypatch.setattr(extract_mod, "_fetch_ytdlp_transcript", dead)
    monkeypatch.setattr(extract_mod, "_fetch_youtube_transcript", dead)
    monkeypatch.setattr(
        extract_mod,
        "_fetch_youtube_asr",
        lambda url, timeout=30: "YouTube ASR transcript for X\n\n" + "asr words " * 30,
    )
    result = extract_mod.extract_one("https://www.youtube.com/watch?v=abc123XYZ")
    assert result.status == "ok"
    assert "ASR" in result.content


def test_reddit_frontend_url_preserves_path():
    assert _reddit_frontend_url("https://www.reddit.com/r/VORONDesign/comments/abc123/title/") == "https://old.reddit.com/r/VORONDesign/comments/abc123/title/"


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
    # Keep the test hermetic: disable the embed tier (first live attempt since
    # 2026-10-14) so this still exercises the blocked-fallback behavior.
    monkeypatch.setattr(
        extract_mod,
        "_fetch_instagram_embed",
        lambda url, timeout=20: (_ for _ in ()).throw(RuntimeError("embed disabled in test")),
    )
    # Same for the Camofox authenticated-session tier (live browser on this host).
    monkeypatch.setattr(
        extract_mod,
        "_camofox_session_fetch",
        lambda url, timeout=30: (_ for _ in ()).throw(RuntimeError("camofox disabled in test")),
    )

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


# ── Canonical Hermes home resolution (HOME != Hermes home) ─────────────
# Regression: extract.py used raw ~/.hermes expansion, so from the normal
# host shell (HOME=plain login home, canonical home exported as HERMES_HOME) the
# proxy file was looked up under the shell home and YouTube transcript
# extraction ran without the residential proxy (and failed).

def _canonical_env(tmp_path, monkeypatch, proxies="http://proxy.example:8080"):
    """Point HERMES_HOME at a temp canonical Hermes home and HOME at an
    unrelated shell home without any .hermes — the layout of the normal
    host shell that regressed proxy-backed extraction."""
    canonical = tmp_path / "hermes"
    (canonical / "secrets").mkdir(parents=True)
    (canonical / "secrets" / "trailhead-proxy-url.txt").write_text(proxies + "\n")
    shell_home = tmp_path / "shell-home"
    shell_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(canonical))
    monkeypatch.setenv("HOME", str(shell_home))
    monkeypatch.delenv("TRAILHEAD_PROXY_URL", raising=False)
    return canonical


def test_get_proxy_url_resolves_canonical_home_not_shell_home(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)
    assert extract_mod._get_proxy_url() == "http://proxy.example:8080"


def test_proxy_rotation_counter_lives_in_canonical_state_dir(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch, proxies="http://p1\nhttp://p2")
    assert extract_mod._get_proxy_url() == "http://p1"
    assert extract_mod._get_proxy_url() == "http://p2"
    counter = tmp_path / "hermes" / "state" / "trailhead-proxy-round.txt"
    assert counter.read_text().strip() == "2"


def test_fetch_ytdlp_transcript_uses_canonical_proxy(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)

    captured = {}

    class FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path + ".en.srt", "w") as f:
            f.write(
                "1\n00:00:00,000 --> 00:00:02,000\nHello world test\n\n"
                "2\n00:00:02,000 --> 00:00:04,000\nSecond line here\n"
            )
        return FakeProc()

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)
    out = extract_mod._fetch_ytdlp_transcript("https://www.youtube.com/watch?v=abc123XYZ")
    assert "YouTube auto-captions" in out
    cmd = captured["cmd"]
    assert cmd[cmd.index("--proxy") + 1] == "http://proxy.example:8080"


def test_fetch_ytdlp_transcript_fails_over_when_first_proxy_dead(tmp_path, monkeypatch):
    """A dead/expired proxy route (e.g. residential 407) must not block the
    transcript when another enabled proxy still works: yt-dlp tries the
    rotated proxy, then falls back to the remaining enabled proxies."""
    import hermes_trailhead.extract as extract_mod

    canonical = _canonical_env(
        tmp_path, monkeypatch, proxies="http://p1.example:8080\nhttp://p2.example:8080"
    )

    attempts: list[str] = []

    class FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        proxy = cmd[cmd.index("--proxy") + 1] if "--proxy" in cmd else ""
        out_path = cmd[cmd.index("-o") + 1]
        if proxy == "http://p1.example:8080":
            # Simulate a dead route: auth failure, non-zero exit, no SRT.
            attempts.append(proxy.split("//")[1].split("@")[-1])
            return type("Proc", (), {"returncode": 1, "stderr": "ERROR: 407 Proxy Authentication Required"})()
        attempts.append(proxy.split("//")[1].split("@")[-1])
        with open(out_path + ".en.srt", "w") as f:
            f.write(
                "1\n"
                "00:00:00,000 --> 00:00:01,000\n"
                "The proxy failover worked exactly as designed today\n\n"
            )
        return FakeProc()

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)

    out = extract_mod._fetch_ytdlp_transcript("https://www.youtube.com/watch?v=abc123XYZ")
    assert "YouTube auto-captions" in out
    assert "The proxy failover worked" in out
    # Both proxies were tried: rotated first, working one second.
    assert attempts == ["p1.example:8080", "p2.example:8080"]


def test_fetch_ytdlp_transcript_timeout_floor_and_js_runtime(tmp_path, monkeypatch):
    """CLI extract budgets pass ~10s which starves yt-dlp (transcript loads
    exist, route works, call times out -> false 'blocked'). The per-attempt
    timeout must be floored at 30s, and node must be offered as the JS runtime
    for YouTube challenge solving."""
    import hermes_trailhead.extract as extract_mod

    _canonical_env(tmp_path, monkeypatch)

    captured = {}

    class FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path + ".en.srt", "w") as f:
            f.write(
                "1\n00:00:00,000 --> 00:00:02,000\n"
                "Hello from the floored timeout with plenty of content here\n"
            )
        return FakeProc()

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)
    out = extract_mod._fetch_ytdlp_transcript(
        "https://www.youtube.com/watch?v=abc123XYZ", timeout=10
    )
    assert "Hello from the floored timeout" in out
    assert captured["timeout"] >= 30
    if __import__("shutil").which("node"):
        assert "--js-runtimes" in captured["cmd"]


def test_instagram_session_reads_canonical_secrets(tmp_path, monkeypatch):
    import hermes_trailhead.extract as extract_mod

    canonical = _canonical_env(tmp_path, monkeypatch)
    (canonical / "secrets" / "instagram-session.txt").write_text("session-cookie")
    assert extract_mod._get_instagram_session() == "session-cookie"


def test_fetch_proxy_fails_over_across_routes_and_flaky_rounds(monkeypatch):
    """A dead residential route (407) must not kill the proxy tier while
    another enabled proxy still works; per-request 407 flakes are retried."""
    import hermes_trailhead.extract as extract_mod

    monkeypatch.setattr(
        extract_mod,
        "_proxy_failover_plan",
        lambda: ["http://dead.example:1", "http://alive.example:1"],
    )

    calls: list[str | None] = []
    alive_attempts: list[int] = []

    class FakeResp:
        def read(self):
            return b"<html><body>" + b"real proxy content " * 30 + b"</body></html>"

    class FakeOpener:
        def __init__(self, proxy):
            self.proxy = proxy

        def open(self, req, timeout=None):
            calls.append(self.proxy)
            if self.proxy == "http://dead.example:1":
                raise RuntimeError("407 Proxy Authentication Required")
            alive_attempts.append(1)
            if len(alive_attempts) == 1:
                raise RuntimeError("407 transient flake")
            return FakeResp()

    out = extract_mod._fetch_proxy("https://example.com/page", timeout=5, opener_factory=FakeOpener)

    assert "real proxy content" in out
    assert calls[0] == "http://dead.example:1"
    assert calls.count("http://dead.example:1") == 2  # both rounds tried the dead route
    assert len(alive_attempts) == 2  # first flake retried in round 2


def test_fetch_proxy_direct_fallback_without_routes(monkeypatch):
    """No configured proxies: the tier still attempts a direct fetch."""
    import hermes_trailhead.extract as extract_mod

    monkeypatch.setattr(extract_mod, "_proxy_failover_plan", lambda: [None])

    class FakeResp:
        def read(self):
            return b"<html>direct fallback content here</html>" * 12

    class FakeOpener:
        def __init__(self, proxy):
            self.proxy = proxy

        def open(self, req, timeout=None):
            assert self.proxy is None
            return FakeResp()

    out = extract_mod._fetch_proxy("https://example.com/page", timeout=5, opener_factory=FakeOpener)

    assert "direct fallback content" in out
