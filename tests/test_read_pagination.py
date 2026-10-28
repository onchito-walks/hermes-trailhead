"""Contracts for truthful long-document `read --offset/--max-chars` pagination.

The public typing reference is a long Chinese document with no ASCII word
spacing.  These tests freeze its marker set and prove, without the network,
that successive windows reconstruct the available extracted document with no
gap and no overlap.  They also pin the bounds and the shell-classification
regression that made short CJK HTML bodies look like client-rendered shells.
"""
from __future__ import annotations

import json

import pytest

from hermes_trailhead import cli
from hermes_trailhead import extract as extract_mod
from hermes_trailhead.cli import main
from hermes_trailhead.extract import (
    ExtractedHit,
    ExtractionResult,
    _as_readable_page_text,
    _html_to_readable_text,
    _is_html_shell,
    _readable_page_result,
    classify_page_shell,
    retrieval_char_limit,
    retrieval_scope,
)

URL = "https://docs.python.org/zh-cn/3/library/typing.html"

#: Markers frozen from the public Chinese `typing` reference (docs.python.org
#: zh-cn).  The first window of the live page contains 类型提示 ×6, typing ×37,
#: 泛型 ×34 in the 2026-10-28 read; the deterministic fixture below carries the
#: same vocabulary so the contract is testable offline.
FROZEN_MARKERS = ("类型提示", "typing", "泛型", "协议", "PEP 673")

_SENTENCES = (
    "类型提示让函数签名表达参数与返回值的预期类型，类型检查器可以据此发现不一致。",
    "泛型允许同一段代码复用于不同的元素类型，同时保留静态检查的精度。",
    "协议描述结构化子类型要求的方法集合，任何满足该集合的类型都可以传入。",
    "类型别名把复杂的注解折叠成一个名字，阅读代码时不必反复展开完整签名。",
    "标注可调用对象时要写清参数列表与返回类型，否则检查器只能退化为任意类型。",
    "联合类型表示一个值可能是几种类型之一，收窄分支之后才能访问共有成员。",
    "typing 模块提供类型提示所需的特殊类型原语与工具函数。",
)


def _build_frozen_document(sections: int = 1000) -> str:
    """A long, deterministic Chinese typing reference with frozen markers."""
    lines: list[str] = []
    for index in range(sections):
        sentence = _SENTENCES[index % len(_SENTENCES)]
        lines.append(
            f"第 {index:03d} 节 类型提示：{sentence} 本节编号 {index:04d} 唯一。"
        )
        if index % 37 == 0:
            lines.append(f"第 {index:03d} 节补充：泛型参数可以带默认值 {index}。")
        if index == sections // 2:
            lines.append("PEP 673 引入了 Self 类型，用于标注返回实例自身的方法。")
    return "\n".join(lines)


LONG_ZH_DOC = _build_frozen_document()


def _fake_extract(monkeypatch, extraction: ExtractionResult, calls: list | None = None):
    """Replace cli.extract_hits with a one-hit stub; record scope at call time."""

    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        if calls is not None:
            calls.append(
                {
                    "limit": limit,
                    "timeout": timeout,
                    "extract": extract,
                    "fetch": fetch,
                    "retrieval_limit": retrieval_char_limit(),
                }
            )
        return (
            ExtractedHit(
                title=hits[0].title,
                url=hits[0].url,
                snippet=hits[0].snippet,
                extraction=extraction,
            ),
        )

    monkeypatch.setattr(cli, "extract_hits", fake)
    return fake


def _run_json(capsys, argv: list[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured.err


def _read_window(capsys, offset: int, max_chars: int = 20000) -> dict:
    rc, payload, err = _run_json(
        capsys,
        ["read", URL, "--format", "json", "--offset", str(offset), "--max-chars", str(max_chars)],
    )
    assert rc == 0, (payload, err)
    return payload


# ── 1. Windows reconstruct the available document exactly ───────────────


def test_long_cjk_document_is_long_enough_to_page():
    assert len(LONG_ZH_DOC) > 3 * cli.READ_DEFAULT_MAX_CHARS
    for marker in FROZEN_MARKERS:
        assert marker in LONG_ZH_DOC
    assert LONG_ZH_DOC.count("PEP 673") == 1


def test_windows_reconstruct_document_without_gaps_or_overlaps(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=LONG_ZH_DOC,
            content_length=len(LONG_ZH_DOC),
            source_type="docs",
        ),
    )

    windows: list[str] = []
    spans: list[tuple[int, int]] = []
    offset = 0
    seen_offsets: list[int] = []
    for _ in range(10):
        payload = _read_window(capsys, offset)
        page = payload["pagination"]
        assert payload["ok"] is True
        assert page["offset"] == offset
        assert page["start"] == offset
        assert page["end"] == offset + len(payload["content"])
        assert page["returned_chars"] == len(payload["content"])
        assert page["total_available_chars"] == len(LONG_ZH_DOC)
        assert page["end"] <= page["total_available_chars"]
        windows.append(payload["content"])
        spans.append((page["start"], page["end"]))
        seen_offsets.append(offset)
        if not page["more"]:
            assert page["next_offset"] is None
            break
        assert page["next_offset"] == page["end"]
        offset = page["next_offset"]
    else:  # pragma: no cover - a regression would not terminate
        pytest.fail("pagination did not terminate")

    assert len(windows) >= 3
    assert "".join(windows) == LONG_ZH_DOC
    assert seen_offsets == sorted(set(seen_offsets))
    for previous, current in zip(spans, spans[1:]):
        assert previous[1] == current[0], "windows must be contiguous (no gap)"
    assert spans[-1][1] == len(LONG_ZH_DOC)
    assert sum(end - start for start, end in spans) == len(LONG_ZH_DOC)


def test_markers_are_found_across_first_and_later_windows(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=LONG_ZH_DOC,
            content_length=len(LONG_ZH_DOC),
            source_type="docs",
        ),
    )
    first = _read_window(capsys, 0)
    middle = _read_window(capsys, 20000)
    last_offset = first["pagination"]["total_available_chars"] - 1
    last = _read_window(capsys, last_offset, max_chars=20000)

    assert first["content"].count("类型提示") > 0
    assert middle["pagination"]["start"] == 20000
    # The PEP marker sits at the document midpoint, i.e. outside window one.
    assert "PEP 673" not in first["content"]
    assert "PEP 673" in middle["content"] or "PEP 673" in last["content"]
    reconstructed = "".join(
        p["content"]
        for p in (_read_window(capsys, 0), _read_window(capsys, 20000))
    )
    assert FROZEN_MARKERS[0] in reconstructed


def test_default_read_output_is_still_the_first_20k_window(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=LONG_ZH_DOC,
            content_length=len(LONG_ZH_DOC),
            source_type="docs",
        ),
    )
    rc, payload, err = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0 and err == ""
    assert payload["returned_chars"] == cli.READ_DEFAULT_MAX_CHARS
    assert payload["content"] == LONG_ZH_DOC[: cli.READ_DEFAULT_MAX_CHARS]
    assert payload["pagination"]["max_chars"] == cli.READ_DEFAULT_MAX_CHARS
    assert payload["pagination"]["next_offset"] == cli.READ_DEFAULT_MAX_CHARS
    assert payload["truncated"] is True
    assert "more text is available" in payload["truncation_note"]


def test_full_window_claims_only_extracted_completeness(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=LONG_ZH_DOC,
            content_length=len(LONG_ZH_DOC),
            source_type="docs",
        ),
    )
    rc, payload, _ = _run_json(
        capsys,
        ["read", URL, "--format", "json", "--max-chars", str(len(LONG_ZH_DOC))],
    )

    assert rc == 0
    assert payload["content"] == LONG_ZH_DOC
    assert payload["pagination"]["more"] is False
    assert payload["pagination"]["next_offset"] is None
    assert payload["pagination"]["window_empty"] is False
    assert payload["truncated"] is False
    assert payload["completeness"]["extracted_document_complete"] is True
    # Never a claim about the raw page: cleaning removes markup and chrome.
    assert payload["completeness"]["raw_page_complete"] is False
    assert "not the raw HTML" in payload["completeness"]["note"]


def test_offset_beyond_end_is_truthful_not_an_error(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=LONG_ZH_DOC,
            content_length=len(LONG_ZH_DOC),
            source_type="docs",
        ),
    )
    rc, payload, _ = _run_json(
        capsys,
        ["read", URL, "--format", "json", "--offset", str(len(LONG_ZH_DOC) + 50)],
    )

    assert rc == 0
    page = payload["pagination"]
    assert payload["content"] == ""
    assert payload["returned_chars"] == 0
    assert page["start"] == page["end"] == len(LONG_ZH_DOC)
    assert page["more"] is False
    assert page["window_empty"] is True
    assert "beyond the" in page["note"] and "empty" in page["note"]


def test_windows_are_not_reclassified_as_shells(monkeypatch, capsys):
    """A chunk quoting shell vocabulary is still part of a real document."""
    doc = (
        "类型提示文档说明：页面不存在时请返回错误页。\n"
        + "\n".join(
            f"第 {n:03d} 段 协议与泛型：加载中并不表示 404，页面不存在 只是错误文案。"
            for n in range(700)
        )
        + "\nLoading... 也不是内容本身。"
    )
    _fake_extract(
        monkeypatch,
        ExtractionResult(status="ok", content=doc, content_length=len(doc)),
    )
    payload = _read_window(capsys, 20000)

    assert payload["ok"] is True
    assert extract_mod._is_usable_page_text(payload["content"]) is True
    assert classify_page_shell(payload["content"]) is None
    assert payload["pagination"]["more"] is False


# ── 2. Bounds and stable errors ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("flag", "value", "code"),
    [
        ("--offset", "-1", "invalid_offset"),
        ("--offset", "abc", "invalid_offset"),
        ("--offset", "1.5", "invalid_offset"),
        ("--max-chars", "0", "invalid_max_chars"),
        ("--max-chars", "-5", "invalid_max_chars"),
        ("--max-chars", "abc", "invalid_max_chars"),
        (
            "--max-chars",
            str(cli.READ_MAX_WINDOW_CHARS + 1),
            "invalid_max_chars",
        ),
    ],
)
def test_invalid_window_arguments_are_stable_json_errors(
    monkeypatch, capsys, flag, value, code
):
    calls: list[dict] = []
    _fake_extract(monkeypatch, ExtractionResult(status="ok", content=LONG_ZH_DOC), calls)

    rc, payload, err = _run_json(
        capsys, ["read", URL, "--format", "json", flag, value]
    )

    assert rc == 2
    assert err == ""
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert payload["extraction_status"] == "not_attempted"
    assert payload["content"] == ""
    assert "non-negative integer" in payload["error"]["message"] or "between 1 and" in payload["error"]["message"]
    assert calls == []


def test_max_chars_boundary_is_accepted(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(status="ok", content=LONG_ZH_DOC, content_length=len(LONG_ZH_DOC)),
    )
    payload = _read_window(capsys, 0, max_chars=cli.READ_MAX_WINDOW_CHARS)

    assert payload["pagination"]["max_chars"] == cli.READ_MAX_WINDOW_CHARS
    assert payload["returned_chars"] <= cli.READ_MAX_WINDOW_CHARS


def test_window_bounds_are_disclosed_in_every_outcome(monkeypatch, capsys):
    _fake_extract(monkeypatch, ExtractionResult(status="ok", content=LONG_ZH_DOC))
    _, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    page = payload["pagination"]
    assert page["retrieval_char_cap"] == cli.READ_RETRIEVAL_CHAR_CAP
    assert page["transport_byte_cap"] == cli.READ_TRANSPORT_BYTE_CAP
    assert cli.READ_MAX_WINDOW_CHARS < cli.READ_RETRIEVAL_CHAR_CAP
    assert page["transport_byte_cap"] > cli.READ_RETRIEVAL_CHAR_CAP


# ── 3. Extractor / retrieval / transport truncation stay distinct ───────


def test_extractor_truncation_reported_without_window_double_count(monkeypatch, capsys):
    kept, measured = "A" * 5000, 9000
    _fake_extract(
        monkeypatch,
        ExtractionResult(status="ok", content=kept, content_length=measured),
    )
    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["content"] == kept
    assert payload["content_length"] == measured
    assert payload["pagination"]["total_available_chars"] == len(kept)
    assert payload["pagination"]["extractor_truncated"] is True
    assert payload["pagination"]["more"] is False
    assert payload["truncated"] is True
    assert "5000" in payload["truncation_note"]
    assert "9000" in payload["truncation_note"]
    assert "more text is available" not in payload["truncation_note"]


def test_retrieval_cap_is_disclosed_separately_from_the_window(monkeypatch, capsys):
    capped = "B" * cli.READ_RETRIEVAL_CHAR_CAP + "\n..."
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="ok",
            content=capped,
            content_length=len(capped) + 250_000,
            source_type="docs",
        ),
    )
    rc, payload, _ = _run_json(
        capsys, ["read", URL, "--format", "json", "--offset", "999000"]
    )

    assert rc == 0
    page = payload["pagination"]
    assert page["retrieval_capped"] is True
    assert page["total_available_chars"] == len(capped)
    assert page["more"] is False
    assert payload["truncated"] is True
    assert f"{cli.READ_RETRIEVAL_CHAR_CAP}-character retrieval cap" in payload["truncation_note"]
    assert f"{cli.READ_TRANSPORT_BYTE_CAP}-byte transport cap" not in payload["truncation_note"]


def test_transport_cap_is_reported_from_the_fetch_scope(monkeypatch, capsys):
    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        extract_mod._mark_transport_capped("byte_capped")
        return (
            ExtractedHit(
                title="", url=hits[0].url,
                extraction=ExtractionResult(status="ok", content=LONG_ZH_DOC, content_length=len(LONG_ZH_DOC)),
            ),
        )

    monkeypatch.setattr(cli, "extract_hits", fake)
    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["pagination"]["transport_capped"] is True
    assert payload["truncated"] is True
    assert f"{cli.READ_TRANSPORT_BYTE_CAP}-byte transport cap" in payload["truncation_note"]
    assert payload["pagination"]["retrieval_capped"] is False


def test_bounded_body_marks_byte_cap_and_restores_scope():
    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    body = b"x" * 64
    with retrieval_scope(char_limit=100, byte_limit=10) as state:
        assert retrieval_char_limit() == 100
        assert extract_mod._bounded_body(Response(body)) == b"x" * 10
        assert state["byte_capped"] is True
    assert retrieval_char_limit() == extract_mod._READABLE_TEXT_LIMIT
    # Outside the scope the historical unbounded read still applies.
    assert extract_mod._bounded_body(Response(body)) == body


def test_read_widens_retrieval_only_inside_the_call(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(
        monkeypatch,
        ExtractionResult(status="ok", content=LONG_ZH_DOC, content_length=len(LONG_ZH_DOC)),
        calls,
    )
    before = retrieval_char_limit()
    _run_json(capsys, ["read", URL, "--format", "json", "--offset", "20000"])

    assert before == extract_mod._READABLE_TEXT_LIMIT
    assert calls[0]["retrieval_limit"] == cli.READ_RETRIEVAL_CHAR_CAP
    assert retrieval_char_limit() == extract_mod._READABLE_TEXT_LIMIT


def test_plain_text_is_bounded_by_the_same_retrieval_limit():
    """Non-HTML bodies must honour the declared cap instead of passing through."""
    text = "plain paragraph line\n" * 40
    stats: dict = {}
    bounded = _as_readable_page_text(text, limit=100, stats=stats)

    assert len(bounded) <= 100 + len("\n...")
    assert bounded.startswith(text[:99])
    assert bounded.endswith("\n...")
    assert stats == {"total_chars": len(text), "capped": True}
    assert _as_readable_page_text("short text", limit=100) == "short text"


def test_readable_text_limit_and_stats_are_explicit():
    html = "<html><body>" + "".join(
        f"<p>Paragraph {n} carries enough distinct words to be usable prose here.</p>"
        for n in range(400)
    ) + "</body></html>"
    default = _html_to_readable_text(html)
    stats: dict = {}
    widened = _html_to_readable_text(html, limit=100_000, stats=stats)

    assert len(default) <= extract_mod._READABLE_TEXT_LIMIT + 4
    assert default.endswith("...")
    assert len(widened) > extract_mod._READABLE_TEXT_LIMIT
    assert stats["total_chars"] == len(widened)
    assert stats["capped"] is False


# ── 4. F8 non-English shell assessment (fixtures, conservative) ─────────


_ZH_HTML_DOC = (
    "<!DOCTYPE html><html lang='zh-CN'><head><title>快速开始</title></head><body>"
    "<h1>快速开始</h1>"
    + "".join(
        f"<p>安装依赖之后运行命令创建索引，索引会为每一行生成条目，条目写入之后即可查询第{n}节。</p>"
        for n in range(8)
    )
    + "<p>更多内容参见文档目录，协议与泛型章节还说明了类型别名的限制。</p>"
    "</body></html>"
)

_ZH_HTML_SHELL = (
    "<!DOCTYPE html><html lang='zh-CN'><body><div class='app'>"
    "<button>登录</button><button>注册</button><div>加载中</div>"
    "<div>查询结果</div><div>暂无数据</div>"
    "</div></body></html>"
)

_SHORT_EN_SHELL = (
    "<!DOCTYPE html><html><body><div id='app'><nav>Home Login Signup</nav>"
    "<div class='spinner'>Loading...</div></div></body></html>"
)


def test_short_cjk_html_document_is_not_a_shell():
    """A CJK page under 25 whitespace tokens is still a document, not a shell.

    Reproduces the non-English false positive in the short-body gate: Chinese
    writes without spaces, so the historical word count saw a nearly empty
    body.  Positive prose evidence (sustained CJK text plus sentence marks) is
    the narrow fix; nothing about label-only shells changed.
    """
    cleaned = extract_mod._clean_html_text(_ZH_HTML_DOC)
    assert len(cleaned.split()) < 25
    assert extract_mod._looks_like_cjk_prose(cleaned) is True
    assert _is_html_shell(_ZH_HTML_DOC) is False
    assert _readable_page_result(_ZH_HTML_DOC) != ""
    assert extract_mod._is_usable_page_text(_readable_page_result(_ZH_HTML_DOC))


def test_cjk_label_shell_is_still_rejected():
    cleaned = extract_mod._clean_html_text(_ZH_HTML_SHELL)
    assert extract_mod._looks_like_cjk_prose(cleaned) is False
    assert _is_html_shell(_ZH_HTML_SHELL) is True
    assert _readable_page_result(_ZH_HTML_SHELL) == ""


def test_short_latin_shell_is_still_rejected():
    assert _is_html_shell(_SHORT_EN_SHELL) is True


def test_legitimate_chinese_article_quoting_missing_page_is_not_condemned():
    """F8: do not widen literal marker matching; keep the F4 middle band."""
    article = (
        "排查 404 的笔记：用户反馈页面不存在，我们先确认路由是否注册。"
        + "随后检查静态资源与反向代理，页面不存在 往往只是缓存过期。" * 40
    )
    assert 800 < len(article) <= 2000
    assert classify_page_shell(article) is None
    assert extract_mod._is_usable_page_text(article) is True
