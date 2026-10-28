"""Contracts for Jina/DuckDuckGo snippet recovery and explicit ranking criteria.

Two things are pinned here.

1. ``jina_duckduckgo`` does return snippets; they are the link *text* of a
   snippet line, which sits two blocks (heading, favicon+display-URL, snippet)
   below the result heading and is separated from it by blank lines.  The old
   reader stopped at the first blank line, so every snippet came back empty.
   These tests use the real reader shape, and assert only literal text from the
   response is used — the reader's own ``**highlight**`` markup is stripped, but
   nothing is composed, re-spaced or translated.
2. Relevance ordering is opt-in.  It is computed from the caller's explicit
   ``preferred_language`` / ``preferred_sources`` and from inspectable URL
   language segments and domains only.  No query keyword is ever read to guess a
   language, and with no criteria the backend order is untouched.
"""
from __future__ import annotations

import json

import pytest

from hermes_trailhead.search import (
    SearchHit,
    execute_search,
    language_from_url,
    language_matches,
    normalize_source,
    order_hits_by_criteria,
    source_matches,
    _parse_markdown_search_results,
)

# One result block exactly as Jina Reader emits it for
# https://r.jina.ai/http://duckduckgo.com/html/?q=... (captured 2026-10-28,
# rut= hashes shortened, nothing else edited).
REAL_JINA_EN = """Title: requests HTTP library at DuckDuckGo

URL Source: http://duckduckgo.com/html/?q=requests+HTTP+library

Markdown Content:
[](http://duckduckgo.com/html/?q=requests+HTTP+library)

## [Requests: HTTP for Humans™ — Requests 2.34.2 documentation](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python%2Drequests.org%2Fen%2Fmaster%2Findex.html&rut=6e93)

[![Image 1](http://external-content.duckduckgo.com/ip3/docs.python-requests.org.ico)](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python%2Drequests.org%2Fen%2Fmaster%2Findex.html&rut=6e93)[docs.python-requests.org/en/master/index.html](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python%2Drequests.org%2Fen%2Fmaster%2Findex.html&rut=6e93)

[**Requests**: **HTTP** for Humans™ ¶ Release v2.34.2. (Installation) **Requests** is an elegant and simple **HTTP****library** for Python, built for human beings.](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python%2Drequests.org%2Fen%2Fmaster%2Findex.html&rut=6e93)

## [requests · PyPI](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Frequests%2F&rut=ab6f)

[![Image 2](http://external-content.duckduckgo.com/ip3/pypi.org.ico)](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Frequests%2F&rut=ab6f)[pypi.org/project/requests/](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Frequests%2F&rut=ab6f)

[**Requests****Requests** is a simple, yet elegant, **HTTP****library**. ... **Requests** allows you to send HTTP/1.1 **requests** extremely easily.](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Frequests%2F&rut=ab6f)

## [GitHub - psf/requests: A simple, yet elegant, HTTP library.](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpsf%2Frequests&rut=8f8f)

[![Image 3](http://external-content.duckduckgo.com/ip3/github.com.ico)](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpsf%2Frequests&rut=8f8f)[github.com/psf/requests](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpsf%2Frequests&rut=8f8f)

[A simple, yet elegant, **HTTP****library**. Contribute to psf/**requests** development by creating an account on GitHub.](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpsf%2Frequests&rut=8f8f)
"""

EXPECTED_EN_SNIPPETS = (
    "Requests: HTTP for Humans™ Release v2.34.2. (Installation) Requests is an elegant and simple "
    "HTTPlibrary for Python, built for human beings.",
    "RequestsRequests is a simple, yet elegant, HTTPlibrary. ... Requests allows you to send HTTP/1.1 "
    "requests extremely easily.",
    "A simple, yet elegant, HTTPlibrary. Contribute to psf/requests development by creating an account on GitHub.",
)


# ── 1. Snippet recovery on the real reader shape ─────────────────────────


def test_real_jina_blocks_yield_literal_snippets():
    hits = _parse_markdown_search_results(REAL_JINA_EN, limit=3)

    assert [hit.url for hit in hits] == [
        "https://docs.python-requests.org/en/master/index.html",
        "https://pypi.org/project/requests/",
        "https://github.com/psf/requests",
    ]
    assert tuple(hit.snippet for hit in hits) == EXPECTED_EN_SNIPPETS


def test_snippets_contain_no_markup_or_breadcrumb_residue():
    for hit in _parse_markdown_search_results(REAL_JINA_EN, limit=3):
        assert hit.snippet
        assert "**" not in hit.snippet
        assert "](" not in hit.snippet
        assert "uddg=" not in hit.snippet
        assert "rut=" not in hit.snippet
        assert "r.jina.ai" not in hit.snippet
        assert "¶" not in hit.snippet
        assert "Image" not in hit.snippet
        # the grey breadcrumb line is a URL, never a snippet
        assert not hit.snippet.startswith("docs.python-requests.org")
        assert not hit.snippet.startswith("pypi.org")
        assert not hit.snippet.startswith("github.com")


def test_display_url_line_is_skipped_but_present_in_response():
    assert "[docs.python-requests.org/en/master/index.html](" in REAL_JINA_EN
    hit = _parse_markdown_search_results(REAL_JINA_EN, limit=1)[0]
    assert "docs.python-requests.org/en/master/index.html" not in hit.snippet


def test_block_without_snippet_does_not_borrow_the_next_block():
    markdown = """## [No snippet here](https://example.com/a)

## [Has snippet](https://example.com/b)

[Literal snippet text.](https://example.com/b)
"""
    hits = _parse_markdown_search_results(markdown, limit=5)
    assert hits[0].snippet == ""
    assert hits[1].snippet == "Literal snippet text."


def test_unterminated_trailing_snippet_stays_empty_not_invented():
    # Jina truncates the last response mid-line; that line is not a snippet.
    markdown = """## [Complete](https://example.com/a)

[Real snippet.](https://example.com/a)

## [Cut off](https://example.com/b)

[**asyncio** i
"""
    hits = _parse_markdown_search_results(markdown, limit=5)
    assert hits[0].snippet == "Real snippet."
    assert hits[1].snippet == ""


def test_legacy_inline_fixture_format_still_parses():
    markdown = """## [Prusa KB — PLA](https://help.prusa3d.com/article/pla_2062)
PLA is easy to print and low warping.
"""
    hit = _parse_markdown_search_results(markdown, limit=1)[0]
    assert hit.snippet == "PLA is easy to print and low warping."


def test_snippet_length_is_capped():
    long_text = "palabra " * 100
    markdown = f'## [Long](https://example.com/long)\n\n[{long_text}](https://example.com/long)\n'
    assert len(_parse_markdown_search_results(markdown, limit=1)[0].snippet) == 300


# ── 2. URL-language and domain inspection rules ──────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://docs.python.org/zh-cn/3/library/typing.html", "zh-cn"),
        ("https://docs.python.org/es/3/library/asyncio-dev.html", "es"),
        ("https://example.com/pt-BR/guia", "pt-br"),
        ("https://es.wikipedia.org/wiki/Asyncio", "es"),
        ("https://docs.python.org/3/library/asyncio.html", ""),
        ("https://pypi.org/project/requests/", ""),
        ("https://example.com/english/guide", ""),
        ("https://www.es.com/page", ""),  # two labels: leftmost is not a language
        ("https://example.com/xx/unknown-code", ""),
        ("https://example.com", ""),
        ("not a url", ""),
    ],
)
def test_language_from_url_reads_segments_only(url, expected):
    assert language_from_url(url) == expected


def test_language_match_is_subtag_prefix_and_never_folds_script_or_region():
    assert language_matches("zh-cn", "zh") is True
    assert language_matches("es", "es") is True
    assert language_matches("zh-hans", "zh-cn") is False
    assert language_matches("", "es") is False
    assert language_matches("es", "") is False


@pytest.mark.parametrize(
    "url,source,expected",
    [
        ("https://docs.python.org/3/library/x.html", "docs.python.org", True),
        ("https://docs.python.org/3/library/x.html", "python.org", True),
        ("https://docs.python.org/3/library/x.html", "https://www.docs.python.org/3/", True),
        ("https://notdocs.python.org/x", "docs.python.org", False),
        ("https://python.org.evil.example/x", "python.org", False),
        ("https://example.com/x", "", False),
    ],
)
def test_source_match_is_domain_scoped(url, source, expected):
    assert source_matches(url, source) is expected


def test_normalize_source_strips_scheme_path_port_and_www():
    assert normalize_source("HTTPS://WWW.Example.COM:8443/a/b") == "example.com"


# ── 3. Ordering: opt-in, stable, criteria-only ───────────────────────────

ES_HITS = (
    SearchHit(title="asyncio EN", url="https://docs.python.org/3/library/asyncio.html"),
    SearchHit(title="asyncio ES", url="https://docs.python.org/es/3/library/asyncio-dev.html"),
    SearchHit(title="overview EN", url="https://docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html"),
    SearchHit(title="blog ES", url="https://todopython.com/es/asyncio-python/"),
)


def test_no_criteria_keeps_backend_order_exactly():
    ordered, records = order_hits_by_criteria(ES_HITS)
    assert ordered == ES_HITS
    assert [record["language_match"] for record in records] == [False] * len(ES_HITS)
    assert [record["url_language"] for record in records] == ["", "es", "", "es"]


def test_preferred_language_moves_matching_hits_first_and_keeps_relative_order():
    ordered, _ = order_hits_by_criteria(ES_HITS, preferred_language="es")
    assert [hit.title for hit in ordered] == ["asyncio ES", "blog ES", "asyncio EN", "overview EN"]


def test_preferred_language_does_not_drop_or_duplicate_hits():
    ordered, _ = order_hits_by_criteria(ES_HITS, preferred_language="es")
    assert sorted(hit.url for hit in ordered) == sorted(hit.url for hit in ES_HITS)


def test_source_criterion_alone_orders_by_domain():
    hits = (
        SearchHit(title="third party", url="https://todopython.com/es/asyncio-python/"),
        SearchHit(title="official", url="https://docs.python.org/es/3/library/asyncio-dev.html"),
    )
    ordered, records = order_hits_by_criteria(hits, preferred_sources=("docs.python.org",))
    assert [hit.title for hit in ordered] == ["official", "third party"]
    assert records[0]["source_matches"] == ["docs.python.org"]


def test_language_takes_precedence_over_source():
    hits = (
        SearchHit(title="en official", url="https://docs.python.org/3/library/asyncio.html"),
        SearchHit(title="es third party", url="https://todopython.com/es/asyncio-python/"),
        SearchHit(title="es official", url="https://docs.python.org/es/3/library/asyncio-dev.html"),
    )
    ordered, _ = order_hits_by_criteria(
        hits, preferred_language="es", preferred_sources=("docs.python.org",)
    )
    assert [hit.title for hit in ordered] == ["es official", "es third party", "en official"]


def test_unknown_language_request_changes_nothing_and_claims_nothing():
    ordered, records = order_hits_by_criteria(ES_HITS, preferred_language="ja")
    assert ordered == ES_HITS
    assert all(record["language_match"] is False for record in records)


# ── 4. Integration: execution API, defaults and JSON compatibility ───────

ZH_QUERY = "Python类型提示"
ZH_MARKDOWN = """## [Python 类型注解（Type Hints） - 菜鸟教程](https://www.runoob.com/python3/python-type-hints.html)

[Python 类型注解是一种为代码添加说明标签的技术。](https://www.runoob.com/python3/python-type-hints.html)

## [typing --- 对类型提示的支持 — Python 3.15.2 文档](https://docs.python.org/zh-cn/3/library/typing.html)

[Learn how to use the typing module to add type annotations to your Python code.](https://docs.python.org/zh-cn/3/library/typing.html)
"""


def _fetch_zh(url, timeout):
    return ZH_MARKDOWN


def test_execute_search_defaults_are_unchanged_for_multilingual_query():
    executed = execute_search("web", ZH_QUERY, limit=2, fetch=_fetch_zh)
    execution = executed.executions[0]

    assert [hit.url for hit in execution.hits] == [
        "https://www.runoob.com/python3/python-type-hints.html",
        "https://docs.python.org/zh-cn/3/library/typing.html",
    ]
    assert execution.preferred_language == ""
    assert execution.preferred_sources == ()
    payload = execution.to_dict()
    assert payload["preferred_language"] == ""
    assert payload["preferred_sources"] == []
    assert payload["criteria_matches"][0]["url_language"] == ""
    assert payload["criteria_matches"][1]["url_language"] == "zh-cn"


def test_query_language_is_never_inferred_from_the_query_text():
    """A Chinese query with no criteria must not be silently re-ranked."""
    default_run = execute_search("web", ZH_QUERY, limit=2, fetch=_fetch_zh).executions[0]
    assert [hit.url for hit in default_run.hits][0].startswith("https://www.runoob.com")

    explicit_run = execute_search(
        "web", ZH_QUERY, limit=2, fetch=_fetch_zh, preferred_language="zh"
    ).executions[0]
    assert [hit.url for hit in explicit_run.hits][0] == "https://docs.python.org/zh-cn/3/library/typing.html"


def test_explicit_criteria_are_visible_in_execution_json():
    execution = execute_search(
        "web", ZH_QUERY, limit=2, fetch=_fetch_zh, preferred_language="zh-cn", preferred_sources=("docs.python.org",)
    ).executions[0]
    payload = execution.to_dict()

    json.dumps(payload)  # must stay serialisable for --format json
    assert payload["preferred_language"] == "zh-cn"
    assert payload["preferred_sources"] == ["docs.python.org"]
    assert payload["criteria_matches"] == [
        {
            "url": "https://docs.python.org/zh-cn/3/library/typing.html",
            "url_language": "zh-cn",
            "language_match": True,
            "source_matches": ["docs.python.org"],
        },
        {
            "url": "https://www.runoob.com/python3/python-type-hints.html",
            "url_language": "",
            "language_match": False,
            "source_matches": [],
        },
    ]


def test_hit_json_keeps_legacy_three_keys_after_reordering():
    execution = execute_search(
        "web", ZH_QUERY, limit=2, fetch=_fetch_zh, preferred_language="zh"
    ).executions[0]
    for hit in execution.to_dict()["hits"]:
        assert set(hit) == {"title", "url", "snippet"}


def test_reordering_preserves_snippets_attached_to_their_own_hit():
    execution = execute_search("web", ZH_QUERY, limit=2, fetch=_fetch_zh, preferred_language="zh").executions[0]
    by_url = {hit.url: hit.snippet for hit in execution.hits}
    assert by_url["https://docs.python.org/zh-cn/3/library/typing.html"].startswith("Learn how to use the typing")
    assert by_url["https://www.runoob.com/python3/python-type-hints.html"].startswith("Python 类型注解")
