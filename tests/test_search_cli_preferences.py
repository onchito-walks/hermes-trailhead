"""CLI contracts for explicit search preferences and real snippet rendering.

What is pinned here:

1. ``--prefer-language TAG`` and repeatable ``--prefer-source HOST`` reach
   ``search.execute_search(preferred_language=..., preferred_sources=...)``
   after normalisation — no criteria are inferred from the query or from the
   platform, and nothing is filtered out.
2. Text output prints the snippet the engine actually returned (bounded at the
   same 300 characters the parser stores) and prints nothing when the engine
   returned no snippet — no composed or borrowed text.
3. Malformed tag/host values are usage errors (exit 2) instead of being
   silently dropped, because the URL matcher could never satisfy them.
4. A ``Namespace`` without the new attributes behaves exactly like the CLI
   before the flags existed (``getattr`` defaults, empty criteria).

No network is touched: the real ``execute_search`` runs with an injected
``fetch`` fixture, and extraction is switched off with ``--no-extract``.
"""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from hermes_trailhead import cli as cli_module
from hermes_trailhead.cli import main
from hermes_trailhead.search import execute_search

EN_URL = "https://docs.python.org/3/library/asyncio.html"
ES_URL = "https://docs.python.org/es/3/library/asyncio-dev.html"
EN_SNIPPET = "The event loop is the core of every asyncio application."
ES_SNIPPET = "El bucle de eventos es el núcleo de toda aplicación asyncio."

# English result first, Spanish result second: a preference for "es" has to move
# the second hit up, and a run without criteria has to leave it where it is.
MD = f"""## [asyncio EN]({EN_URL})

[{EN_SNIPPET}]({EN_URL})

## [asyncio ES]({ES_URL})

[{ES_SNIPPET}]({ES_URL})
"""

ZH_URL = "https://docs.python.org/zh-cn/3/library/typing.html"
RUNOOB_URL = "https://www.runoob.com/python3/python-type-hints.html"
MD_ZH = f"""## [Python 类型注解 - 菜鸟教程]({RUNOOB_URL})

[Python 类型注解是一种为代码添加说明标签的技术。]({RUNOOB_URL})

## [typing --- 对类型提示的支持]({ZH_URL})

[Learn how to use the typing module to add type annotations.]({ZH_URL})
"""


class _Fetch:
    """Record every engine fetch so 'no extra engine call' is measurable."""

    def __init__(self, markdown: str) -> None:
        self.markdown = markdown
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: int) -> str:
        self.calls.append(url)
        return self.markdown


@pytest.fixture
def install_fetch(monkeypatch):
    """Replace cli.execute_search with the real one plus a fixture fetcher."""

    def install(markdown: str = MD) -> _Fetch:
        fetcher = _Fetch(markdown)

        def wrapper(*args, **kwargs):
            kwargs["fetch"] = fetcher
            return execute_search(*args, **kwargs)

        monkeypatch.setattr(cli_module, "execute_search", wrapper)
        return fetcher

    return install


def _json_run(capsys, argv: list[str]) -> dict:
    rc = main(argv)
    out = capsys.readouterr().out
    assert rc == 0
    return json.loads(out)


def _stub_executed(hits=()) -> SimpleNamespace:
    execution = SimpleNamespace(
        platform="web",
        status="ok",
        result_count=len(hits),
        engine="fixture",
        attribution="",
        caveat="",
        error="",
        hits=list(hits),
    )
    return SimpleNamespace(
        plan=SimpleNamespace(query="asyncio", paid_api_required=False),
        executions=(execution,),
    )


# ── 1. Flags exist and stay explicit ─────────────────────────────────────


def test_parser_defaults_are_explicitly_empty():
    args = cli_module.build_parser().parse_args(["search", "web", "asyncio"])
    assert args.preferred_language == ""
    assert args.preferred_sources == []


def test_parser_accepts_repeatable_prefer_source():
    args = cli_module.build_parser().parse_args(
        [
            "search",
            "web",
            "asyncio",
            "--prefer-language",
            "zh_CN",
            "--prefer-source",
            "docs.python.org",
            "--prefer-source",
            "https://www.pypi.org/project/",
        ]
    )
    assert args.preferred_language == "zh_CN"
    assert args.preferred_sources == ["docs.python.org", "https://www.pypi.org/project/"]


def test_cmd_search_forwards_normalised_deduplicated_preferences(monkeypatch, capsys):
    calls = []
    executed = _stub_executed()

    def fake_search_execute_data(platform, query, **kwargs):
        calls.append((platform, query, kwargs))
        return executed

    monkeypatch.setattr(cli_module, "search_execute_data", fake_search_execute_data)
    rc = main(
        [
            "search",
            "web",
            "asyncio",
            "--execute",
            "--no-extract",
            "--limit",
            "4",
            "--prefer-language",
            "ZH_CN",
            "--prefer-source",
            "https://www.Docs.Python.org:443/3/library/",
            "--prefer-source",
            "docs.python.org",
        ]
    )

    assert rc == 0
    ((platform, query, kwargs),) = calls
    assert (platform, query) == ("web", "asyncio")
    assert kwargs["preferred_language"] == "zh-cn"
    assert kwargs["preferred_sources"] == ("docs.python.org",)  # normalised + deduped
    assert kwargs["limit"] == 4
    assert kwargs["live"] is False


def test_search_execute_data_forwards_preferences_and_keeps_defaults(monkeypatch):
    seen = {}

    def fake_execute_search(platform, query, **kwargs):
        seen["call"] = (platform, query, kwargs)
        return "sentinel"

    monkeypatch.setattr(cli_module, "execute_search", fake_execute_search)

    assert (
        cli_module.search_execute_data(
            "web", "asyncio", limit=2, preferred_language="es", preferred_sources=("docs.python.org",)
        )
        == "sentinel"
    )
    assert seen["call"] == (
        "web",
        "asyncio",
        {
            "live": False,
            "limit": 2,
            "preferred_language": "es",
            "preferred_sources": ("docs.python.org",),
        },
    )

    seen.clear()
    cli_module.search_execute_data("web", "asyncio")
    assert seen["call"][2]["preferred_language"] == ""
    assert seen["call"][2]["preferred_sources"] == ()


# ── 2. Text output: real snippets, bounded, never invented ───────────────


def test_text_prints_returned_snippets_in_backend_order(install_fetch, capsys):
    install_fetch()
    rc = main(["search", "web", "asyncio", "--execute", "--no-extract"])
    out = capsys.readouterr().out

    assert rc == 0
    assert f"snippet: {EN_SNIPPET}" in out
    assert f"snippet: {ES_SNIPPET}" in out
    assert out.index(EN_URL) < out.index(ES_URL)  # no criteria: order untouched
    assert "Preferences:" not in out


def test_text_snippet_is_bounded_to_300_characters(monkeypatch, capsys):
    long_snippet = "palabra " * 60  # 480 characters
    hit = SimpleNamespace(title="Long snippet", url="https://example.com/long", snippet=long_snippet)
    monkeypatch.setattr(cli_module, "search_execute_data", lambda *a, **k: _stub_executed((hit,)))

    rc = main(["search", "web", "asyncio", "--execute", "--no-extract"])
    out = capsys.readouterr().out

    assert rc == 0
    line = next(line for line in out.splitlines() if line.strip().startswith("snippet:"))
    printed = line.strip()[len("snippet: ") :]
    assert printed == long_snippet[:300]
    assert len(printed) == 300


@pytest.mark.parametrize("hit", [SimpleNamespace(title="No snippet", url="https://example.com/a", snippet=""), SimpleNamespace(title="Older hit object", url="https://example.com/b")])
def test_absent_snippet_prints_no_snippet_line(monkeypatch, capsys, hit):
    monkeypatch.setattr(cli_module, "search_execute_data", lambda *a, **k: _stub_executed((hit,)))

    rc = main(["search", "web", "asyncio", "--execute", "--no-extract"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "snippet:" not in out
    assert hit.url in out


def test_text_reports_preference_and_keeps_every_hit(install_fetch, capsys):
    install_fetch()
    rc = main(["search", "web", "asyncio", "--execute", "--no-extract", "--prefer-language", "es"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Preferences: language=es" in out
    assert "Ordering only: these criteria never remove a hit" in out
    assert "Criteria matches: 1/2 hits" in out
    assert out.index(ES_URL) < out.index(EN_URL)  # preferred hit moved up
    assert out.count("snippet:") == 2  # nothing filtered, nothing duplicated


# ── 3. JSON: metadata from SearchExecution, still one engine call ────────


def test_json_execution_carries_preference_metadata(install_fetch, capsys):
    install_fetch()
    payload = _json_run(
        capsys,
        [
            "search",
            "web",
            "asyncio",
            "--execute",
            "--no-extract",
            "--format",
            "json",
            "--prefer-language",
            "es",
            "--prefer-source",
            "docs.python.org",
        ],
    )
    execution = payload["executions"][0]

    assert execution["preferred_language"] == "es"
    assert execution["preferred_sources"] == ["docs.python.org"]
    assert [hit["url"] for hit in execution["hits"]] == [ES_URL, EN_URL]
    assert set(execution["hits"][0]) == {"title", "url", "snippet"}  # legacy hit keys
    assert execution["hits"][0]["snippet"] == ES_SNIPPET  # snippet follows its hit
    assert execution["criteria_matches"][0]["url_language"] == "es"
    assert execution["criteria_matches"][0]["source_matches"] == ["docs.python.org"]


def test_criteria_do_not_add_an_engine_call(install_fetch, capsys):
    plain_fetcher = install_fetch()
    _json_run(capsys, ["search", "web", "asyncio", "--execute", "--no-extract", "--format", "json"])
    plain_calls = len(plain_fetcher.calls)

    criteria_fetcher = install_fetch()
    _json_run(
        capsys,
        [
            "search",
            "web",
            "asyncio",
            "--execute",
            "--no-extract",
            "--format",
            "json",
            "--prefer-language",
            "es",
            "--prefer-source",
            "docs.python.org",
        ],
    )

    assert plain_calls > 0
    assert len(criteria_fetcher.calls) == plain_calls


def test_query_language_is_never_inferred_at_the_cli(install_fetch, capsys):
    install_fetch(MD_ZH)
    payload = _json_run(capsys, ["search", "web", "Python类型提示", "--execute", "--no-extract", "--format", "json"])
    execution = payload["executions"][0]

    assert execution["preferred_language"] == ""
    assert execution["preferred_sources"] == []
    assert [hit["url"] for hit in execution["hits"]] == [RUNOOB_URL, ZH_URL]

    install_fetch(MD_ZH)
    explicit = _json_run(
        capsys,
        ["search", "web", "Python类型提示", "--execute", "--no-extract", "--format", "json", "--prefer-language", "zh"],
    )
    assert [hit["url"] for hit in explicit["executions"][0]["hits"]] == [ZH_URL, RUNOOB_URL]


def test_valid_but_unmatched_tag_changes_nothing(install_fetch, capsys):
    install_fetch()
    payload = _json_run(
        capsys,
        ["search", "web", "asyncio", "--execute", "--no-extract", "--format", "json", "--prefer-language", "ja"],
    )
    execution = payload["executions"][0]

    assert execution["preferred_language"] == "ja"
    assert [hit["url"] for hit in execution["hits"]] == [EN_URL, ES_URL]


# ── 4. Malformed values are usage errors, not silent no-ops ──────────────


@pytest.mark.parametrize("value", ["english", "e", "zh-cn-", "zh_CN_extra", "123", "zh--cn"])
def test_invalid_language_tag_is_a_usage_error(monkeypatch, capsys, value):
    def must_not_execute(*args, **kwargs):
        raise AssertionError("an invalid tag must not reach the engine")

    monkeypatch.setattr(cli_module, "execute_search", must_not_execute)
    rc = main(["search", "web", "asyncio", "--execute", "--no-extract", "--prefer-language", value])

    err = capsys.readouterr().err
    assert rc == 2
    assert "--prefer-language" in err
    assert "'es'" in err and "'zh-cn'" in err


@pytest.mark.parametrize("value", ["not a host", "localhost", "", "docs..python.org", "bad_host.example.com", "http://"])
def test_invalid_source_is_a_usage_error(monkeypatch, capsys, value):
    def must_not_execute(*args, **kwargs):
        raise AssertionError("an invalid source must not reach the engine")

    monkeypatch.setattr(cli_module, "execute_search", must_not_execute)
    rc = main(["search", "web", "asyncio", "--execute", "--no-extract", "--prefer-source", value])

    err = capsys.readouterr().err
    assert rc == 2
    assert "--prefer-source" in err
    assert "docs.python.org" in err


# ── 5. Namespace compatibility (pre-flag callers) ────────────────────────


def test_plan_namespace_without_preference_attributes_still_works(capsys):
    args = argparse.Namespace(platform="web", query="asyncio", execute=False, format="text", live=False, limit=3)
    rc = cli_module.cmd_search(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Preferences:" not in out


def test_execute_namespace_without_preference_attributes_means_no_criteria(monkeypatch, capsys):
    calls = []

    def fake_search_execute_data(platform, query, **kwargs):
        calls.append(kwargs)
        return _stub_executed()

    monkeypatch.setattr(cli_module, "search_execute_data", fake_search_execute_data)
    args = argparse.Namespace(
        platform="web", query="asyncio", execute=True, format="text", live=False, limit=3, extract=False
    )

    assert cli_module.cmd_search(args) == 0
    assert calls[0]["preferred_language"] == ""
    assert calls[0]["preferred_sources"] == ()
    assert "Preferences:" not in capsys.readouterr().out
