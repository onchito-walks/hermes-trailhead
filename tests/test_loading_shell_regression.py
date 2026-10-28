"""Regression tests for the BOSS直聘 loading-interstitial false success.

The pinned public sweep recorded ``boss read`` as ``ok: true`` with one item and
a 54-character body — see ``docs/ACTION-ARTIFACT-EVIDENCE.md`` §9:

    target  https://www.zhipin.com/job_detail/c1039e39ba83b73e0nd639i_FFJR.html?_security_check=1_1783322651289
    title   请稍候 - BOSS直聘
    body    B O S S  正在加载中...  © copyright BOSS直聘 京ICP备14013441号-5
    sha256  f7dba9e2db1ed96f187a40e79a57f26050c2736304bc2c31155bd4fb8286ace4

That body is BOSS's own "please wait" template — brand mark, loading notice and
the site's ICP/copyright footer — not the job description the action promises.
``extract.classify_page_shell`` (used by ``reach_backend._normalize_items``) did
not classify it, so no ``content_unusable`` guard fired and the caller was told
the read succeeded.

The fix is deliberately narrow: a body is a loading gate only when it is short
**and** carries a loading notice **and** a page-footer stamp **and** has almost
nothing left once both are removed, with any sentence boundary vetoing the
verdict.  The second half of this file is therefore a false-positive corpus:
short Chinese prose, multilingual docs that *discuss* loading/请稍候, an English
article about loading states, and a code snippet must all still be readable.

No network is used.  The backend case is a public-backend spy: the pinned
upstream shape is handed to the real ``AgentReachBackend`` through an injected
runner, so the classification, the withholding and the error envelope are the
production ones.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from hermes_trailhead import reach_backend as reach
from hermes_trailhead.extract import _is_usable_page_text, classify_page_shell, extract_one

# ── the recorded body, verbatim ───────────────────────────────────────────

#: Exactly as forwarded by ``boss read`` (54 chars, two-space runs between the
#: three blocks).  The newlines version is the same three blocks as the platform
#: renders them; both shapes must be rejected.
BOSS_LOADING_FLAT = (
    "B O S S  正在加载中...  © copyright BOSS直聘 京ICP备14013441号-5"
)
BOSS_LOADING_MULTILINE = (
    "B O S S\n正在加载中...\n© copyright BOSS直聘 京ICP备14013441号-5"
)
BOSS_LOADING_TITLE = "请稍候 - BOSS直聘"
BOSS_JOB_URL = (
    "https://www.zhipin.com/job_detail/"
    "c1039e39ba83b73e0nd639i_FFJR.html?_security_check=1_1783322651289"
)
ATTRIBUTION = "Agent Reach (third-party CLI), forwarded by Hermes Trailhead"

#: The same gate as a reader tier served it on 2026-10-28 (one public recheck of
#: the recorded URL, no credentials, no paid API): 435 chars of transport header
#: in front of the same 54-character body.  ``document_sha256`` is what the read
#: reported, so this fixture is provably the page that was fetched.
BOSS_LIVE_CAPTURE = (
    "Title: 请稍候 - BOSS直聘\n\n"
    f"URL Source: {BOSS_JOB_URL}\n\n"
    "Published Time: Wed, 21 Oct 2026 13:19:13 GMT\n\n"
    "Warning: This page maybe not yet fully loaded, consider explicitly specify a timeout.\n"
    "Warning: This is a cached snapshot of the original page, consider retry with "
    "caching opt-out.\n\n"
    "Markdown Content:\nB O S S\n\n正在加载中...\n\n© copyright BOSS直聘 京ICP备14013441号-5\n"
)
BOSS_LIVE_SHA256 = "f23b7084613b5e5b3f66961772081e6e12abf3aea35c158c0472cb20f9cda24b"

# ── false-positive corpus: all of these are documents, not gates ──────────

#: Bodies that mention loading, waiting or a copyright and must stay readable.
DOCUMENT_BODIES = {
    # A Chinese help article *about* a page stuck on 正在加载中.
    "zh_docs_about_loading": (
        "图片一直显示正在加载中怎么办？\n\n"
        "如果你看到页面一直停在正在加载中，先检查网络，再清除缓存。\n"
        "我们整理了三步排查法，覆盖弱网、代理和浏览器扩展三种常见原因。\n"
        "最后一步是查看控制台报错，确认图片地址是否返回 404。"
        "版权所有 示例站点，转载请注明出处。"
    ),
    # A short Chinese page about 请稍候 wording — one sentence, still prose.
    "zh_loading_copy_doc": "加载中提示文案统一为“正在加载中”。版权所有。",
    # A short Chinese page about 请稍候 wording — sentences, still prose.
    "zh_short_loading_doc": (
        "页面一直停在正在加载中。请稍候的提示最多显示十秒，超时就应改用错误提示，"
        "以免用户一直等待。版权所有 2024"
    ),
    # Short Chinese prose with no punctuation at all.
    "zh_short_note": (
        "周末去了这家咖啡店 手冲很稳 豆子偏果酸 人均四十左右 性价比不错 "
        "店里只有六个座位 下午两点后人会多一些"
    ),
    # A copyright notice quoted inside ordinary Chinese prose.
    "zh_short_prose_copyright": (
        "这篇文章讨论版权问题。版权所有意味着他人不能随意转载你的文字，"
        "但引用段落并注明出处是允许的，这一点常被误解。"
    ),
    # An English article that uses "loading" as its subject.
    "en_loading_article": (
        "Loading states matter more than teams expect. A spinner should appear "
        "within 100ms and a skeleton after a second, otherwise users assume the "
        "tap failed and retry, which doubles the request volume. Copyright 2024 "
        "UX Weekly."
    ),
    "en_loading_docs": (
        "Lazy loading defers image requests until they scroll into view. Set the "
        "loading attribute and measure the effect with the Performance panel."
    ),
    # A code snippet: source text is content, never chrome.
    "code_snippet": (
        "async function load() {\n"
        "  setLoading(true);\n"
        "  const res = await fetch('/api/items');\n"
        "  return res.json();\n"
        "}"
    ),
    # Japanese / Korean prose about a stalled loading screen, then a footer.
    "ja_loading_doc": (
        "読み込み中に画面が固まる場合は、ブラウザのキャッシュを削除してください。"
        "それでも改善しないときは通信環境を確認します。© copyright 株式会社サンプル"
    ),
    "ko_loading_doc": (
        "로딩 중 화면이 멈추면 캐시를 지우고 다시 시도하세요. "
        "그래도 문제가 계속되면 네트워크 상태를 확인해야 합니다. © copyright 예제"
    ),
}


# ── classifier: the recorded gate is a shell ──────────────────────────────


@pytest.mark.parametrize("body", [BOSS_LOADING_FLAT, BOSS_LOADING_MULTILINE])
def test_recorded_boss_loading_page_is_classified_blocked(body):
    assert classify_page_shell(body) == "blocked"
    assert _is_usable_page_text(body) is False


def test_recorded_boss_body_keeps_the_pinned_character_count():
    """Guard the fixture itself: 54 chars is what the sweep recorded."""
    assert len(BOSS_LOADING_FLAT) == 54
    assert "正在加载中" in BOSS_LOADING_FLAT
    assert "京ICP备14013441号-5" in BOSS_LOADING_FLAT


# ── the same gate behind a reader tier's transport header ─────────────────


def test_live_capture_is_the_pinned_fetch():
    """The 435-char capture is byte-for-byte the document the read reported."""
    assert len(BOSS_LIVE_CAPTURE) == 435
    assert hashlib.sha256(BOSS_LIVE_CAPTURE.encode()).hexdigest() == BOSS_LIVE_SHA256


def test_live_capture_header_does_not_hide_the_gate():
    """A 435-char header must not lift a 54-char gate over the size test."""
    assert classify_page_shell(BOSS_LIVE_CAPTURE) == "blocked"
    assert _is_usable_page_text(BOSS_LIVE_CAPTURE) is False


def test_native_read_of_the_live_capture_is_blocked_not_ok():
    """The extraction pipeline must report the gate, not a successful read."""
    from hermes_trailhead.extract import extract_one

    result = extract_one(
        BOSS_JOB_URL,
        fetch=lambda url, timeout: BOSS_LIVE_CAPTURE,
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )
    assert result.status == "blocked"
    assert result.usable is False
    assert result.content == ""
    assert "shell" in result.error_message.lower()


def test_article_behind_a_reader_header_is_still_usable():
    """Stripping the transport header must not condemn a real article."""
    article = (
        f"Title: 为什么页面停在正在加载中\n\nURL Source: https://example.com/blog/spinner\n\n"
        "Markdown Content:\n## 为什么页面停在正在加载中\n\n"
        "上周我们的详情页一直停在正在加载中，用户反馈很强。\n"
        "排查后发现问题出在网关超时，接口 30 秒没有返回，前端又没有兜底提示。\n"
        "现在超时后会显示错误提示，并记录日志，方便后续定位。\n"
    )
    assert classify_page_shell(article) is None
    assert _is_usable_page_text(article) is True


# ── classifier: the three signals are all required ────────────────────────

def test_footer_alone_is_not_enough():
    body = "B O S S\n正在加载中...\n"
    assert classify_page_shell(body) is None


def test_loading_notice_alone_is_not_enough():
    body = "B O S S\n正在加载中...\n© copyright BOSS直聘 京ICP备14013441号-5"
    without_notice = body.replace("正在加载中...", "资料整理中")
    assert classify_page_shell(without_notice) is None


def test_a_long_body_is_never_condemned_for_the_same_wording():
    """The gate is short by construction; a page this long has real content."""
    filler = (
        "岗位职责：负责公司内部数据平台的建设与维护，参与需求评审、方案设计和上线。"
        "任职要求：熟悉 Python 与 SQL，具备良好的沟通能力。"
    )
    body = f"{BOSS_LOADING_FLAT}\n{filler * 6}"
    assert len(body) > 400
    assert classify_page_shell(body) is None


# ── classifier: no false positives on documents ───────────────────────────


@pytest.mark.parametrize("name", sorted(DOCUMENT_BODIES))
def test_documents_that_mention_loading_are_not_shells(name):
    body = DOCUMENT_BODIES[name]
    assert classify_page_shell(body) is None, name


@pytest.mark.parametrize(
    "name",
    [
        "zh_docs_about_loading",
        "zh_short_loading_doc",
        "zh_short_prose_copyright",
        "zh_short_note",
        "en_loading_article",
        "en_loading_docs",
        "code_snippet",
        "ja_loading_doc",
        "ko_loading_doc",
    ],
)
def test_documents_stay_usable_evidence(name):
    """Classification *and* usability: a document must survive extraction."""
    body = DOCUMENT_BODIES[name]
    assert _is_usable_page_text(body) is True, name


# ── forwarding contract: the same raw body is withheld, not forwarded ─────


def _p(name: str, help_: str, *, required: bool = False) -> dict:
    return {"name": name, "help": help_, "required": required, "type": "str", "default": None}


def _boss_registry() -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {"read": "agent-reach read <url>"},
        "channels": [
            {
                "name": "boss",
                "description": "BOSS直聘",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "x"},
                "actions": [
                    {
                        "name": "read",
                        "help": "read",
                        "usage": "agent-reach boss read <url>",
                        "params": [_p("target", "", required=True)],
                        "backends": ["public-web"],
                        "public_web": ["zhipin.com/"],
                    }
                ],
            }
        ],
    }


def _boss_envelope(body: str, title: str) -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "channel": "boss",
        "action": "read",
        "backend": "public-web",
        "items": [
            {
                "title": title,
                "url": BOSS_JOB_URL,
                "author": None,
                "published_at": "2026-10-28T12:31:00+08:00",
                "text": body,
                "raw": {"completeness_verified": False},
            }
        ],
        "meta": {
            "elapsed_ms": 1822,
            "attempts": [{"backend": "public-web/jina", "result": "ok", "message": None}],
        },
        "error": None,
    }


def _public_backend(tmp_path, response: dict) -> reach.AgentReachBackend:
    """The real backend, driven by a stub executable that replays the payload."""

    def run(argv, *, timeout, env):
        if list(argv)[1:] == ["channels"]:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(_boss_registry()), stderr=""
            )
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(response, ensure_ascii=False), stderr=""
        )

    stub = tmp_path / "agent-reach"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    return reach.AgentReachBackend(str(stub), runner=run, env={})


@pytest.mark.parametrize("body", [BOSS_LOADING_FLAT, BOSS_LOADING_MULTILINE])
def test_public_boss_read_withholds_the_loading_body(tmp_path, body):
    """Upstream said ok:true with one item; Trailhead must not report a read."""
    response = _boss_envelope(body, BOSS_LOADING_TITLE)
    result = _public_backend(tmp_path, response).execute(
        "boss", "read", {"target": BOSS_JOB_URL}
    ).to_dict()

    assert result["ok"] is False
    assert result["items"] == []
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["blocked"]
    assert result["error"]["withheld_items"] == 1
    # The rejection is attributed and the attempt chain survives: the caller can
    # see that upstream answered and that nothing usable came back.
    assert result["provenance"]["attribution"] == ATTRIBUTION
    assert result["provenance"]["reported_backend"] == "public-web"
    assert result["attempts"] == [
        {"backend": "public-web/jina", "result": "ok", "message": None}
    ]
    assert any("withheld" in note for note in result["limitations"])
    # The loading template never reaches the caller as evidence.
    assert BOSS_LOADING_TITLE not in json.dumps(result["items"], ensure_ascii=False)
    assert "正在加载中" not in json.dumps(result["items"], ensure_ascii=False)


def test_public_boss_read_still_forwards_a_real_description(tmp_path):
    """The same route with a real body is forwarded unchanged — no over-reach."""
    description = (
        "岗位职责：负责保洁区域的日常清洁与维护，按派单就近上门。\n"
        "任职要求：身体健康，能吃苦耐劳，有相关经验者优先。"
    )
    response = _boss_envelope(description, "「南京花园小区保洁」_清熹家政招聘-BOSS直聘")
    result = _public_backend(tmp_path, response).execute(
        "boss", "read", {"target": BOSS_JOB_URL}
    ).to_dict()

    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["text"] == description
