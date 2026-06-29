import base64
import subprocess

from hermes_trailhead import backends
from hermes_trailhead.backends import execute_backend_chain, _github_result_url, _youtube_result_url, _x_result_url


def _bing_href(url: str) -> str:
    encoded = base64.b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&u=a1{encoded}&ntb=1"


def test_youtube_result_url_rejects_corporate_navigation_pages():
    assert _youtube_result_url("https://www.youtube.com/watch?v=abc123") is True
    assert _youtube_result_url("https://youtu.be/abc123") is True
    assert _youtube_result_url("https://www.youtube.com/shorts/abc123") is True
    assert _youtube_result_url("https://www.youtube.com/@creator") is True
    assert _youtube_result_url("https://www.youtube.com/about/") is False
    assert _youtube_result_url("https://www.youtube.com/about/press/") is False
    assert _youtube_result_url("https://www.youtube.com/about/copyright/") is False


def test_x_result_url_rejects_navigation_and_accepts_real_posts():
    assert _x_result_url("https://x.com/nousresearch/status/123") is True
    assert _x_result_url("https://twitter.com/nousresearch/status/123") is True
    assert _x_result_url("https://x.com/nousresearch") is True
    assert _x_result_url("https://x.com/explore") is False
    assert _x_result_url("https://x.com/search?q=hermes") is False
    assert _x_result_url("https://x.com/home") is False


def test_x_backend_filters_search_and_profile_noise_and_returns_status_results():
    def fake_fetch(url, timeout):
        return """
<a href="https://x.com/explore">Explore</a>
<a href="https://x.com/search?q=Hermes">Search</a>
<a href="https://x.com/nousresearch">Profile</a>
<a href="https://x.com/nousresearch/status/123">Status</a>
<a href="https://twitter.com/nousresearch/status/456">Twitter status</a>
"""

    result = execute_backend_chain("x", "Hermes Agent discussion", limit=2, fetch=fake_fetch)

    assert result.engine == "nitter_search"
    assert [hit.url for hit in result.hits] == [
        "https://x.com/nousresearch",
        "https://x.com/nousresearch/status/123",
    ]


def test_youtube_backend_filters_navigation_and_returns_video_results():
    """DDG Lite site:youtube is now first — returns real video results directly."""
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        # DDG Lite returns both corporate pages (filtered) and real videos
        if "lite.duckduckgo.com" in url:
            return """
<a href="https://www.youtube.com/about/">About</a>
<a href="https://www.youtube.com/watch?v=abc123">Real demo video</a>
<a href="https://youtu.be/def456">Second real video</a>
"""
        return ""

    result = execute_backend_chain("youtube", "Claude Code Codex", limit=2, fetch=fake_fetch)

    assert result.engine == "ddg_lite_site_youtube"
    assert len(calls) == 1
    assert [hit.url for hit in result.hits] == [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/def456",
    ]


def test_github_result_url_rejects_marketing_and_accepts_repos():
    assert _github_result_url("https://github.com/DraftShift/StealthChanger") is True
    assert _github_result_url("https://github.com/DraftShift/StealthChanger/wiki/Installation") is True
    assert _github_result_url("https://github.com/features/copilot") is False
    assert _github_result_url("https://github.com/mcp") is False
    assert _github_result_url("https://github.com/security/advanced-security") is False
    assert _github_result_url("https://github.com/search?q=StealthChanger") is False


def test_github_backend_prefers_site_search_and_filters_product_pages():
    import json as _json

    def fake_fetch(url, timeout):
        # SearXNG returns JSON (first in chain now)
        if "127.0.0.1:8099" in url:
            return _json.dumps({
                "results": [
                    {"title": "GitHub Copilot", "url": "https://github.com/features/copilot"},
                    {"title": "GitHub Security", "url": "https://github.com/security/advanced-security"},
                    {"title": "DraftShift StealthChanger", "url": "https://github.com/DraftShift/StealthChanger"},
                    {"title": "Installation Wiki", "url": "https://github.com/DraftShift/StealthChanger/wiki/Installation"},
                ]
            })
        if "bing.com/search" in url:
            return """
<a class="tilk" aria-label="GitHub Copilot" href="{copilot}">GitHub Copilot</a>
<a class="tilk" aria-label="GitHub Security" href="{security}">GitHub Security</a>
<a class="tilk" aria-label="DraftShift StealthChanger" href="{repo}">DraftShift StealthChanger</a>
<a class="tilk" aria-label="Installation Wiki" href="{wiki}">Installation Wiki</a>
""".format(
                copilot=_bing_href("https://github.com/features/copilot"),
                security=_bing_href("https://github.com/security/advanced-security"),
                repo=_bing_href("https://github.com/DraftShift/StealthChanger"),
                wiki=_bing_href("https://github.com/DraftShift/StealthChanger/wiki/Installation"),
            )
        if "site%3Agithub.com" in url or "site:github.com" in url:
            return """
<a href="https://github.com/features/copilot">GitHub Copilot</a>
<a href="https://github.com/security/advanced-security">GitHub Security</a>
<a href="https://github.com/DraftShift/StealthChanger">DraftShift StealthChanger</a>
<a href="https://github.com/DraftShift/StealthChanger/wiki/Installation">Installation Wiki</a>
"""
        return "<a href=\"https://github.com/features/copilot\">GitHub Copilot</a>"

    result = execute_backend_chain("github", "VORON 3D Printer Stealthchanger Build", limit=2, fetch=fake_fetch)

    assert result.engine == "searxng_site_github"
    assert [hit.url for hit in result.hits] == [
        "https://github.com/DraftShift/StealthChanger",
        "https://github.com/DraftShift/StealthChanger/wiki/Installation",
    ]


def test_backend_chain_can_recover_good_results_after_junk_prefix():
    def fake_fetch(url, timeout):
        if "bing.com/search" in url:
            junk = "\n".join(
                f'<a class="tilk" aria-label="Junk {i}" href="{_bing_href(f"https://github.com/features/junk-{i}")}">Junk {i}</a>'
                for i in range(1, 21)
            )
            return junk + f"\n<a class=\"tilk\" aria-label=\"DraftShift StealthChanger\" href=\"{_bing_href('https://github.com/DraftShift/StealthChanger')}\">DraftShift StealthChanger</a>\n"
        if "site%3Agithub.com" in url or "site:github.com" in url or "github.com/search" in url:
            junk = "\n".join(
                f'<a href="https://github.com/features/junk-{i}">Junk {i}</a>'
                for i in range(1, 21)
            )
            return junk + "\n<a href=\"https://github.com/DraftShift/StealthChanger\">DraftShift StealthChanger</a>\n"
        return ""

    result = execute_backend_chain("github", "VORON 3D Printer Stealthchanger Build", limit=1, fetch=fake_fetch)

    assert result.hits
    assert result.hits[0].url == "https://github.com/DraftShift/StealthChanger"


def test_youtube_backend_finds_voron_stealthchanger_video_results():
    def fake_fetch(url, timeout):
        return """
<a href="https://www.youtube.com/about/">About</a>
<a href="https://www.youtube.com/watch?v=EJFSqud2HKQ">StealthChanger - Part 1</a>
<a href="https://www.youtube.com/watch?v=cCbIjArKL4M">Stealthchanger Voron Toolchanger Build Episode 4</a>
"""

    result = execute_backend_chain("youtube", "VORON 3D Printer Stealthchanger Build", limit=2, fetch=fake_fetch)

    assert result.engine == "ddg_lite_site_youtube"
    assert [hit.url for hit in result.hits] == [
        "https://www.youtube.com/watch?v=EJFSqud2HKQ",
        "https://www.youtube.com/watch?v=cCbIjArKL4M",
    ]


def test_tavily_backend_in_tiktok_and_instagram_chains():
    from hermes_trailhead.backends import BACKENDS

    tiktok_names = [b.name for b in BACKENDS["tiktok"]]
    instagram_names = [b.name for b in BACKENDS["instagram"]]

    assert "tavily_tiktok" in tiktok_names, f"tiktok chain missing tavily: {tiktok_names}"
    assert "tavily_instagram" in instagram_names, f"instagram chain missing tavily: {instagram_names}"


def test_tavily_falls_through_gracefully_when_key_is_missing(monkeypatch):
    monkeypatch.setattr("hermes_trailhead.backends._tavily_api_key", lambda: "")

    result = execute_backend_chain("tiktok", "anything", limit=2)

    assert result.engine != "tavily_tiktok"


def test_tiktok_and_instagram_have_bing_discovery_fallbacks():
    def fake_fetch(url, timeout):
        if "bing.com/search" in url and "tiktok.com" in url:
            return f'<a class="tilk" aria-label="TikTok Voron" href="{_bing_href("https://www.tiktok.com/@neokoiprints/video/7520003017949613367")}">TikTok Voron</a>'
        if "bing.com/search" in url and "instagram.com" in url:
            return f'<a class="tilk" aria-label="Instagram Voron" href="{_bing_href("https://www.instagram.com/reel/DQj40znkasX/")}">Instagram Voron</a>'
        return "{}" if "127.0.0.1" in url else ""

    tiktok = execute_backend_chain("tiktok", "VORON StealthChanger", limit=1, fetch=fake_fetch)
    instagram = execute_backend_chain("instagram", "VORON StealthChanger", limit=1, fetch=fake_fetch)

    assert tiktok.engine == "bing_site_tiktok"
    assert tiktok.hits[0].url == "https://www.tiktok.com/@neokoiprints/video/7520003017949613367"
    assert instagram.engine == "bing_site_instagram"
    assert instagram.hits[0].url == "https://www.instagram.com/reel/DQj40znkasX/"


def test_youtube_runtime_prefers_yt_dlp_flat_search(monkeypatch):
    def fake_runner(*args, **kwargs):
        payload = '{"title":"StealthChanger - Part 1","id":"EJFSqud2HKQ","webpage_url":"https://www.youtube.com/watch?v=EJFSqud2HKQ"}\n'
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(backends.shutil, "which", lambda command: "/usr/bin/yt-dlp" if command == "yt-dlp" else None)
    monkeypatch.setattr(backends.subprocess, "run", fake_runner)

    result = execute_backend_chain("youtube", "VORON StealthChanger Build", limit=1)

    assert result.engine == "yt_dlp_flat_search"
    assert result.attempts == ["yt_dlp_flat_search"]
    assert result.hits[0].url == "https://www.youtube.com/watch?v=EJFSqud2HKQ"


def test_reddit_runtime_prefers_social_search_before_fragile_frontends(monkeypatch):
    raw = '''{
      "Reddit": [
        {"text": "Finished my first Voron and Stealthchanger Build", "author": "u/stingeragent · r/3Dprinting", "likes": "140", "retweets": "24 comments"}
      ]
    }'''

    def fake_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=raw, stderr="")

    monkeypatch.setattr(backends.shutil, "which", lambda command: "/home/hermes/.local/bin/social-search" if command == "social-search" else None)
    monkeypatch.setattr(backends.subprocess, "run", fake_runner)

    result = execute_backend_chain("reddit", "VORON StealthChanger Build", limit=1)

    assert result.engine == "social_search_reddit"
    assert result.attempts == ["social_search_reddit"]
    assert "Stealthchanger" in result.hits[0].title
    assert result.hits[0].url.startswith("https://www.reddit.com/r/3Dprinting/search/")


def test_x_runtime_falls_back_to_social_search_when_public_frontends_are_empty(monkeypatch):
    raw = '''{
      "X/Twitter": [
        {"text": "Voron StealthChanger build progress", "author": "@NeoKoi_Prints", "likes": "408", "retweets": "14"}
      ]
    }'''

    def fake_fetch(url, timeout):
        return "{}" if "127.0.0.1" in url else ""

    def fake_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=raw, stderr="")

    monkeypatch.setattr(backends.shutil, "which", lambda command: "/home/hermes/.local/bin/social-search" if command == "social-search" else None)
    monkeypatch.setattr(backends.subprocess, "run", fake_runner)

    result = execute_backend_chain("x", "Voron StealthChanger", limit=1, fetch=fake_fetch, allow_native=True)

    assert result.engine == "social_search_x"
    assert result.hits[0].url == "https://x.com/NeoKoi_Prints"


def test_injected_fetch_path_skips_command_backends_for_deterministic_tests(monkeypatch):
    monkeypatch.setattr(backends.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command backend should not run")))

    def fake_fetch(url, timeout):
        return '<a href="https://www.youtube.com/watch?v=abc123">Real demo video</a>'

    result = execute_backend_chain("youtube", "demo", limit=1, fetch=fake_fetch)

    assert result.engine == "ddg_lite_site_youtube"
    assert result.hits[0].url == "https://www.youtube.com/watch?v=abc123"


def test_ytdlp_flat_search_preserves_descriptions(monkeypatch):
    import json
    from hermes_trailhead import backends

    class Result:
        returncode = 0
        stdout = json.dumps({
            "id": "abc123",
            "title": "Useful demo",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "description": "This is the detailed video description with useful build notes.",
        }) + "\n"
        stderr = ""

    monkeypatch.setattr(backends.shutil, "which", lambda name: "/usr/bin/yt-dlp")
    monkeypatch.setattr(backends.subprocess, "run", lambda *a, **k: Result())

    result = backends.execute_backend_chain("youtube", "demo query", limit=1, allow_native=True)

    assert result.engine == "yt_dlp_flat_search"
    assert result.hits[0].snippet == "This is the detailed video description with useful build notes."
    assert "metadata/transcript extraction is separate" not in result.hits[0].snippet
