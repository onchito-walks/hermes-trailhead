import base64

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


def test_youtube_backend_filters_navigation_and_falls_through_to_video_results():
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        if "r.jina.ai" in url:
            return """
## [About](https://www.youtube.com/about/)
Corporate page.
## [Press](https://www.youtube.com/about/press/)
Corporate page.
"""
        return """
<a href="https://www.youtube.com/about/">About</a>
<a href="https://www.youtube.com/watch?v=abc123">Real demo video</a>
<a href="https://youtu.be/def456">Second real video</a>
"""

    result = execute_backend_chain("youtube", "Claude Code Codex", limit=2, fetch=fake_fetch)

    assert result.engine == "ddg_lite_site_youtube"
    assert len(calls) == 2
    assert "site%3Ayoutube.com%2Fwatch" in calls[-1]
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
    def fake_fetch(url, timeout):
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

    assert result.engine == "bing_search"
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
