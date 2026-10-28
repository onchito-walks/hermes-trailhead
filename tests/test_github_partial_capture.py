"""Regression tests for two measured GitHub partial-capture falsehoods.

1. Repository root README missing — ``docs/PUBLIC-RESOURCE-EVIDENCE.md``
   measured ``github.com/psf/requests`` returning 215 characters of
   metadata-only text (stars/forks/language) with ``status="ok"`` when the
   README fetch failed.  The README *is* the requested artifact on the exact
   repository root, so that read must fail explicitly.  Any other repository
   page keeps tolerating a missing README (metadata-only evidence is honest
   there), and the generic tiers may still serve a real page.

2. Mid-pagination socket failure — ``docs/CAMPAIGN-QA.md`` QR-06.  Only this
   module's own ``_GithubReadTimeout`` used to preserve already-fetched pages;
   a socket/HTTP error on page 2 propagated out of ``_github_paginated_list``
   and page 1 was discarded (``_github_section`` reported "not captured").
   Captured pages must survive as ``complete=False`` with the real endpoint
   error and the next page URL, reusing the capture-summary error semantics.
   A first-page failure still raises.

All GitHub I/O here is injected: no network, no real API.
"""
import base64
import socket
from urllib.parse import parse_qs, urlparse

import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _fetch_github_summary,
    _github_capture_summary,
    _github_paginated_list,
    extract_one,
)

ROOT_URL = "https://github.com/psf/requests"
ISSUE_URL = "https://github.com/psf/requests/issues/1"
COMMENTS_API = "https://api.github.com/repos/psf/requests/issues/1/comments"


def _repo_payload() -> dict:
    return {
        "full_name": "psf/requests",
        "description": "A simple, yet elegant, HTTP library.",
        "homepage": "https://requests.readthedocs.io",
        "stargazers_count": 52000,
        "forks_count": 9300,
        "open_issues_count": 240,
        "language": "Python",
        "license": {"name": "Apache License 2.0", "spdx_id": "Apache-2.0"},
    }


def _issue_payload(comments: int = 5) -> dict:
    return {
        "number": 1,
        "id": 100,
        "title": "README capture regression",
        "state": "open",
        "user": {"login": "reporter"},
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "labels": [],
        "body": "The issue body that must survive a partial comment capture.",
        "comments": comments,
        "html_url": ISSUE_URL,
    }


def _comment(ident: int) -> dict:
    return {
        "id": ident,
        "user": {"login": f"commenter{ident}"},
        "created_at": "2026-10-02T00:00:00Z",
        "body": f"captured comment body number {ident}",
    }


def _install_root(monkeypatch, *, readme="", readme_error=None, contents_error=None,
                  contents=""):
    """Patch the repo-root read: repo payload, raw README and contents API."""

    def fake_api(api: str, timeout: float = 15):
        if api.endswith("/readme"):
            if contents_error is not None:
                raise contents_error
            return {"content": base64.b64encode(contents.encode()).decode()}
        return _repo_payload()

    monkeypatch.setattr(extract_mod, "_github_api_json", fake_api)

    def fake_raw(owner: str, repo: str, timeout: float):
        if readme_error is not None:
            raise readme_error
        return readme

    monkeypatch.setattr(extract_mod, "_github_readme_raw", fake_raw)


def _no_generic_tiers(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("tier unavailable")

    monkeypatch.setattr(extract_mod, "_fetch_text_tiered", boom)
    monkeypatch.setattr(extract_mod, "_fetch_jina", boom)
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", boom)


# ── 1. Repository root: the README is the requested artifact ────────────


def test_root_readme_failure_raises_instead_of_metadata_only_success(monkeypatch):
    _install_root(
        monkeypatch,
        readme_error=RuntimeError("HTTP Error 403: rate limited"),
        contents_error=RuntimeError("HTTP Error 404: Not Found"),
    )

    with pytest.raises(RuntimeError) as excinfo:
        _fetch_github_summary(ROOT_URL, timeout=10)

    message = str(excinfo.value)
    # Truthful, actionable, and it names the artifact that failed.
    assert "README for psf/requests could not be read" in message
    assert "raw readme endpoint: RuntimeError: HTTP Error 403" in message
    assert "readme contents API: RuntimeError: HTTP Error 404" in message
    assert "NOT a successful read" in message
    assert "https://raw.githubusercontent.com/psf/requests/HEAD/README.md" in message


def test_root_readme_empty_body_raises(monkeypatch):
    _install_root(monkeypatch, readme="   \n", contents="")

    with pytest.raises(RuntimeError) as excinfo:
        _fetch_github_summary(ROOT_URL, timeout=10)

    assert "README body came back empty" in str(excinfo.value)


def test_root_readme_success_returns_full_body_not_an_excerpt(monkeypatch):
    body = "Requests: HTTP for Humans\n\n" + ("Install with pip install requests.\n" * 200)
    _install_root(monkeypatch, readme=body)

    content = _fetch_github_summary(ROOT_URL, timeout=10)

    assert "GitHub repository: psf/requests" in content
    assert "README:" in content
    assert "README excerpt" not in content
    assert body.strip() in content  # full README, not the 1200-char excerpt
    assert len(content) > 5000


def test_unknown_repository_path_still_allows_metadata_only(monkeypatch):
    """A non-root repository page keeps the ordinary metadata-only behaviour."""
    _install_root(monkeypatch, contents_error=RuntimeError("HTTP Error 404: Not Found"))

    content = _fetch_github_summary("https://github.com/psf/requests/issues", timeout=10)

    assert "GitHub repository: psf/requests" in content
    assert "README" not in content


def test_extract_one_root_readme_failure_is_not_reported_ok(monkeypatch):
    _install_root(
        monkeypatch,
        readme_error=RuntimeError("HTTP Error 500: Server Error"),
        contents_error=RuntimeError("HTTP Error 500: Server Error"),
    )
    _no_generic_tiers(monkeypatch)

    result = extract_one(ROOT_URL, timeout=1)

    assert result.status != "ok"
    assert "Stars:" not in result.content
    assert "GitHub repository:" not in result.content


def test_extract_one_root_readme_failure_may_still_return_a_real_page(monkeypatch):
    """Falling through to a generic tier is fine when it yields the real page."""
    _install_root(
        monkeypatch,
        readme_error=RuntimeError("HTTP Error 500: Server Error"),
        contents_error=RuntimeError("HTTP Error 500: Server Error"),
    )
    page = (
        "Requests is a simple, yet elegant, HTTP library.\n\n"
        "Requests allows you to send HTTP/1.1 requests extremely easily, with "
        "headers, form data, multipart files and query parameters handled for "
        "you, plus automatic content decoding and connection pooling.\n\n"
        "Install it with pip and start with requests.get('https://example.com').\n"
    )
    monkeypatch.setattr(extract_mod, "_fetch_text_tiered", lambda url, timeout=15: page)

    result = extract_one(ROOT_URL, timeout=5)

    assert result.status == "ok"
    assert "HTTP library" in result.content
    assert "Stars:" not in result.content


# ── 2. Mid-pagination socket failure keeps the pages already captured ───


def _install_comments(monkeypatch, *, fail_page=2, error=None, total_comments=5):
    """Two-item page size; the page after ``fail_page``-1 fails as injected."""
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    error = error if error is not None else socket.timeout("timed out")
    calls: list[str] = []

    def fake(api: str, timeout: float = 15):
        calls.append(api)
        parsed = urlparse(api)
        page = int(parse_qs(parsed.query).get("page", ["1"])[0])
        if parsed.path.endswith("/comments"):
            if page >= fail_page:
                raise error
            return [_comment(1), _comment(2)]
        return _issue_payload(comments=total_comments)

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)
    return calls


def test_later_page_socket_timeout_keeps_captured_pages(monkeypatch):
    _install_comments(monkeypatch)

    capture = _github_paginated_list(COMMENTS_API, 10)

    assert [item["id"] for item in capture["items"]] == [1, 2]
    assert capture["pages"] == 1
    assert capture["complete"] is False
    assert capture["deadline_exhausted"] is False
    assert "TimeoutError" in capture["error"]
    assert "timed out" in capture["error"]
    assert capture["next_url"] == f"{COMMENTS_API}?per_page=2&page=2"


def test_partial_capture_summary_discloses_the_real_endpoint_error(monkeypatch):
    _install_comments(monkeypatch)
    capture = _github_paginated_list(COMMENTS_API, 10)

    summary = _github_capture_summary("Conversation comments", capture, total=5)

    assert "captured 2 of 5" in summary
    assert "NOT complete" in summary
    assert "the request for the next page failed (TimeoutError: timed out)" in summary
    assert "page=2" in summary
    assert "complete for this endpoint" not in summary


def test_issue_read_with_a_later_page_timeout_keeps_the_first_page(monkeypatch):
    _install_comments(monkeypatch)

    content = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "GitHub issue psf/requests#1: README capture regression" in content
    assert "The issue body that must survive" in content
    assert "captured comment body number 1" in content  # page 1 was not discarded
    assert "captured 2 of 5" in content
    assert "NOT complete" in content
    assert "TimeoutError" in content
    assert "not captured" not in content  # the old all-or-nothing wording


def test_first_page_failure_still_raises(monkeypatch):
    _install_comments(monkeypatch, fail_page=1)

    with pytest.raises(socket.timeout):
        _github_paginated_list(COMMENTS_API, 10)


def test_first_page_failure_in_a_secondary_section_is_disclosed_not_fatal(monkeypatch):
    """A first-page failure raises out of the capture, and the section says so.

    The issue body is the requested artifact, so the section reports the
    failure instead of taking the whole read down (unchanged behaviour).
    """
    _install_comments(monkeypatch, fail_page=1)

    content = _fetch_github_summary(ISSUE_URL, timeout=10)

    assert "The issue body that must survive" in content
    assert "Conversation comments: not captured (TimeoutError: timed out)" in content
    assert "captured 0" not in content


def test_deadline_exhaustion_is_still_not_reported_as_endpoint_error(monkeypatch):
    """The pre-existing deadline semantics must win over the new error field."""
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 1)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    now = {"t": 0.0}
    monkeypatch.setattr(extract_mod, "_github_monotonic", lambda: now["t"])

    def fake(api: str, timeout: float = 15):
        now["t"] += 6
        return [_comment(1)]

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)
    deadline = extract_mod._GithubReadDeadline(10)

    capture = _github_paginated_list(COMMENTS_API, 10, deadline=deadline)

    assert capture["pages"] == 2
    assert capture["deadline_exhausted"] is True
    assert capture["error"] == ""
    assert "deadline expired" in _github_capture_summary("Conversation comments", capture)


def test_complete_capture_is_unchanged(monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 100)

    def fake(api: str, timeout: float = 15):
        return [_comment(1), _comment(2)]

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    capture = _github_paginated_list(COMMENTS_API, 10)

    assert capture["complete"] is True
    assert capture["error"] == ""
    assert capture["next_url"] == ""
    assert "complete for this endpoint" in _github_capture_summary(
        "Conversation comments", capture, total=2
    )
