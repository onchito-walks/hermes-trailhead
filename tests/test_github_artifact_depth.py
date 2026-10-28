"""GitHub issue/pull-request artifact depth contracts.

A native ``read`` of ``github.com/<owner>/<repo>/issues/<n>`` or ``/pull/<n>``
routed to :func:`_github_repo_metadata`, so the caller received repository stats
and a README excerpt instead of the requested issue/PR body and discussion.

The frozen live identifiers below were captured from the public REST API on
2026-10-28 with ``GITHUB_TOKEN``/``GH_TOKEN`` and the home directory stripped:

* ``pallets/flask#5`` — "Implement SQLAlchemy", issue id 170451,
  comment ids 308703 and 308779;
* ``pallets/flask#112`` — "JSONP", pull id 541, 14 conversation comment ids
  (382640 … 4489650), 0 reviews, 0 inline review comments.

These tests never touch the network: the public API payloads are reconstructed
from the frozen shapes, and comment bodies for the PR fixture are placeholders.
What is frozen and asserted is the routing (issue/pull vs repository root), the
identifiers/titles, the bounded capture/disclosure contract and the honest
failure paths.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead import cli
from hermes_trailhead.cli import main
from hermes_trailhead.extract import (
    _fetch_github_summary,
    _github_paginated_list,
    extract_one,
)

# ── Frozen public artifacts (captured before any code change) ─────────

ISSUE_URL = "https://github.com/pallets/flask/issues/5"
ISSUE_ID = 170451
ISSUE_TITLE = "Implement SQLAlchemy"
ISSUE_COMMENT_IDS = (308703, 308779)

PR_URL = "https://github.com/pallets/flask/pull/112"
PR_ID = 541
PR_TITLE = "JSONP"
PR_COMMENT_IDS = (
    382640, 383274, 618181, 620332, 650978, 1050643, 2304151,
    2308644, 3522442, 3529766, 3535071, 4275572, 4322406, 4489650,
)


# ── Offline public-API fixtures ───────────────────────────────────────


def _comment(comment_id: int, login: str, body: str, created: str = "2010-04-07T00:00:00Z") -> dict:
    return {
        "id": comment_id,
        "user": {"login": login},
        "created_at": created,
        "body": body,
    }


ISSUE_COMMENTS = [
    _comment(308703, "dcolish", "Just use the Flask-SQLAlchemy extension\n"),
    _comment(308779, "mitsuhiko", "What dcolish said.\n", "2010-04-08T00:00:00Z"),
]


def _issue_payload(**overrides) -> dict:
    data = {
        "number": 5,
        "id": ISSUE_ID,
        "title": ISSUE_TITLE,
        "state": "closed",
        "user": {"login": "justquick"},
        "created_at": "2010-04-06T16:13:37Z",
        "updated_at": "2010-04-12T02:24:12Z",
        "labels": [{"name": "feature"}],
        "body": "Use SQLAlchemy in the core framework as an ORM\n",
        "comments": len(ISSUE_COMMENTS),
        "html_url": ISSUE_URL,
    }
    data.update(overrides)
    return data


PR_COMMENTS = [
    _comment(cid, "commenter", f"Frozen PR comment {cid}", "2011-09-24T00:00:00Z")
    for cid in PR_COMMENT_IDS
]


def _pull_payload(**overrides) -> dict:
    data = {
        "number": 112,
        "id": PR_ID,
        "title": PR_TITLE,
        "state": "closed",
        "merged_at": None,
        "merged": False,
        "draft": False,
        "user": {"login": "galvez"},
        "created_at": "2011-09-23T00:00:00Z",
        "updated_at": "2013-01-19T00:00:00Z",
        "base": {"label": "pallets:master", "ref": "master"},
        "head": {"label": None, "ref": "patch-1"},
        "commits": 1,
        "changed_files": 2,
        "additions": 26,
        "deletions": 4,
        "body": (
            "If you are interested, I added a function to return padded JSON. "
            "I needed it for a project I'm working on."
        ),
        "comments": len(PR_COMMENTS),
        "review_comments": 0,
        "html_url": PR_URL,
    }
    data.update(overrides)
    return data


def _install_api(
    monkeypatch,
    *,
    issue=None,
    comments=None,
    pull=None,
    reviews=None,
    review_comments=None,
    fail_comments: str = "",
) -> list[str]:
    """Patch ``_github_api_json`` with deterministic public-API-shaped data."""
    calls: list[str] = []

    def fake(api: str, timeout: int = 15):
        calls.append(api)
        parsed = urlparse(api)
        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        per_page = int(query.get("per_page", ["100"])[0])
        path = parsed.path

        if fail_comments and path.endswith("/comments") and "/issues/" in path:
            raise RuntimeError(fail_comments)

        if path.endswith("/comments") and "/pulls/" in path:
            payload = review_comments if review_comments is not None else []
        elif path.endswith("/reviews"):
            payload = reviews if reviews is not None else []
        elif path.endswith("/comments"):
            payload = comments if comments is not None else []
        elif "/pulls/" in path:
            payload = pull
        elif "/issues/" in path:
            payload = issue
        else:  # pragma: no cover - the reader must not call anything else
            raise AssertionError(f"unexpected GitHub API URL: {api}")

        if isinstance(payload, list):
            start = (page - 1) * per_page
            return payload[start : start + per_page]
        if payload is None:
            raise AssertionError(f"no fixture for GitHub API URL: {api}")
        return payload

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)
    return calls


def _no_generic_tiers(monkeypatch) -> None:
    """Make every non-GitHub fetch tier fail, so no test touches the network."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("tier unavailable")

    monkeypatch.setattr(extract_mod, "_fetch_text_tiered", boom)
    monkeypatch.setattr(extract_mod, "_fetch_jina", boom)
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", boom)


# ── 1. Issue and pull URLs return their own artifact ──────────────────


def test_issue_url_returns_issue_body_and_comments_not_repository_metadata(monkeypatch):
    calls = _install_api(monkeypatch, issue=_issue_payload(), comments=ISSUE_COMMENTS)

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert out.startswith("GitHub issue pallets/flask#5: Implement SQLAlchemy")
    assert "Use SQLAlchemy in the core framework as an ORM" in out
    assert "Just use the Flask-SQLAlchemy extension" in out
    assert "What dcolish said." in out
    assert "[id 308703]" in out and "[id 308779]" in out
    assert "captured 2 of 2" in out
    assert "complete for this endpoint" in out
    assert "https://api.github.com/repos/pallets/flask/issues/5/comments?per_page=100" in calls
    # The wrong artifact must not be reachable from this path.
    assert "GitHub repository:" not in out
    assert "Stars:" not in out
    assert "README" not in out


def test_pull_url_returns_pull_body_with_bounded_discussion(monkeypatch):
    reviews = [
        {
            "id": 9001,
            "user": {"login": "mitsuhiko"},
            "state": "APPROVED",
            "created_at": "2013-01-18T00:00:00Z",
            "body": "Looks fine, but add a test.",
        }
    ]
    review_comments = [
        {
            "id": 9002,
            "user": {"login": "davidism"},
            "created_at": "2013-01-18T01:00:00Z",
            "path": "flask/json.py",
            "line": 42,
            "body": "This should escape the callback name.",
        }
    ]
    _install_api(
        monkeypatch,
        pull=_pull_payload(review_comments=1),
        comments=PR_COMMENTS,
        reviews=reviews,
        review_comments=review_comments,
    )

    out = _fetch_github_summary(PR_URL, timeout=10)

    assert out.startswith("GitHub pull request pallets/flask#112: JSONP")
    assert "I added a function to return padded JSON" in out
    assert "Base: pallets:master | Head: patch-1" in out
    assert "Commits: 1 | Changed files: 2" in out
    # Conversation comments keep their identifiers.
    for comment_id in PR_COMMENT_IDS:
        assert f"[id {comment_id}]" in out
    assert "captured 14 of 14" in out
    # Reviews and inline review comments are captured bounded and labelled.
    assert "--- review 1: mitsuhiko" in out and "— APPROVED" in out
    assert "Looks fine, but add a test." in out
    assert "--- inline review comment 1: davidism" in out
    assert "flask/json.py:42" in out
    assert "This should escape the callback name." in out
    assert "Inline review comments: captured 1 of 1" in out
    # The PR conversation is explicitly scoped, never claimed as complete.
    assert "is NOT the complete PR conversation" in out
    assert "NOT the complete PR conversation" in out
    assert "GitHub repository:" not in out


def test_frozen_identifiers_survive_the_issue_and_pull_paths(monkeypatch):
    """Public IDs/titles captured before the change stay the requested objects."""
    _install_api(monkeypatch, issue=_issue_payload(), comments=ISSUE_COMMENTS)
    issue = _fetch_github_summary(ISSUE_URL, timeout=10)
    assert f"GitHub issue pallets/flask#5: {ISSUE_TITLE}" in issue
    assert "closed" in issue.splitlines()[1]
    assert "Labels: feature" in issue

    _install_api(
        monkeypatch,
        pull=_pull_payload(),
        comments=PR_COMMENTS,
        reviews=[],
        review_comments=[],
    )
    pull = _fetch_github_summary(PR_URL, timeout=10)
    assert f"GitHub pull request pallets/flask#112: {PR_TITLE}" in pull
    assert "Reviews: captured 0" in pull
    assert "Inline review comments: captured 0 of 0" in pull


def test_issue_number_that_is_a_pull_request_is_read_as_a_pull(monkeypatch):
    _install_api(
        monkeypatch,
        issue=_issue_payload(
            number=112,
            id=PR_ID,
            title=PR_TITLE,
            pull_request={"url": "https://api.github.com/repos/pallets/flask/pulls/112"},
        ),
        pull=_pull_payload(),
        comments=PR_COMMENTS,
        reviews=[],
        review_comments=[],
    )

    out = _fetch_github_summary("https://github.com/pallets/flask/issues/112", timeout=10)

    assert out.startswith("GitHub pull request pallets/flask#112: JSONP")


# ── 2. Bounded pagination and explicit capture disclosure ─────────────


def test_issue_comment_pagination_pages_until_complete(monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    comments = [_comment(1000 + i, "user", f"comment body {i}") for i in range(5)]
    calls = _install_api(
        monkeypatch,
        issue=_issue_payload(comments=5),
        comments=comments,
    )

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "Conversation comments: captured 5 of 5 (3 page(s), per_page 2" in out
    assert "complete for this endpoint" in out
    comment_calls = [url for url in calls if url.endswith("/comments") or "/comments?" in url]
    assert len(comment_calls) == 3
    assert "page=3" in comment_calls[-1]
    for i in range(5):
        assert f"comment body {i}" in out


def test_issue_comment_pagination_discloses_unfetched_next_page(monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    comments = [_comment(2000 + i, "user", f"comment body {i}") for i in range(9)]
    calls = _install_api(
        monkeypatch,
        issue=_issue_payload(comments=9),
        comments=comments,
    )

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "captured 6 of 9" in out
    assert "NOT complete" in out
    assert "next page: https://api.github.com/repos/pallets/flask/issues/5/comments?per_page=2&page=4" in out
    # Only the captured pages' text is present; uncaptured items are not invented.
    assert "comment body 5" in out
    assert "comment body 6" not in out
    assert len([url for url in calls if "/comments" in url]) == 3


def test_paginated_reader_refuses_non_list_payloads(monkeypatch):
    monkeypatch.setattr(
        extract_mod, "_github_api_json", lambda api, timeout=15: {"message": "Not Found"}
    )
    with pytest.raises(RuntimeError):
        _github_paginated_list("https://api.github.com/repos/o/r/issues/1/comments", 10)


# ── 3. Caps are disclosed, never silently applied ─────────────────────


def test_comment_body_cap_is_disclosed(monkeypatch):
    long_body = "x" * 5000
    _install_api(
        monkeypatch,
        issue=_issue_payload(comments=1),
        comments=[_comment(3000, "long", long_body)],
    )

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "[body truncated at 4000 of 5000 chars]" in out
    assert "body cap 4000 chars per item" in out
    assert "x" * 4000 in out
    assert "x" * 4001 not in out


def test_artifact_text_cap_stops_capture_with_disclosure(monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_ARTIFACT_CHAR_CAP", 1500)
    comments = [_comment(4000 + i, "user", "y" * 500) for i in range(4)]
    _install_api(monkeypatch, issue=_issue_payload(comments=4), comments=comments)

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert len(out) < 5000
    assert f"discussion text cap {1500} chars reached" in out
    assert "not included]" in out
    # Capture count still reports what the endpoint returned, not what fit.
    assert "captured 4 of 4" in out


def test_pull_body_truncation_is_disclosed(monkeypatch):
    body = "z" * 25000
    _install_api(
        monkeypatch,
        pull=_pull_payload(body=body, comments=0, review_comments=0),
        comments=[],
        reviews=[],
        review_comments=[],
    )

    out = _fetch_github_summary(PR_URL, timeout=10)

    assert "[body truncated at 20000 of 25000 chars]" in out


# ── 4. Wrong identifiers and failures never become success ────────────


def test_wrong_issue_id_response_is_rejected(monkeypatch):
    _install_api(
        monkeypatch,
        issue=_issue_payload(number=6, id=999, title="A different issue"),
        comments=[],
    )

    with pytest.raises(RuntimeError) as excinfo:
        _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "no issue pallets/flask#5" in str(excinfo.value)


def test_failed_issue_api_raises_and_never_returns_repository_metadata(monkeypatch):
    def failing(api: str, timeout: int = 15):
        raise RuntimeError("HTTP Error 404: Not Found")

    monkeypatch.setattr(extract_mod, "_github_api_json", failing)

    with pytest.raises(RuntimeError):
        _fetch_github_summary(ISSUE_URL, timeout=10)

    # The native extraction path must not turn the failure into repo metadata.
    # Every generic tier is stubbed out as well: without this, a live direct or
    # Jina fetch of the same URL would make the assertion network-dependent.
    _no_generic_tiers(monkeypatch)
    result = extract_one(ISSUE_URL, timeout=1)

    assert result.status == "error"
    assert result.content == ""
    assert ISSUE_URL in result.error_message
    assert "GitHub repository:" not in result.content
    assert "Stars:" not in result.content


def test_generic_page_fallback_serves_the_requested_issue_not_repository_metadata(
    monkeypatch,
):
    """A real page fetch is a legitimate degraded read — but of the issue itself.

    Only the GitHub API tier failed here; the generic tier returned the issue
    page. That is the requested artifact, so ``ok`` is allowed — while
    repository stats are still never substituted for the requested issue.
    """

    def failing(api: str, timeout: int = 15):
        raise RuntimeError("HTTP Error 404: Not Found")

    monkeypatch.setattr(extract_mod, "_github_api_json", failing)

    page = (
        f"Title: {ISSUE_TITLE}\n\nURL Source: {ISSUE_URL}\n\nMarkdown Content:\n"
        "Use SQLAlchemy in the core framework as an ORM\n\n"
        + "Just use the Flask-SQLAlchemy extension\n" * 20
    )
    monkeypatch.setattr(
        extract_mod, "_fetch_text_tiered", lambda url, timeout=15: page
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("tier unavailable")

    monkeypatch.setattr(extract_mod, "_fetch_jina", boom)
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", boom)

    result = extract_one(ISSUE_URL, timeout=1)

    assert result.status == "ok"
    assert result.source_type == "github"
    assert ISSUE_TITLE in result.content
    assert "Just use the Flask-SQLAlchemy extension" in result.content
    # The fallback is the requested issue page, never repository metadata.
    assert "GitHub repository:" not in result.content
    assert "Stars:" not in result.content


def test_api_error_object_is_not_rendered_as_issue_evidence(monkeypatch):
    _install_api(monkeypatch, issue={"message": "Not Found", "documentation_url": "https://docs"})

    with pytest.raises(RuntimeError):
        _fetch_github_summary(ISSUE_URL, timeout=10)


def test_secondary_comment_failure_is_disclosed_not_fatal(monkeypatch):
    _install_api(
        monkeypatch,
        issue=_issue_payload(),
        fail_comments="HTTP Error 500: Server Error",
    )

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "Implement SQLAlchemy" in out
    assert "Conversation comments: not captured" in out
    assert "HTTP Error 500: Server Error" in out
    assert "the requested artifact above is unaffected" in out


# ── 5. Native `read` pagination and search previews still hold ────────


def test_native_read_paginates_the_resulting_github_artifact_text(monkeypatch, capsys):
    artifact = (
        "GitHub issue pallets/flask#5: Implement SQLAlchemy\n\n"
        + ("bounded discussion text for pagination\n" * 1600)
    )
    assert len(artifact) > 3 * cli.READ_DEFAULT_MAX_CHARS
    monkeypatch.setattr(
        extract_mod, "_fetch_github_summary", lambda url, timeout=15: artifact
    )

    rc = main(["read", ISSUE_URL, "--format", "json"])
    first = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert first["pagination"]["total_available_chars"] == len(artifact)
    assert first["pagination"]["more"] is True
    assert first["pagination"]["next_offset"] == cli.READ_DEFAULT_MAX_CHARS
    assert first["pagination"]["retrieval_char_cap"] == 1_000_000

    rc = main(
        [
            "read", ISSUE_URL, "--format", "json",
            "--offset", str(first["pagination"]["next_offset"]),
            "--max-chars", str(cli.READ_DEFAULT_MAX_CHARS),
        ]
    )
    second = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert second["pagination"]["start"] == first["pagination"]["end"]
    assert second["pagination"]["document_sha256"] == first["pagination"]["document_sha256"]
    # Windows are contiguous text of the same artifact, no gap or overlap.
    assert first["content"] + second["content"] == artifact[: second["pagination"]["end"]]


def test_search_preview_stays_bounded_for_the_github_artifact(monkeypatch):
    artifact = "GitHub issue pallets/flask#5: Implement SQLAlchemy\n" + (
        "discussion line\n" * 4000
    )
    monkeypatch.setattr(
        extract_mod, "_fetch_github_summary", lambda url, timeout=15: artifact
    )

    with extract_mod.retrieval_scope(char_limit=extract_mod._READABLE_TEXT_LIMIT):
        result = extract_one(ISSUE_URL, timeout=1)

    assert result.status == "ok"
    assert result.content_length == len(artifact)
    assert len(result.content) <= extract_mod._READABLE_TEXT_LIMIT + 4
    assert result.content.endswith("...")


def test_github_artifact_cap_stays_below_the_one_megabyte_read_bound():
    assert extract_mod._GITHUB_ARTIFACT_CHAR_CAP < cli.READ_RETRIEVAL_CHAR_CAP
    assert cli.READ_RETRIEVAL_CHAR_CAP == 1_000_000
