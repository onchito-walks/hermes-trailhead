"""Regression tests for the Agent Reach forwarding false-success bug.

The pinned public sweep (``trailhead-40-action-live.json``, 2026-10-28) recorded
four ``returned_items`` rows whose items were *not* the artifact the action
promised:

* ``reddit read`` — Jina relayed "You've been blocked by network security".
* ``xiaohongshu read`` — the note link resolved to "你访问的页面不见了".
* ``linkedin read`` — a job URL returned LinkedIn's multilingual 404 page.

``reach_backend._interpret`` reported all three as ``ok: true`` with items.  The
same sweep recorded metadata-only actions (``v2ex user``, ``bilibili hot``,
``xueqiu search``) whose empty ``text`` is legitimate — those must keep working.

Fixtures are the verbatim bodies saved from that run
(``tests/fixtures/reach_page_shells.json``), so the shell shapes stay real
instead of becoming tidied-up strings that never occur upstream.
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from hermes_trailhead import reach_backend as reach
from hermes_trailhead.extract import _is_usable_page_text, classify_page_shell
from hermes_trailhead.scoring import ScoredHit, SourceQuality, score_hit, assess_evidence

FIXTURES = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "reach_page_shells.json").read_text(
        encoding="utf-8"
    )
)["cases"]

ATTRIBUTION = "Agent Reach (third-party CLI), forwarded by Hermes Trailhead"


# ── registry / runner fixtures ────────────────────────────────────────────


def _p(name: str, help_: str, *, required: bool = False, type_: str = "str", default=None) -> dict:
    return {"name": name, "help": help_, "required": required, "type": type_, "default": default}


def _action(name: str, params, *, public_web=(), backends=()) -> dict:
    return {
        "name": name,
        "help": name,
        "usage": f"agent-reach {name}",
        "params": params,
        "backends": list(backends),
        "public_web": list(public_web),
    }


def registry_payload() -> dict:
    """The pinned upstream shape, trimmed to the channels these tests drive."""
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {"read": "agent-reach read <url>"},
        "channels": [
            {
                "name": "reddit",
                "description": "Reddit",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "x"},
                "actions": [
                    _action("search", [_p("query", "", required=True), _p("limit", "", type_="int")],
                            public_web=["reddit.com/r/"], backends=["opencli"]),
                    _action("read", [_p("target", "", required=True)],
                            public_web=["reddit.com/r/", "redd.it/"], backends=["opencli"]),
                ],
            },
            {
                "name": "xiaohongshu",
                "description": "小红书",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "x"},
                "actions": [
                    _action("read", [_p("target", "", required=True)],
                            public_web=["xiaohongshu.com/explore/", "xhslink.com/"], backends=["opencli"]),
                ],
            },
            {
                "name": "linkedin",
                "description": "LinkedIn",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "x"},
                "actions": [
                    _action("jobs", [_p("query", "", required=True), _p("limit", "", type_="int")],
                            public_web=["linkedin.com/jobs/view/"], backends=["opencli"]),
                    _action("read", [_p("target", "", required=True)],
                            public_web=["linkedin.com/jobs/view/"], backends=["opencli"]),
                ],
            },
            {
                "name": "v2ex",
                "description": "V2EX",
                "level": "default",
                "login": None,
                "actions": [
                    _action("user", [_p("username", "", required=True)], backends=["v2ex-api"]),
                ],
            },
            {
                "name": "bilibili",
                "description": "B站",
                "level": "default",
                "login": {"via": "session", "logged_in": False, "command": "x"},
                "actions": [
                    _action("hot", [_p("limit", "", type_="int")], backends=["bilibili-api"]),
                ],
            },
            {
                "name": "xueqiu",
                "description": "雪球",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "x"},
                "actions": [
                    _action("search", [_p("query", "", required=True), _p("limit", "", type_="int")],
                            backends=["tencent", "xueqiu-api"]),
                ],
            },
            {
                "name": "github",
                "description": "GitHub",
                "level": "default",
                "login": None,
                "actions": [
                    _action("read", [_p("target", "", required=True)], backends=["gh", "github-api"]),
                ],
            },
            {
                "name": "web",
                "description": "web",
                "level": "default",
                "login": None,
                "actions": [
                    _action("read", [_p("target", "", required=True)], backends=["jina", "exa"]),
                ],
            },
        ],
    }


ROUTE_BACKEND = {
    "reddit": "public-web",
    "xiaohongshu": "public-web",
    "linkedin": "public-web",
    "v2ex": "v2ex-api",
    "bilibili": "bilibili-api",
    "xueqiu": "tencent",
    "github": "github-api",
    "web": "public-web",
}


def envelope(channel: str, action: str, items, *, backend=None) -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": backend or ROUTE_BACKEND[channel],
        "items": items,
        "meta": {
            "elapsed_ms": 411,
            "attempts": [{"backend": "public-web/jina", "result": "ok", "message": None}],
        },
        "error": None,
    }


def _item(case: str, **overrides) -> dict:
    fixture = FIXTURES[case]
    item = {
        "title": fixture["title"],
        "url": fixture["url"],
        "author": None,
        "published_at": None,
        "text": fixture["text"],
        "raw": fixture.get("raw"),
    }
    item.update(overrides)
    return item


def _runner(response: dict):
    def run(argv, *, timeout, env):
        if list(argv)[1:] == ["channels"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(registry_payload()), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(response, ensure_ascii=False), stderr="")

    return run


def _backend(tmp_path, response: dict) -> reach.AgentReachBackend:
    stub = tmp_path / "agent-reach"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    return reach.AgentReachBackend(str(stub), runner=_runner(response), env={})


# ── classifier unit level (shared with extraction) ────────────────────────


@pytest.mark.parametrize(
    "case,reason",
    [
        ("reddit_read_blocked", "blocked"),
        ("xiaohongshu_read_missing", "missing_page"),
        ("linkedin_read_404", "missing_page"),
    ],
)
def test_classifier_flags_recorded_shells(case, reason):
    text = FIXTURES[case]["text"]
    assert classify_page_shell(text) == reason
    assert _is_usable_page_text(text) is False


@pytest.mark.parametrize("case", ["github_read_readme", "linkedin_jobs_page"])
def test_classifier_keeps_real_page_bodies(case):
    text = FIXTURES[case]["text"]
    assert classify_page_shell(text) is None
    assert _is_usable_page_text(text) is True


def test_long_article_about_404_pages_is_not_a_shell():
    """A marker alone must never condemn real prose — only a dominant shell."""
    article = (
        "Debugging soft 404s in production\n\n"
        "A page not found response is usually a routing bug, not a content bug. "
        "Start with the rewrite table, then check CDN cache keys, then confirm the "
        "origin still serves the document. Each step below isolates one layer so a "
        "missing route never hides behind a stale edge cache. We also cover how "
        "search engines treat soft 404s and why a friendly error page still needs "
        "to return the right status code for crawlers and clients alike.\n\n"
    ) * 4
    assert len(article) > 800
    assert classify_page_shell(article) is None


def test_short_chinese_placeholder_is_a_shell_but_real_note_is_not():
    placeholder = "你访问的页面不见了，你还可以 返回上一页 活动 活动"
    assert classify_page_shell(placeholder) == "missing_page"

    note = (
        "周末去了这家咖啡店，手冲很稳，豆子偏果酸。\n\n"
        "#咖啡 #探店\n\n"
        "店里只有六个座位，下午两点后人会多一些。老板会介绍每支豆子的处理法，"
        "可以按杯点也可以买豆子回家。人均四十左右，性价比不错。"
    ) * 2
    assert classify_page_shell(note) is None


def test_scoring_treats_forwarded_or_extracted_shell_as_platform_shell():
    body = FIXTURES["linkedin_read_404"]["text"]
    hit = ScoredHit(
        title="LinkedIn",
        url="https://www.linkedin.com/jobs/view/4447811252",
        summary=body,
        extraction_status="ok",
        extraction_length=len(body),
    )
    assert assess_evidence(hit).usable is False
    assert score_hit(hit).scoring.quality == SourceQuality.PLATFORM_SHELL


# ── forwarding contract: shells are not successful reads ──────────────────


def test_reddit_read_block_is_content_unusable_not_ok(tmp_path):
    response = envelope("reddit", "read", [_item("reddit_read_blocked")])
    result = _backend(tmp_path, response).execute(
        "reddit", "read", {"target": FIXTURES["reddit_read_blocked"]["url"]}
    ).to_dict()

    assert result["ok"] is False
    assert result["items"] == []
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["blocked"]
    assert result["error"]["withheld_items"] == 1
    # Attribution and the upstream attempt chain survive the rejection.
    assert result["provenance"]["attribution"] == ATTRIBUTION
    assert result["provenance"]["reported_backend"] == "public-web"
    assert result["attempts"] == [
        {"backend": "public-web/jina", "result": "ok", "message": None}
    ]
    assert any("withheld" in note for note in result["limitations"])


def test_xiaohongshu_read_missing_note_is_content_unusable(tmp_path):
    response = envelope("xiaohongshu", "read", [_item("xiaohongshu_read_missing")])
    result = _backend(tmp_path, response).execute(
        "xiaohongshu", "read", {"target": FIXTURES["xiaohongshu_read_missing"]["url"]}
    ).to_dict()

    assert result["ok"] is False
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["missing_page"]


def test_linkedin_read_multilingual_404_is_content_unusable(tmp_path):
    response = envelope("linkedin", "read", [_item("linkedin_read_404")])
    result = _backend(tmp_path, response).execute(
        "linkedin", "read", {"target": FIXTURES["linkedin_read_404"]["url"]}
    ).to_dict()

    assert result["ok"] is False
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["missing_page"]


def test_shell_does_not_starve_a_usable_row_behind_it(tmp_path):
    """A withheld first row must not consume the item budget."""
    response = envelope(
        "linkedin",
        "read",
        [
            _item("linkedin_read_404"),
            _item(
                "linkedin_jobs_page",
                url="https://www.linkedin.com/jobs/view/senior-python-developer-remote-at-hired-4447811252",
            ),
        ],
    )
    result = _backend(tmp_path, response).execute(
        "linkedin", "read", {"target": "https://www.linkedin.com/jobs/view/4447811252"}, max_items=1
    ).to_dict()

    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert "Senior Python Developer" in result["items"][0]["title"]
    assert any("1 item(s) were withheld" in note for note in result["limitations"])


def test_mixed_rows_report_usable_content_and_name_what_was_withheld(tmp_path):
    response = envelope(
        "web",
        "read",
        [_item("github_read_readme"), _item("reddit_read_blocked")],
        backend="public-web",
    )
    result = _backend(tmp_path, response).execute(
        "web", "read", {"target": "https://docs.python.org/3/library/asyncio.html"}
    ).to_dict()

    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["url"] == FIXTURES["github_read_readme"]["url"]
    limitation = next(n for n in result["limitations"] if "withheld" in n)
    assert "blocked=1" in limitation and "missing_page=0" in limitation


# ── metadata-only actions and discovery snippets are untouched ────────────


def test_metadata_actions_keep_empty_text_items(tmp_path):
    """v2ex user / bilibili hot / xueqiu search carry no body text by design."""
    params_by_case = {
        "v2ex_user_metadata": {"username": "Livid"},
        "bilibili_hot_metadata": {"limit": 2},
        "xueqiu_search_metadata": {"query": "茅台", "limit": 2},
    }
    for case, params in params_by_case.items():
        fixture = FIXTURES[case]
        item = _item(case)
        assert item["text"] == ""
        response = envelope(fixture["channel"], fixture["action"], [item, dict(item)])
        result = _backend(tmp_path, response).execute(
            fixture["channel"], fixture["action"], params, max_items=2
        ).to_dict()

        assert result["ok"] is True, case
        assert len(result["items"]) == 2, case
        assert result["items"][0]["raw"] == fixture["raw"], case
        assert not any("withheld" in note for note in result["limitations"]), case


def test_read_action_with_metadata_only_items_is_not_flagged(tmp_path):
    """Empty text on a read row is odd but not a shell — never invent a verdict."""
    response = envelope("v2ex", "user", [{"title": "Livid", "url": "https://www.v2ex.com/u/Livid",
                                          "text": "", "raw": {"status": "found"}}])
    # The action name is metadata-only here, so the body-read gate does not apply.
    result = _backend(tmp_path, response).execute("v2ex", "user", {"username": "Livid"}).to_dict()
    assert result["ok"] is True
    assert len(result["items"]) == 1


def test_discovery_search_snippet_is_forwarded_unchanged(tmp_path):
    """Search rows are leads, not complete-artifact claims: no body filtering."""
    snippet = "Page not found — this thread was removed by the moderators."
    response = envelope(
        "reddit",
        "search",
        [{"title": "r/Python thread", "url": "https://www.reddit.com/r/Python/comments/x/y/",
          "text": snippet, "raw": None}],
    )
    result = _backend(tmp_path, response).execute(
        "reddit", "search", {"query": "python asyncio"}
    ).to_dict()

    assert result["ok"] is True
    assert result["items"][0]["text"] == snippet


def test_usable_bodies_are_still_forwarded(tmp_path):
    for case in ("github_read_readme", "linkedin_jobs_page"):
        fixture = FIXTURES[case]
        response = envelope(fixture["channel"], "read", [_item(case)])
        result = _backend(tmp_path, response).execute(
            fixture["channel"], "read", {"target": fixture["url"]}
        ).to_dict()

        assert result["ok"] is True, case
        assert len(result["items"]) == 1, case
        assert result["items"][0]["text"].startswith(fixture["text"][:40]), case


def test_body_read_actions_are_the_detail_reads_only():
    assert reach.BODY_READ_ACTIONS == frozenset({"read", "thread", "comments"})
    for discovery in ("search", "jobs", "hot", "user", "quote", "node", "profile"):
        assert discovery not in reach.BODY_READ_ACTIONS
