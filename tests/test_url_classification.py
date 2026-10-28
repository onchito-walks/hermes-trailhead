"""Regression contracts for URL classification and plain-web HTML readability.

Host rules must be exact-domain or subdomain matches on the parsed hostname —
never a substring of the whole URL.  ``v2ex.com`` contains ``x.com``; a query
string can carry any domain; ``github.com.evil.test`` is not GitHub.

Plain server-rendered HTML (V2EX and friends) must come back as readable text,
not as raw tags and inline script.
"""
import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _as_readable_page_text,
    _classify_source_type,
    _html_to_readable_text,
    _is_youtube_url,
    _youtube_video_id,
    extract_one,
)

# ── Host-boundary classification ──────────────────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        # github — exact host and real subdomains only
        ("https://github.com/NousResearch/hermes-agent/issues/42", "github"),
        ("https://gist.github.com/someone/abc123", "github"),
        ("https://github.com.evil.test/NousResearch/hermes-agent", "web"),
        ("https://mygithub.com/NousResearch/hermes-agent", "web"),
        ("https://example.com/?q=https://github.com/psf/requests", "web"),
        # x / twitter
        ("https://x.com/nousresearch/status/123", "x"),
        ("https://twitter.com/nousresearch/status/123", "x"),
        ("https://mobile.twitter.com/nousresearch/status/123", "x"),
        ("https://www.v2ex.com/t/1252479", "forum"),
        ("https://v2ex.com/t/1252479", "forum"),
        ("https://x.com.evil.test/nousresearch/status/123", "web"),
        ("https://notx.com/status/123", "web"),
        ("https://fox.com/status/123", "web"),
        ("https://example.com/?q=https://x.com/nousresearch", "web"),
        ("https://example.com/redirect?to=https://twitter.com/nousresearch", "web"),
        # reddit
        ("https://www.reddit.com/r/hermesagent/comments/abc123/", "reddit"),
        ("https://old.reddit.com/r/hermesagent/comments/abc123/", "reddit"),
        ("https://reddit.com.evil.test/r/hermesagent/", "web"),
        # tiktok / instagram
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://tiktok.com.evil.test/@user/video/123", "web"),
        ("https://www.instagram.com/p/abc123/", "instagram"),
        # youtube
        ("https://www.youtube.com/watch?v=abc123", "youtube"),
        ("https://m.youtube.com/watch?v=abc123", "youtube"),
        ("https://music.youtube.com/watch?v=abc123", "youtube"),
        ("https://youtu.be/def456", "youtube"),
        ("https://notyoutube.com/watch?v=abc123", "web"),
        ("https://youtube.com.evil.test/watch?v=abc123", "web"),
        ("https://example.com/?u=https://youtu.be/def456", "web"),
        # pdf — suffix on the parsed path, query/fragment ignored
        ("https://example.com/report.pdf", "pdf"),
        ("https://example.com/report.pdf?token=1#page=2", "pdf"),
        ("https://example.com/PAPER.PDF?download=1", "pdf"),
        ("https://example.com/?file=report.pdf", "web"),
        ("https://example.com/pdf/report", "web"),
        # docs — exact host prefixes / path markers, not "docs." in a query
        ("https://docs.hermes-agent.nousresearch.com/config", "docs"),
        ("https://docs.python.org/3/library/json.html", "docs"),
        ("https://project.readthedocs.io/en/latest/", "docs"),
        ("https://example.com/docs/getting-started", "docs"),
        ("https://example.com/?next=docs.python.org/3/", "web"),
        # forum — exact hosts / prefixes
        ("https://stackoverflow.com/questions/123", "forum"),
        ("https://gis.stackexchange.com/questions/123", "forum"),
        ("https://forum.arduino.cc/t/topic/123", "forum"),
        ("https://community.home-assistant.io/t/topic/123", "forum"),
        ("https://discourse.example.com/t/topic/123", "forum"),
        ("https://stackoverflow.com.evil.test/questions/123", "web"),
        ("https://notstackoverflow.com/questions/123", "web"),
        ("https://example.com/?ref=forum.arduino.cc", "web"),
        # plain web
        ("https://example.com/blog/post", "web"),
        ("https://example.com/community/post", "web"),
    ],
)
def test_classify_source_type_uses_host_boundaries(url, expected):
    assert _classify_source_type(url) == expected


def test_classify_source_type_handles_scheme_less_and_empty_inputs():
    assert _classify_source_type("v2ex.com/t/1252479") == "forum"
    assert _classify_source_type("github.com/psf/requests") == "github"
    assert _classify_source_type("") == "web"
    assert _classify_source_type("not a url") == "web"


def test_v2ex_is_not_classified_as_x():
    """``v2ex.com`` contains the substring ``x.com`` — it must not be X."""
    assert _classify_source_type("https://www.v2ex.com/t/1252479") != "x"


# ── YouTube id + URL host boundaries ─────────────────────────────────


def test_youtube_video_id_parses_common_url_shapes():
    assert _youtube_video_id("https://www.youtube.com/watch?v=abc123&t=10") == "abc123"
    assert _youtube_video_id("https://m.youtube.com/watch?v=abc123") == "abc123"
    assert _youtube_video_id("https://youtu.be/def456") == "def456"
    assert _youtube_video_id("https://youtu.be/def456?t=30") == "def456"
    assert _youtube_video_id("https://www.youtube.com/shorts/ghi789") == "ghi789"
    assert _youtube_video_id("https://www.youtube.com/embed/jkl012") == "jkl012"


@pytest.mark.parametrize(
    "url",
    [
        "https://notyoutube.com/watch?v=evil",
        "https://youtube.com.evil.test/watch?v=evil",
        "https://youtu.be.evil.test/evil",
        "https://example.com/watch?v=evil",
        "https://example.com/?u=https://www.youtube.com/watch?v=evil",
        "https://v2ex.com/t/1252479",
        "",
    ],
)
def test_youtube_video_id_rejects_lookalike_hosts(url):
    assert _youtube_video_id(url) == ""


def test_is_youtube_url_uses_host_boundaries():
    assert _is_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert _is_youtube_url("https://youtu.be/abc123")
    assert not _is_youtube_url("https://notyoutube.com/watch?v=abc123")
    assert not _is_youtube_url("https://example.com/?u=https://youtu.be/abc123")


# ── Plain-web HTML readability ────────────────────────────────────────

# A server-rendered forum topic page shaped like a real V2EX thread: no client
# framework, script/style bodies that must never surface, repeated nav chrome,
# HTML entities and multi-paragraph topic + reply content.
V2EX_PLAIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta name="Content-Type" content="text/html;charset=utf-8">
<meta name="theme-color" content="#ffffff">
<title>肾癌转移术后治疗方案 - V2EX</title>
<style>.cell { padding: 10px; } .dark { color: #333; }</style>
<script type="text/javascript">
  var _gaq = _gaq || [];
  var SHOULD_NEVER_APPEAR = "inline-script-marker";
  function track() { return "function-body-marker"; }
</script>
</head>
<body>
<div id="Top">
  <a href="/" class="site-logo">V2EX</a>
  <a href="/?tab=tech">技术</a>
  <a href="/?tab=creative">创意</a>
  <a href="/?tab=apple">Apple</a>
  <a href="/?tab=jobs">酷工作</a>
</div>
<div id="Wrapper">
  <div class="cell">
    <h1>肾癌转移术后治疗方案，想听听大家的意见</h1>
    <div class="topic_content">
      <div class="markdown_body">
        <p>我父亲 8 年前做过右肾透明细胞癌手术，两年前发现右侧腰背部包块。</p>
        <p>CT、MRI 和 PET/CT 怀疑肾癌转移，但未发现其他明确病灶。腰背部肿瘤已经扩大切除，切缘阴性，病理确认肾细胞癌转移。</p>
        <p>术后影像没有明确残留，属于转移灶切除后的无瘤状态，即 M1 NED。医生建议使用&ldquo;特瑞普利单抗＋阿昔替尼&rdquo;。</p>
      </div>
    </div>
  </div>
  <div class="cell">
    <div class="reply_content">
      <p>建议先去泌尿肿瘤专科做多学科会诊，把病理切片带齐。</p>
    </div>
    <div class="reply_content">
      <p>免疫联合靶向的方案现在比较常见，注意监测甲状腺功能。</p>
    </div>
  </div>
  <div class="cell">
    <a href="/t/1252479#reply1">回复</a>
    <a href="/t/1252479#reply1">回复</a>
    <a href="/t/1252479#reply1">回复</a>
  </div>
</div>
<div id="Bottom">
  <a href="/about">关于</a>
  <a href="/about">关于</a>
  <span>V2EX</span>
</div>
<script type="application/json">{"props": {"pageProps": {"marker": "json-payload-marker"}}}</script>
</body>
</html>
"""


def _fake_fetch_returning(payload):
    def fake_fetch(url, timeout):
        return payload

    return fake_fetch


def test_v2ex_plain_page_extracts_readable_text_not_markup(monkeypatch):
    """A server-rendered forum page becomes readable text, not raw HTML."""
    monkeypatch.setattr(
        extract_mod,
        "_fetch_hermes_web_extract",
        lambda url, timeout: (_ for _ in ()).throw(AssertionError("direct HTML fetch should win")),
    )

    result = extract_one(
        "https://www.v2ex.com/t/1252479",
        fetch=_fake_fetch_returning(V2EX_PLAIN_PAGE),
    )

    assert result.status == "ok"
    assert result.source_type == "forum"
    assert result.usable is True

    content = result.content
    # Evidence survives, in order, as prose.
    assert "肾癌转移术后治疗方案" in content
    assert "透明细胞癌" in content
    assert "多学科会诊" in content
    assert "甲状腺功能" in content
    assert "“特瑞普利单抗＋阿昔替尼”" in content  # entities decoded
    # Markup and non-visible bodies never leak into evidence.
    assert "<div" not in content
    assert "<script" not in content
    assert "<p>" not in content
    assert "</" not in content
    assert "inline-script-marker" not in content
    assert "function-body-marker" not in content
    assert "json-payload-marker" not in content
    assert "SHOULD_NEVER_APPEAR" not in content
    assert "var _gaq" not in content
    assert "&ldquo;" not in content
    assert "&nbsp;" not in content
    # Repeated nav/footer chrome is deduplicated, and paragraphs stay apart.
    assert content.count("回复") == 1
    assert content.count("关于") == 1
    assert "\n" in content
    # Reported length describes the readable text actually returned.
    assert result.content_length == len(content)
    assert result.content_length < len(V2EX_PLAIN_PAGE)


def test_client_rendered_shell_is_still_blocked(monkeypatch):
    """Cleaning must not turn a JS-only app shell into "evidence"."""
    monkeypatch.setattr(
        extract_mod,
        "_fetch_hermes_web_extract",
        lambda url, timeout: (_ for _ in ()).throw(AssertionError("shell should stop here")),
    )
    shell = "<!DOCTYPE html><html><body><div id='root'></div><script>window.APP=1;</script></body></html>"

    result = extract_one("https://example.com/app", fetch=_fake_fetch_returning(shell))

    assert result.status == "blocked"
    assert not result.usable


def test_clean_markdown_passes_through_unchanged():
    markdown = "# Title\n\nReadable paragraph.\n\n- item one\n- item two\n"
    assert _as_readable_page_text(markdown) == markdown


def test_html_to_readable_text_separates_blocks_and_decodes_entities():
    html = "<html><body><p>First &amp; second.</p><p>Third&nbsp;line.</p></body></html>"
    text = _html_to_readable_text(html)
    assert text.splitlines() == ["First & second.", "Third line."]


def test_html_to_readable_text_caps_runaway_pages():
    body = "<html><body>" + "".join(f"<p>paragraph number {i}</p>" for i in range(4000)) + "</body></html>"
    text = _html_to_readable_text(body)
    assert len(text) <= extract_mod._READABLE_TEXT_LIMIT + 5
    assert text.endswith("...")


# ── TRAILHEAD_DISABLE_ASR gate ────────────────────────────────────────


def _forbid_external_calls(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("external call attempted while ASR is disabled")

    monkeypatch.setattr(extract_mod.subprocess, "run", boom)
    monkeypatch.setattr(extract_mod.urllib.request, "urlopen", boom)
    monkeypatch.setattr(extract_mod, "_get_groq_key", boom)


def test_youtube_asr_veto_wins_over_full_consent_before_external_call(monkeypatch):
    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    _forbid_external_calls(monkeypatch)

    with pytest.raises(RuntimeError, match="ASR disabled for this run"):
        extract_mod._fetch_youtube_asr(
            "https://www.youtube.com/watch?v=abc123",
            allow_authenticated=True,
            allow_quota_consuming=True,
        )


def test_tiktok_asr_veto_wins_over_full_consent_before_external_call(monkeypatch):
    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    _forbid_external_calls(monkeypatch)

    with pytest.raises(RuntimeError, match="ASR disabled for this run"):
        extract_mod._fetch_tiktok_transcript(
            "https://www.tiktok.com/@user/video/123",
            allow_authenticated=True,
            allow_quota_consuming=True,
        )


def test_asr_gate_defaults_to_refusing_consent(monkeypatch):
    monkeypatch.delenv("TRAILHEAD_DISABLE_ASR", raising=False)
    assert extract_mod._asr_disabled() is False

    with pytest.raises(RuntimeError, match="ASR is opt-in"):
        extract_mod._ensure_asr_enabled()

    # Both consent keywords are required; one is not enough.
    with pytest.raises(RuntimeError, match="ASR is opt-in"):
        extract_mod._ensure_asr_enabled(allow_authenticated=True)
    with pytest.raises(RuntimeError, match="ASR is opt-in"):
        extract_mod._ensure_asr_enabled(allow_quota_consuming=True)

    extract_mod._ensure_asr_enabled(
        allow_authenticated=True,
        allow_quota_consuming=True,
    )  # no raise

    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "0")
    assert extract_mod._asr_disabled() is False
