import base64
import subprocess

from hermes_trailhead import backends
from hermes_trailhead.backends import (
    execute_backend_chain,
    _github_result_url,
    _youtube_result_url,
    _x_result_url,
    _run_github_api_search,
)
from hermes_trailhead.backends import _instagram_result_url


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


def test_redlib_parser_extracts_canonical_thread_urls():
    from hermes_trailhead.backends import _parse_redlib_results

    page = '''
    <h2 class="post_title">
        <a href="/r/LocalLLaMA/search?q=flair_name%3A%22Discussion%22" class="post_flair" style="color:white;" dir="ltr"><span>Discussion</span></a>
        <a href="/r/LocalLLaMA/comments/1w0muuz/the_rtx_3060_12gb_an_unsung_hero/">The RTX 3060 12GB: An unsung hero of local AI</a>
    </h2>
    <h2 class="post_title"><a href="/r/ollama/comments/1rudsyc/professionalgrade_local_ai/">Professional-grade local AI on consumer hardware</a></h2>
    <a href="https://www.reddit.com/search?q=x">Noise search link</a>
    '''
    hits = _parse_redlib_results(page, 5)

    assert [h.url for h in hits] == [
        "https://www.reddit.com/r/LocalLLaMA/comments/1w0muuz/the_rtx_3060_12gb_an_unsung_hero",
        "https://www.reddit.com/r/ollama/comments/1rudsyc/professionalgrade_local_ai",
    ]


def test_reddit_chain_prefers_local_redlib():
    from hermes_trailhead.backends import _reset_circuit

    _reset_circuit("redlib_local_search")

    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        if "127.0.0.1:8789" in url:
            return (
                '<h2 class="post_title">'
                '<a href="/r/LocalLLaMA/comments/1w0muuz/the_rtx_3060_12gb/">'
                'The RTX 3060 12GB: an unsung hero of local AI'
                "</a></h2>"
            )
        return ""

    result = execute_backend_chain("reddit", "rtx 3060 local", limit=2, fetch=fake_fetch)

    assert result.engine == "redlib_local_search"
    assert calls and calls[0].startswith("http://127.0.0.1:8789/search")
    assert result.hits[0].url == "https://www.reddit.com/r/LocalLLaMA/comments/1w0muuz/the_rtx_3060_12gb"


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
    assert result.hits[0].url == "https://x.com/search?q=Voron+StealthChanger"


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


def test_github_run_api_search_returns_canonical_repos_and_issues():
    import json as _json

    def fake_opener(url, timeout):
        if "/search/repositories" in url:
            return _json.dumps({"items": [
                {
                    "html_url": "https://github.com/DraftShift/StealthChanger",
                    "full_name": "DraftShift/StealthChanger",
                    "description": "Tool changing system for Vorons",
                    "stargazers_count": 1169,
                },
                # Marketing path that must be filtered out
                {"html_url": "https://github.com/features/copilot", "full_name": "github/features"},
            ]})
        # issues endpoint
        return _json.dumps({"items": [
            {
                "html_url": "https://github.com/DraftShift/StealthChanger/issues/5",
                "repository": {"full_name": "DraftShift/StealthChanger"},
                "title": "stealthchanger toolhead swap not aligning",
            },
        ]})

    hits = _run_github_api_search("stealthchanger", limit=3, opener=fake_opener)
    urls = [h.url for h in hits]

    assert "https://github.com/DraftShift/StealthChanger" in urls
    assert "https://github.com/DraftShift/StealthChanger/issues/5" in urls
    assert "https://github.com/features/copilot" not in urls  # marketing filtered


def test_github_run_api_search_degrades_gracefully_on_error():
    def fail_opener(url, timeout):
        raise RuntimeError("simulated API rate limit / network failure")

    # Empty result — chain falls through to HTTP backends instead of crashing.
    assert _run_github_api_search("stealthchanger", limit=3, opener=fail_opener) == ()


def test_github_runtime_prefers_api_repo_discovery(monkeypatch):
    import json as _json

    class FakeResp:
        def read(self):
            return _json.dumps({"items": [
                {
                    "html_url": "https://github.com/DraftShift/StealthChanger",
                    "full_name": "DraftShift/StealthChanger",
                    "description": "Tool changing system for Vorons",
                    "stargazers_count": 1169,
                },
            ]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(backends.urllib.request, "urlopen", lambda req, timeout=20: FakeResp())

    result = execute_backend_chain("github", "stealthchanger voron", limit=2)

    assert result.engine == "github_api_search"
    assert result.hits[0].url == "https://github.com/DraftShift/StealthChanger"


def test_github_api_search_url_reduces_verbose_exact_match_query():
    # GitHub search is exact-match over the raw query: a verbose multi-word
    # query returns 0 results. The API URL must reduce to top meaningful terms.
    from hermes_trailhead.backends import _github_api_search_url

    url = _github_api_search_url("VORON Stealthchanger 3D printer build", "repositories")
    assert "q=voron+stealthchanger" in url
    assert "printer" not in url  # stopword dropped

    issues = _github_api_search_url("VORON Stealthchanger 3D printer build", "issues")
    assert "q=voron+stealthchanger+in:title" in issues


def test_github_query_terms_keep_numeric_axis_compounds():
    # Regression: "DIY 5 axis 3D printer" used to reduce to the single generic
    # term "axis" (5 and printer were dropped), returning unrelated repos
    # (agent frameworks, AXI controllers). The compound must survive.
    from hermes_trailhead.backends import _github_query_terms, _github_api_search_url

    assert _github_query_terms("DIY 5 axis 3D printer") == ("5-axis",)
    assert _github_query_terms("5 axis cnc router") == ("5-axis", "router")

    url = _github_api_search_url("DIY 5 axis 3D printer", "repositories")
    assert "q=5-axis" in url


def test_tiktok_result_url_rejects_shop_listings():
    from hermes_trailhead.backends import _tiktok_result_url

    assert _tiktok_result_url("https://shop.tiktok.com/us/k/5-axsis-3d-printer") is False
    assert _tiktok_result_url("https://www.tiktok.com/@3dprintingdoctor/video/7665567402905685261") is True


def test_open_web_result_url_excludes_dedicated_lane_hosts():
    from hermes_trailhead.backends import _open_web_result_url

    assert _open_web_result_url("https://hackaday.com/2022/03/13/5-axis-3d-printing/") is True
    assert _open_web_result_url("https://www.reddit.com/r/3Dprinting/comments/16eakw2/x/") is True
    assert _open_web_result_url("https://www.youtube.com/watch?v=hIQLzIJiO9g") is False
    assert _open_web_result_url("https://youtu.be/abc") is False
    assert _open_web_result_url("https://www.tiktok.com/@x/video/1") is False
    assert _open_web_result_url("https://www.instagram.com/reel/x/") is False
    assert _open_web_result_url("https://www.facebook.com/watch/1") is False


def test_instagram_result_url_rejects_popular_aggregation_pages():
    # Deep post/reel and profile routes are kept for discovery.
    assert _instagram_result_url("https://www.instagram.com/reel/DYHibt4PCLB/") is True
    assert _instagram_result_url("https://www.instagram.com/p/DQj40znkasX/") is True
    assert _instagram_result_url("https://www.instagram.com/voron_design/") is True
    # Aggregation/navigation shells are discarded — they extract as junk.
    assert _instagram_result_url("https://www.instagram.com/popular/voron-stealthchanger/") is False
    assert _instagram_result_url("https://www.instagram.com/explore/tags/voron/") is False
    assert _instagram_result_url("https://www.instagram.com/about/") is False
