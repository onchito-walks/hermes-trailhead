"""Regression tests for a reader tier's 404/410 wrapped in HTTP 200.

Reproduced on the committed implementation (HEAD ``6c600b7``) against
``https://github.com/pallets/flask/issues/999999999`` — an issue that does not
exist.  The GitHub API answered 404, ``github.com`` answered 404, but
``r.jina.ai`` answered **200** with its own envelope around the upstream 404
page::

    Title: Build software better, together
    URL Source: https://github.com/pallets/flask/issues/999999999
    Warning: Target URL returned error 404: Not Found
    Markdown Content:
    [Skip to content] ... [Sign in] ... GitHub Copilot ...

``read`` accepted that navigation chrome as evidence: ``ok:true``,
``usable:true``, 6,041 chars, ``source_type:"github"`` — a missing artifact
mislabelled as a successful read.  The fix reads the reader tier's *transport
header* before any body heuristic: a declared upstream 404/410 is
``missing_page`` (other 4xx/5xx is ``blocked``), because the envelope, not the
page, is what the reader shipped.

The boundary this file pins down in both directions:

* the header is authoritative only at the top of a reader envelope — a document
  that *discusses* or *quotes* the same ``Warning:`` line in its body is still a
  document, and no marker list is widened to condemn it;
* a genuine reader envelope with no upstream error (a real issue page, even a
  cached snapshot with a routine ``Warning:``) stays usable, so the fix cannot
  pass by rejecting reader output wholesale.

``tests/fixtures/jina_github_404_envelope.txt`` is the exact 6,049-byte body
captured from ``r.jina.ai`` for that URL during the clean-Linux run; its
SHA-256 is asserted so the regression fixture cannot drift silently.
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _is_usable_page_text,
    _readable_page_result,
    _reader_upstream_status,
    classify_page_shell,
    extract_one,
)

MISSING_ISSUE_URL = "https://github.com/pallets/flask/issues/999999999"

_ENVELOPE_PATH = (
    pathlib.Path(__file__).parent / "fixtures" / "jina_github_404_envelope.txt"
)
_ENVELOPE = _ENVELOPE_PATH.read_text(encoding="utf-8")
_ENVELOPE_SHA256 = "aa58dfb87f4e4e87efd02ec0fd19701f642753860d286710c47ace47e2464f6c"

_LEGIT_ISSUE_ENVELOPE = (
    "Title: Use SQLAlchemy in the core framework as an ORM · Issue #1 · pallets/flask\n"
    "\n"
    "URL Source: https://github.com/pallets/flask/issues/1\n"
    "\n"
    "Warning: This is a cached snapshot of the original page, consider retry "
    "with caching opt-out.\n"
    "\n"
    "Markdown Content:\n"
    "## Use SQLAlchemy in the core framework as an ORM\n"
    "\n"
    "The core framework currently hand-writes its own connection handling. "
    "Wrapping the existing engine in SQLAlchemy would remove a thousand lines "
    "of dialect guesswork and let extensions share one session scope, without "
    "changing the public API that Flask-SQLAlchemy already builds on.\n"
    "\n"
    "Just use the Flask-SQLAlchemy extension was the counter-proposal in the "
    "thread, and it stays the documented answer for application code.\n"
)


def _no_generic_tiers(monkeypatch) -> None:
    """Fail every live tier so the assertions never depend on the network."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("tier unavailable")

    monkeypatch.setattr(extract_mod, "_fetch_github_summary", boom)
    monkeypatch.setattr(extract_mod, "_fetch_text_tiered", boom)
    monkeypatch.setattr(extract_mod, "_fetch_jina", boom)
    monkeypatch.setattr(extract_mod, "_fetch_hermes_web_extract", boom)


# ── 1. The exact captured envelope ───────────────────────────────────────


def test_captured_envelope_fixture_is_the_recorded_artifact():
    assert len(_ENVELOPE.encode("utf-8")) == 6049
    assert hashlib.sha256(_ENVELOPE.encode("utf-8")).hexdigest() == _ENVELOPE_SHA256
    assert _ENVELOPE.startswith(
        "Title: Build software better, together\n"
        "\n"
        f"URL Source: {MISSING_ISSUE_URL}\n"
        "\n"
        "Warning: Target URL returned error 404: Not Found\n"
        "\n"
        "Markdown Content:\n"
    )
    # The body is GitHub navigation chrome: it never says "page not found", so
    # no body-marker list could have condemned it.
    assert "page not found" not in _ENVELOPE.lower()


def test_reader_envelope_reports_the_upstream_status():
    assert _reader_upstream_status(_ENVELOPE) == 404


def test_missing_github_issue_envelope_is_missing_page_not_usable():
    assert classify_page_shell(_ENVELOPE) == "missing_page"
    assert _is_usable_page_text(_ENVELOPE) is False
    assert _readable_page_result(_ENVELOPE) == ""


def test_missing_github_issue_via_injected_fetcher_reports_blocked():
    result = extract_one(
        MISSING_ISSUE_URL,
        fetch=lambda url, timeout: _ENVELOPE,
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )

    assert result.status == "blocked"
    assert result.content == ""
    assert result.content_length == 0
    assert result.usable is False
    assert "missing-page" in result.error_message
    assert "Build software better" not in result.content


def test_missing_github_issue_via_jina_tier_reports_blocked(monkeypatch):
    """The reported route: GitHub API 404, direct fetch 404, Jina 200 wrapper."""

    def failing_github(*_args, **_kwargs):
        raise RuntimeError("HTTP Error 404: Not Found")

    def failing_fetch(*_args, **_kwargs):
        raise OSError("http 404")

    monkeypatch.setattr(extract_mod, "_fetch_github_summary", failing_github)
    monkeypatch.setattr(extract_mod, "_fetch_text_tiered", failing_fetch)
    monkeypatch.setattr(
        extract_mod, "_fetch_jina", lambda url, timeout=30: _ENVELOPE
    )
    monkeypatch.setattr(
        extract_mod,
        "_fetch_hermes_web_extract",
        lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
    )

    result = extract_one(MISSING_ISSUE_URL, timeout=1)

    assert result.status == "blocked"
    assert result.usable is False
    assert result.content == ""
    assert "missing-page" in result.error_message


def test_gone_target_envelope_is_missing_page():
    gone = (
        "Title: Page removed\n"
        "URL Source: https://example.com/old-post\n"
        "Warning: Target URL returned error 410: Gone\n"
        "Markdown Content:\n"
        "This article has been retired.\n"
    )
    assert _reader_upstream_status(gone) == 410
    assert classify_page_shell(gone) == "missing_page"
    assert _readable_page_result(gone) == ""


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_other_upstream_error_envelopes_are_blocked(status):
    """A refusal or upstream failure is not the artifact either."""

    envelope = (
        "Title: Access denied\n"
        "URL Source: https://example.com/private\n"
        f"Warning: Target URL returned error {status}: nope\n"
        "Markdown Content:\n"
        "Sign in to continue.\n"
    )
    assert _reader_upstream_status(envelope) == status
    assert classify_page_shell(envelope) == "blocked"
    assert _readable_page_result(envelope) == ""


def test_x_target_status_header_is_recognized():
    envelope = (
        "Title: Down\n"
        "URL Source: https://example.com/down\n"
        "X-Target-Status: 410\n"
        "Markdown Content:\n"
        "Nothing here.\n"
    )
    assert _reader_upstream_status(envelope) == 410
    assert classify_page_shell(envelope) == "missing_page"


# ── 2. Documents that discuss or quote the same warning stay usable ─────


_DEBUGGING_DOC = """# Debugging Jina reader envelopes

Our fetch layer used to treat `r.jina.ai` output as page text. That is wrong:
when the target is missing, the reader answers 200 with its own header in front
of the vendor's error page, and the body is navigation chrome rather than the
requested artifact.

The failure looks like this:

```text
Title: Build software better, together
URL Source: https://github.com/pallets/flask/issues/999999999
Warning: Target URL returned error 404: Not Found
Markdown Content:
[Skip to content] ...
```

A reader that trusts the body alone reports `ok:true` with about six thousand
characters of menus and marketing copy. The fix is to read the transport header
first: a declared upstream 404/410 means the artifact was never served, while a
document like this one only *quotes* the envelope to explain the bug.
"""


def test_article_discussing_reader_404_envelope_is_usable():
    assert _reader_upstream_status(_DEBUGGING_DOC) is None
    assert classify_page_shell(_DEBUGGING_DOC) is None
    assert _is_usable_page_text(_DEBUGGING_DOC) is True
    assert _readable_page_result(_DEBUGGING_DOC).startswith("# Debugging Jina")


def test_article_discussing_reader_404_envelope_extracts_ok():
    result = extract_one(
        "https://example.com/blog/jina-envelope-404",
        fetch=lambda url, timeout: _DEBUGGING_DOC,
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )
    assert result.status == "ok"
    assert result.usable is True
    assert "Warning: Target URL returned error 404" in result.content


def test_quoted_warning_without_envelope_shape_is_not_transport():
    """A page opening with a bare ``Warning:`` line is prose, not an envelope."""
    quoted = (
        "Warning: Target URL returned error 404: Not Found\n"
        "\n"
        "That is the exact string the reader emits, and this page exists to "
        "explain why a reader must not treat it as page content.\n"
    )
    assert _reader_upstream_status(quoted) is None
    assert classify_page_shell(quoted) is None


# ── 3. Legitimate reader 200 pages keep working ─────────────────────────


def test_legitimate_jina_issue_page_is_still_usable():
    assert _reader_upstream_status(_LEGIT_ISSUE_ENVELOPE) is None
    assert classify_page_shell(_LEGIT_ISSUE_ENVELOPE) is None
    readable = _readable_page_result(_LEGIT_ISSUE_ENVELOPE)
    assert "Use SQLAlchemy in the core framework as an ORM" in readable
    assert _is_usable_page_text(readable) is True


def test_legitimate_jina_issue_page_extracts_ok():
    result = extract_one(
        "https://github.com/pallets/flask/issues/1",
        fetch=lambda url, timeout: _LEGIT_ISSUE_ENVELOPE,
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )
    assert result.status == "ok"
    assert result.usable is True
    assert result.source_type == "github"
    assert "Just use the Flask-SQLAlchemy extension" in result.content


def test_cached_snapshot_warning_alone_never_condemns_a_page():
    cached = _LEGIT_ISSUE_ENVELOPE
    assert "cached snapshot" in cached
    assert classify_page_shell(cached) is None


def test_non_reader_bodies_are_unaffected():
    assert _reader_upstream_status("") is None
    body = "Just a short plain page about nothing in particular.\n"
    assert _reader_upstream_status(body) is None
    assert classify_page_shell(body) is None
