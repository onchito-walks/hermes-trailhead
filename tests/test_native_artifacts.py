"""Native artifact contracts: GitHub README and listing-page link identifiers.

Two public acceptance cases returned the wrong *artifact* while reporting
``status == "ok"``:

* a GitHub repository root returned stats plus a ~1.2k README excerpt, so the
  install command that lives further down the README never reached the caller;
* a V2EX node listing returned topic titles with no topic URLs, so the caller
  could read *what* exists but not *where* it is.

Both defects are fixed in the existing reader (``extract.py``), not with a new
connector.  These tests therefore assert the source text survives the reader:

* the README is fetched whole from the maintained public README endpoint, and a
  README that does not contain an install command or licence must **not** gain
  one — artifacts are read from the source, never synthesised;
* anchors keep the destination that is in the markup, resolved against the page
  URL that was actually fetched, and no destination is invented when the page
  URL (or the href) is unusable;
* reported truncation stays truthful when content exceeds the readable cap.

No test touches the network.
"""

from __future__ import annotations

import base64
import json

import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _expand_anchor_targets,
    _fetch_github_summary,
    _github_repo_metadata,
    _html_to_readable_text,
    _link_target,
    extract_one,
)


# ── Fakes (no network) ────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _repo_metadata(**overrides) -> dict:
    data = {
        "full_name": "example/widget",
        "description": "A widget library.",
        "homepage": "",
        "stargazers_count": 10,
        "forks_count": 2,
        "open_issues_count": 1,
        "language": "Python",
        "license": {"name": "Apache License 2.0", "spdx_id": "Apache-2.0"},
    }
    data.update(overrides)
    return data


def _readme_with_buried_install() -> str:
    """README whose install section sits well past the old 1200-char excerpt."""
    preamble = "\n".join(
        f"- note {i}: repository background line that fills the excerpt budget"
        for i in range(30)
    )
    return (
        "# widget\n\n"
        "A simple, yet elegant, widget library.\n\n"
        f"{preamble}\n\n"
        "## Installing widget\n\n"
        "```console\n$ python -m pip install widget\n```\n\n"
        "## License\n\nApache License 2.0\n"
    )


def _patch_repo_json(monkeypatch, *, readme_body: str | None = None, **metadata):
    """Patch `_github_api_json` so only the public API shapes appear."""

    def fake_json(api: str, timeout: int = 15):
        if api.endswith("/readme"):
            if readme_body is None:
                raise AssertionError("contents-API fallback must not be used here")
            return {"content": base64.b64encode(readme_body.encode()).decode()}
        return _repo_metadata(**metadata)

    monkeypatch.setattr(extract_mod, "_github_api_json", fake_json)


# ── GitHub: full README on the repository root ────────────────────────


def test_github_root_readme_is_fetched_whole_via_raw_media_type(monkeypatch):
    readme = _readme_with_buried_install()
    _patch_repo_json(monkeypatch)
    requests: list = []

    def fake_urlopen(req, timeout=15):
        requests.append(req)
        assert req.full_url == "https://api.github.com/repos/example/widget/readme"
        return _FakeResponse(readme.encode())

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", fake_urlopen)

    out = _github_repo_metadata("example", "widget", ["example", "widget"], 10, full_readme=True)

    # The maintained public REST README endpoint is used with the raw media
    # type, so no base64 JSON payload and no excerpt slicing is involved.
    assert len(requests) == 1
    assert requests[0].get_header("Accept") == "application/vnd.github.raw"
    assert "README:" in out
    assert "README excerpt" not in out
    # Artifacts that live deep in the source README survive.
    assert "python -m pip install widget" in out
    assert "Apache License 2.0" in out
    assert "A simple, yet elegant, widget library." in out
    # License also comes from the repository metadata the API returns.
    assert "License: Apache License 2.0" in out
    # The body is returned unmodified, not re-flowed by a regex.
    assert readme.strip() in out


def test_github_root_does_not_invent_artifacts_the_readme_lacks(monkeypatch):
    readme = "# bare\n\nA repository with a minimal README and nothing else.\n"
    _patch_repo_json(monkeypatch, license=None)
    monkeypatch.setattr(
        extract_mod.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResponse(readme.encode()),
    )

    out = _github_repo_metadata("example", "bare", ["example", "bare"], 10, full_readme=True)

    assert "A repository with a minimal README" in out
    # No install command, no licence, no invented "License:" field.
    assert "pip install" not in out
    assert "License:" not in out
    assert "Apache" not in out


def test_github_raw_failure_falls_back_to_contents_api(monkeypatch):
    readme = _readme_with_buried_install()
    _patch_repo_json(monkeypatch, readme_body=readme)

    def failing_urlopen(req, timeout=15):
        raise OSError("raw media type unavailable")

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", failing_urlopen)

    out = _github_repo_metadata("example", "widget", ["example", "widget"], 10, full_readme=True)

    assert "python -m pip install widget" in out
    assert "README:" in out


def test_github_api_error_body_is_not_readme_evidence(monkeypatch):
    readme = "# widget\n\nReal README body from the contents API fallback.\n"
    _patch_repo_json(monkeypatch, readme_body=readme)

    error_body = json.dumps({"message": "Not Found", "documentation_url": "https://docs"})
    monkeypatch.setattr(
        extract_mod.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResponse(error_body.encode()),
    )

    out = _github_repo_metadata("example", "widget", ["example", "widget"], 10, full_readme=True)

    assert "Real README body from the contents API fallback." in out
    assert '"message"' not in out
    assert "Not Found" not in out


def test_github_non_root_page_keeps_bounded_excerpt(monkeypatch):
    readme = _readme_with_buried_install()
    _patch_repo_json(monkeypatch, readme_body=readme)

    def failing_urlopen(req, timeout=15):
        raise AssertionError("non-root pages must not use the raw README path")

    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", failing_urlopen)

    out = _fetch_github_summary("https://github.com/example/widget/issues", timeout=10)

    assert "README excerpt:" in out
    assert "Requested path: /issues" in out
    # Bounded excerpt: content past the excerpt budget is not claimed.
    assert "python -m pip install widget" not in out


def test_github_root_summary_opt_in_is_exact_root_only(monkeypatch):
    readme = _readme_with_buried_install()
    _patch_repo_json(monkeypatch)
    monkeypatch.setattr(
        extract_mod.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResponse(readme.encode()),
    )

    out = _fetch_github_summary("https://github.com/example/widget", timeout=10)

    assert "python -m pip install widget" in out
    assert "README excerpt" not in out


def test_github_oversized_content_reports_truncation_truthfully(monkeypatch):
    huge = "line of README text\n" * 4000  # ~80k chars
    monkeypatch.setattr(extract_mod, "_fetch_github_summary", lambda url, timeout=15: huge)

    result = extract_one("https://github.com/example/huge", timeout=1)

    assert result.status == "ok"
    assert result.content_length == len(huge)  # measured, not the returned slice
    assert len(result.content) <= extract_mod._READABLE_TEXT_LIMIT + 4
    assert result.content.endswith("...")
    assert result.content.startswith("line of README text")


# ── Listing pages: titles keep their identifiers ──────────────────────

V2EX_NODE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><title>Python - V2EX</title>
<script>var marker = "SHOULD_NEVER_APPEAR";</script></head>
<body>
<div id="Top">
  <a href="/" class="site-logo">V2EX</a>
  <a href="/?tab=tech">技术</a>
  <a href="javascript:void(0)">更多</a>
  <a href="mailto:hi@example.com">联系</a>
  <a href="#reply1">跳到回复</a>
</div>
<div class="intro">
  <p>这里讨论各种 Python 语言编程话题，也包括 Django，Tornado 等框架的讨论。</p>
  <p>这里是一个能够帮助你解决实际问题的地方，欢迎分享你的项目、疑问和经验。</p>
</div>
<div id="TopicsNode">
  <div class="cell">
    <a href="/t/1250533#reply122" class="topic-link">前端想学后端，但是看完这段代码就已经力竭了</a>
    <span class="meta">Bologna • 6 days ago • Lastly replied by Bologna</span>
    <a href="/t/1250533#reply122">122</a>
  </div>
  <div class="cell">
    <a href="/t/1246645#reply68" class="topic-link">大家还搞 Python 吗</a>
    <span class="meta">iorilu • 7 days ago • Lastly replied by jackOff</span>
  </div>
  <div class="cell">
    <a href="/t/1248327#reply10" class="topic-link">Python 3.15 正式发布</a>
    <span class="meta">iorilu • 14 days ago • Lastly replied by huangzhiyia</span>
    <a href="https://docs.python.org/3/whatsnew/3.15.html">release notes</a>
  </div>
  <div class="cell">
    <a href="/t/1246683#reply0" class="topic-link">fastapi-gql-mcp 将 fastapi 应用转变成 agent 友好的 mcp 服务</a>
    <span class="meta">tangkikodo • 22 days ago</span>
  </div>
  <div class="cell"><a href="/go/python?p=2">2</a> <a href="/go/python?p=3">3</a></div>
</div>
</body>
</html>
"""


def test_listing_page_titles_keep_resolved_topic_urls():
    url = "https://www.v2ex.com/go/python"
    text = _html_to_readable_text(V2EX_NODE_PAGE, base_url=url)

    # Every topic title keeps the identifier from the href, resolved against
    # the page URL that was actually fetched.
    assert "前端想学后端，但是看完这段代码就已经力竭了 — https://www.v2ex.com/t/1250533#reply122" in text
    assert "大家还搞 Python 吗 — https://www.v2ex.com/t/1246645#reply68" in text
    assert "Python 3.15 正式发布 — https://www.v2ex.com/t/1248327#reply10" in text
    assert "release notes — https://docs.python.org/3/whatsnew/3.15.html" in text
    # Markup and script bodies never leak.
    assert "<a" not in text and "</" not in text
    assert "SHOULD_NEVER_APPEAR" not in text


def test_unusable_or_duplicate_targets_add_no_url():
    url = "https://www.v2ex.com/go/python"
    text = _html_to_readable_text(V2EX_NODE_PAGE, base_url=url)

    # Pure-digit labels (reply counts, pagination) name navigation, not content.
    assert "122 —" not in text
    assert "2 — https://www.v2ex.com/go/python?p=2" not in text
    # Script/mail/fragment hrefs are not destinations a reader can follow.
    assert "更多" in text and "javascript:" not in text
    assert "联系" in text and "mailto:" not in text
    assert "跳到回复" in text
    # A repeated target is shown once, with the identifying label; a second
    # label for the same destination keeps its text but adds no second URL.
    assert text.count("https://www.v2ex.com/t/1250533#reply122") == 1
    assert "\n122\n" in f"\n{text}\n"
    # The page's own address is not presented as an outbound destination.
    assert f"V2EX — {url}" not in text


def test_relative_hrefs_are_never_guessed_without_a_page_url():
    html = '<p><a href="/t/1250533#reply122">topic title</a></p>'
    text = _html_to_readable_text(html)

    assert text == "topic title"
    assert "v2ex.com" not in text


def test_absolute_hrefs_survive_without_a_page_url():
    html = '<p><a href="https://www.v2ex.com/t/9">topic</a></p>'
    assert "topic — https://www.v2ex.com/t/9" in _html_to_readable_text(html)


def test_link_target_rejects_non_addresses():
    assert _link_target("#reply1", "https://www.v2ex.com/go/python") == ""
    assert _link_target("javascript:void(0)", "https://www.v2ex.com/go/python") == ""
    assert _link_target("mailto:hi@example.com", "https://www.v2ex.com/go/python") == ""
    assert _link_target("/t/1", "") == ""
    assert _link_target("/t/1", "https://www.v2ex.com/go/python") == "https://www.v2ex.com/t/1"
    assert _link_target("t/1", "https://www.v2ex.com/go/python/") == "https://www.v2ex.com/go/python/t/1"


def test_clean_markdown_is_not_rewritten():
    markdown = "# Title\n\nReadable paragraph with [a link](https://example.com/x).\n"
    assert extract_mod._as_readable_page_text(markdown) == markdown
    assert _expand_anchor_targets(markdown) == markdown


def test_listing_extraction_end_to_end_keeps_topic_urls():
    """`extract_one` threads the fetched URL into the readable-text pass."""

    result = extract_one(
        "https://www.v2ex.com/go/python",
        fetch=lambda url, timeout: V2EX_NODE_PAGE,
    )

    assert result.status == "ok"
    assert result.source_type == "forum"
    content = result.content
    assert content.count("https://www.v2ex.com/t/") >= 3
    assert result.content_length == len(content)
    assert result.content_length < len(V2EX_NODE_PAGE)


@pytest.mark.parametrize("label", ["122", "2", "❮", "›"])
def test_navigation_labels_never_carry_urls(label):
    html = f'<p><a href="/t/{label}">{label}</a></p>'
    text = _html_to_readable_text(html, base_url="https://www.v2ex.com/t/1252479")
    assert text == label


def test_link_annotations_cannot_mask_a_blocked_interstitial():
    """Blocked pages are classified on source text, not on added URLs.

    A "blocked" notice is only read as an interstitial while the body is short.
    If appended link destinations counted towards that length, a nav-heavy
    block page would cross the threshold and be reported as usable evidence.
    """
    url = "https://www.example.com/blocked"
    nav = "".join(
        f'<a href="/section/{i}">navigation item number {i}</a>' for i in range(40)
    )
    page = (
        "<!DOCTYPE html><html><body><div id='nav'>"
        f"{nav}"
        "</div><div>Access Denied. You have been blocked by network security.</div>"
        "</body></html>"
    )

    # The annotated reading is long enough to cross the interstitial length
    # threshold, so the gate must not be looking at it.
    annotated = _html_to_readable_text(page, base_url=url)
    assert len(annotated) > extract_mod._BLOCKED_SHELL_MAX_CHARS

    assert extract_mod._readable_page_result(page, base_url=url) == ""
    assert extract_mod._readable_page_result(page) == ""
