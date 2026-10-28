"""Aggregate ``read --timeout`` budget for native GitHub issue/PR reads.

A requested read timeout must bound the *whole* artifact — the issue/PR body
plus every paginated comment/review collection — rather than being spent again
on each HTTP request.  Before this contract, one ``read --timeout 10`` of a
pull request could issue ten 10s requests (the pull, three comment pages, three
review pages, three inline-review pages), i.e. a 100s read for a 10s budget.

These tests drive a fake monotonic clock and a fake GitHub fetcher, so they
prove the propagation deterministically: every request must be granted only
the time left, and no request may start after the deadline.  Nothing here
sleeps or touches the network.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _fetch_github_summary,
    _GithubReadDeadline,
    _GithubReadTimeout,
    _github_paginated_list,
)

ISSUE_URL = "https://github.com/example/widget/issues/7"
PULL_URL = "https://github.com/example/widget/pull/9"
ISSUE_PR_URL = "https://github.com/example/widget/issues/9"


class FakeClock:
    """Deterministic stand-in for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def spend(self, seconds: float) -> None:
        self.now += seconds


def _comment(comment_id: int) -> dict:
    return {
        "id": comment_id,
        "user": {"login": "commenter"},
        "created_at": "2026-10-01T00:00:00Z",
        "body": f"comment body {comment_id}",
    }


def _issue_payload(**overrides) -> dict:
    data = {
        "number": 7,
        "id": 700,
        "title": "Primary artifact",
        "state": "open",
        "user": {"login": "reporter"},
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "labels": [],
        "body": "Issue body text that must survive a spent budget.",
        "comments": 0,
        "html_url": ISSUE_URL,
    }
    data.update(overrides)
    return data


def _pull_payload(**overrides) -> dict:
    data = {
        "number": 9,
        "id": 900,
        "title": "Primary pull artifact",
        "state": "open",
        "merged_at": None,
        "merged": False,
        "draft": False,
        "user": {"login": "author"},
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "base": {"label": "example:main", "ref": "main"},
        "head": {"label": None, "ref": "topic"},
        "commits": 1,
        "changed_files": 1,
        "additions": 2,
        "deletions": 0,
        "body": "Pull body text that must survive a spent budget.",
        "comments": 0,
        "review_comments": 0,
        "html_url": PULL_URL,
    }
    data.update(overrides)
    return data


class FakeGitHubAPI:
    """Fake ``_github_api_json`` that consumes clock time per request."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        spend: float,
        issue=None,
        pull=None,
        issue_comments=None,
        pull_comments=None,
        reviews=None,
        review_comments=None,
    ) -> None:
        self.clock = clock
        self.spend = spend
        self.issue = issue
        self.pull = pull
        self.issue_comments = issue_comments
        self.pull_comments = pull_comments
        self.reviews = reviews
        self.review_comments = review_comments
        self.calls: list[tuple[str, float]] = []

    def __call__(self, api: str, timeout: float = 15):
        if timeout <= 0:
            raise AssertionError(f"request started after the deadline: {api}")
        self.calls.append((api, timeout))
        # A slow endpoint can spend at most the window it was granted.
        self.clock.spend(min(self.spend, timeout))
        parsed = urlparse(api)
        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        per_page = int(query.get("per_page", ["100"])[0])
        path = parsed.path
        if path.endswith("/comments") and "/pulls/" in path:
            payload = self.review_comments
        elif path.endswith("/reviews"):
            payload = self.reviews
        elif path.endswith("/comments"):
            # A pull's conversation comments live on the /issues/<n> endpoint.
            payload = (
                self.issue_comments
                if self.issue_comments is not None
                else self.pull_comments
            )
        elif "/pulls/" in path:
            payload = self.pull
        elif "/issues/" in path:
            payload = self.issue
        else:  # pragma: no cover - the reader must not call anything else
            raise AssertionError(f"unexpected GitHub API URL: {api}")
        if isinstance(payload, list):
            start = (page - 1) * per_page
            return payload[start : start + per_page]
        if payload is None:
            raise AssertionError(f"no fixture for GitHub API URL: {api}")
        return payload

    @property
    def timeouts(self) -> list[float]:
        return [timeout for _api, timeout in self.calls]

    def paths(self) -> list[str]:
        return [urlparse(api).path for api, _timeout in self.calls]


@pytest.fixture()
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(extract_mod, "_github_monotonic", fake)
    return fake


# ── Deadline primitive ───────────────────────────────────────────────


def test_deadline_counts_down_one_monotonic_budget():
    tick = FakeClock()
    deadline = _GithubReadDeadline(10, clock=tick)

    assert deadline.remaining() == pytest.approx(10.0)
    assert deadline.timeout_for_call("call one") == pytest.approx(10.0)

    tick.spend(4)
    assert deadline.remaining() == pytest.approx(6.0)
    assert deadline.timeout_for_call("call two") == pytest.approx(6.0)
    assert deadline.expired() is False

    tick.spend(6)
    assert deadline.remaining() == 0.0
    assert deadline.expired() is True
    with pytest.raises(_GithubReadTimeout) as excinfo:
        deadline.timeout_for_call("call three")
    assert "deadline of 10s exhausted" in str(excinfo.value)
    assert "Retry with a larger timeout budget" in str(excinfo.value)


# ── Budget propagates and decreases across every request ─────────────


def test_issue_read_grants_only_the_time_left_to_each_comment_page(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 10)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    comments = [_comment(1000 + i) for i in range(60)]
    fake = FakeGitHubAPI(
        clock, spend=2.5, issue=_issue_payload(comments=60), issue_comments=comments
    )
    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    # metadata + three capped comment pages, each granted only what was left
    assert fake.timeouts == pytest.approx([10.0, 7.5, 5.0, 2.5])
    assert clock.now == pytest.approx(10.0)
    assert "Issue body text that must survive a spent budget." in out
    assert "captured 30 of 60" in out
    assert "NOT complete" in out and "next page:" in out
    assert "complete for this endpoint" not in out


def test_pull_read_stops_requesting_once_the_budget_is_exhausted(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 10)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    comments = [_comment(2000 + i) for i in range(60)]
    fake = FakeGitHubAPI(
        clock,
        spend=3.0,
        pull=_pull_payload(comments=60),
        pull_comments=comments,
        reviews=[],
        review_comments=[],
    )
    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    out = _fetch_github_summary(PULL_URL, timeout=10)

    # Four requests fit the 10s budget; reviews/inline reviews never start.
    assert len(fake.calls) == 4
    assert fake.timeouts == pytest.approx([10.0, 7.0, 4.0, 1.0])
    assert clock.now == pytest.approx(10.0)
    assert fake.paths()[-1].endswith("/issues/9/comments")
    assert not any(path.endswith("/reviews") for path in fake.paths())
    assert not any(path.endswith("/pulls/9/comments") for path in fake.paths())

    # The artifact body survives; the uncaptured sections are disclosed, and
    # the result never claims a complete capture.
    assert "Pull body text that must survive a spent budget." in out
    assert "Reviews: not captured" in out
    assert "Inline review comments: not captured" in out
    assert "the read deadline" in out
    assert "incomplete and must not be reported as full" in out
    assert "complete for this endpoint" not in out
    assert "is NOT the complete PR conversation" in out


def test_expiry_mid_pagination_returns_partial_capture_marked_incomplete(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 10)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    comments = [_comment(3000 + i) for i in range(60)]
    fake = FakeGitHubAPI(
        clock, spend=5.0, issue=_issue_payload(comments=60), issue_comments=comments
    )
    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    out = _fetch_github_summary(ISSUE_URL, timeout=10)

    # metadata (granted 10, spent 5) + page 1 (granted 5, spent 5) → expired
    assert fake.timeouts == pytest.approx([10.0, 5.0])
    assert len(fake.calls) == 2  # page 2 was never requested
    assert "captured 10 of 60" in out
    assert "NOT complete — the read deadline expired" in out
    assert "next page: https://api.github.com/repos/example/widget/issues/7/comments?per_page=10&page=2" in out
    assert "comment body 3000" in out
    assert "comment body 3010" not in out


def test_no_request_is_made_when_the_budget_starts_exhausted(clock, monkeypatch):
    fake = FakeGitHubAPI(clock, spend=1.0, issue=_issue_payload())
    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    with pytest.raises(_GithubReadTimeout) as excinfo:
        _fetch_github_summary(ISSUE_URL, timeout=0)

    assert fake.calls == []
    assert "0s" in str(excinfo.value)
    assert "Retry with a larger timeout budget" in str(excinfo.value)


def test_issue_that_is_a_pull_keeps_the_same_budget_across_the_handoff(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 10)
    fake = FakeGitHubAPI(
        clock,
        spend=1.0,
        issue=_issue_payload(
            number=9,
            pull_request={"url": "https://api.github.com/repos/example/widget/pulls/9"},
        ),
        pull=_pull_payload(),
        pull_comments=[],
        reviews=[],
        review_comments=[],
    )
    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    out = _fetch_github_summary(ISSUE_PR_URL, timeout=10)

    # The pull lookup is call two and is granted 9s, not a fresh 10s window.
    assert fake.timeouts[0] == pytest.approx(10.0)
    assert fake.timeouts[1] == pytest.approx(9.0)
    assert all(later < earlier for earlier, later in zip(fake.timeouts, fake.timeouts[1:]))
    assert clock.now <= 10.0
    assert out.startswith("GitHub pull request example/widget#9: Primary pull artifact")


# ── Compatibility for callers that pass a plain per-request timeout ──


def test_paginated_list_without_a_deadline_keeps_the_legacy_timeout(monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 3)
    seen: list[float] = []

    def fake(api: str, timeout: float = 15):
        seen.append(timeout)
        return [_comment(1), _comment(2)]

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)

    capture = _github_paginated_list(
        "https://api.github.com/repos/o/r/issues/1/comments", 10
    )

    assert seen == [10, 10, 10]  # unchanged out-of-scope contract: no budget
    assert capture["pages"] == 3
    assert capture["complete"] is False
    assert capture["deadline_exhausted"] is False
    assert capture["next_url"].endswith("page=4")


def test_paginated_list_with_a_deadline_passes_the_remaining_window(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(extract_mod, "_GITHUB_LIST_MAX_PAGES", 2)
    seen: list[float] = []

    def fake(api: str, timeout: float = 15):
        seen.append(timeout)
        clock.spend(2)
        return [_comment(1), _comment(2)]

    monkeypatch.setattr(extract_mod, "_github_api_json", fake)
    deadline = _GithubReadDeadline(10, clock=clock)

    capture = _github_paginated_list(
        "https://api.github.com/repos/o/r/issues/1/comments", 10, deadline=deadline
    )

    assert seen == pytest.approx([10.0, 8.0])
    assert capture["pages"] == 2
    assert capture["complete"] is False
    assert capture["deadline_exhausted"] is False
