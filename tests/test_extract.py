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
    monkeypatch.setattr(extract_mod, "_proxy_failover_plan", lambda: ["http://shell.example:1", "http://good.example:1"])
    monkeypatch.setattr(extract_mod, "_fetch_via_route", fake_route)

    result = extract_mod.extract_one("https://www.reddit.com/r/LocalLLaMA/comments/abc123/title/")

    assert result.status == "ok"
    assert "word59 content59 detail59" in result.content


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
# host shell (HOME=<user-home>, canonical home exported as HERMES_HOME) the
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
