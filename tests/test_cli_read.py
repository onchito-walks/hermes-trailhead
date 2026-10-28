"""Contracts for `hermes-trailhead read` — native known-URL reading.

Every test injects a fake `extract_hits`, so the suite never touches the
network and never depends on an Agent Reach install.
"""
from __future__ import annotations

import json
import os

import pytest

from hermes_trailhead import cli
from hermes_trailhead.cli import main
from hermes_trailhead.extract import ExtractedHit, ExtractionResult, SourceType, VideoEvidence


URL = "https://example.com/known-page"


def _fake_extract(monkeypatch, extraction: ExtractionResult, calls: list | None = None):
    """Replace cli.extract_hits with a one-hit stub and record its arguments."""

    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        if calls is not None:
            calls.append(
                {
                    "hits": hits,
                    "limit": limit,
                    "timeout": timeout,
                    "extract": extract,
                    "fetch": fetch,
                }
            )
        hit = hits[0]
        return (
            ExtractedHit(
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
                extraction=extraction,
                query=getattr(hit, "query", ""),
            ),
        )

    monkeypatch.setattr(cli, "extract_hits", fake)
    return fake


def _ok_result(content: str, *, source_type: SourceType = "web", **kwargs) -> ExtractionResult:
    return ExtractionResult(
        status="ok",
        content=content,
        content_length=len(content),
        source_type=source_type,
        **kwargs,
    )


def _run_json(capsys, argv: list[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured.err


def test_read_success_json_contract(monkeypatch, capsys):
    content = "Readable page body. " * 20
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result(content), calls)

    rc, payload, err = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert err == ""
    assert payload["command"] == "read"
    assert payload["schema_version"] == 1
    assert payload["ok"] is True
    assert payload["url"] == URL
    assert payload["source_type"] == "web"
    assert payload["timeout_seconds"] == 15
    assert payload["extraction_status"] == "ok"
    assert payload["content_length"] == len(content)
    assert payload["returned_chars"] == len(content)
    assert payload["truncated"] is False
    assert payload["truncation_note"] == ""
    assert payload["content"] == content
    assert payload["error"] is None
    assert payload["evidence"]["usable"] is True
    assert payload["evidence"]["transport_ok"] is True
    assert payload["evidence"]["relevance"] == "unknown"
    assert payload["evidence"]["source_quality"]["quality"]
    assert payload["video_evidence"] is None
    # One hit, extraction limit 1, URL carried through unchanged.
    assert calls[0]["limit"] == 1
    assert calls[0]["timeout"] == 15
    assert calls[0]["hits"][0].url == URL
    assert calls[0]["fetch"] is None


def test_read_policy_declares_no_agent_reach_no_asr(monkeypatch, capsys):
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20))

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["asr"]["enabled"] is False
    assert payload["asr"]["env"] == "TRAILHEAD_DISABLE_ASR"
    assert payload["policy"]["agent_reach"] == "not_used"
    assert payload["policy"]["asr"] == "disabled"
    assert payload["policy"]["hermes_web_extract"] == "disabled"


def test_read_forces_asr_off_and_restores_unset_env(monkeypatch, capsys):
    monkeypatch.delenv(cli.READ_ASR_ENV, raising=False)
    seen: dict[str, str | None] = {}
    extraction = _ok_result("Readable page body. " * 20)

    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        seen["asr"] = os.environ.get(cli.READ_ASR_ENV)
        return (ExtractedHit(title="", url=hits[0].url, extraction=extraction),)

    monkeypatch.setattr(cli, "extract_hits", fake)

    rc = main(["read", URL, "--format", "json"])

    assert rc == 0
    assert seen["asr"] == "1"
    assert cli.READ_ASR_ENV not in os.environ


def test_read_restores_preexisting_asr_env_value(monkeypatch, capsys):
    monkeypatch.setenv(cli.READ_ASR_ENV, "0")
    seen: dict[str, str | None] = {}

    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        seen["asr"] = os.environ.get(cli.READ_ASR_ENV)
        return (
            ExtractedHit(
                title="",
                url=hits[0].url,
                extraction=_ok_result("Readable page body. " * 20),
            ),
        )

    monkeypatch.setattr(cli, "extract_hits", fake)

    assert main(["read", URL, "--format", "json"]) == 0
    assert seen["asr"] == "1"
    assert os.environ[cli.READ_ASR_ENV] == "0"


def test_read_disables_model_backed_web_extract_fallback(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    _run_json(capsys, ["read", URL, "--format", "json"])

    disabled = calls[0]["extract"]
    assert callable(disabled)
    with pytest.raises(RuntimeError, match="web_extract"):
        disabled(URL, 15)


def test_read_blocked_returns_nonzero_and_stable_error(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="blocked",
            source_type="x",
            error_message="x content requires browser/session",
        ),
    )

    rc, payload, _ = _run_json(capsys, ["read", "https://x.com/someone/status/1", "--format", "json"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["extraction_status"] == "blocked"
    assert payload["error"]["code"] == "extraction_blocked"
    assert payload["error"]["message"] == "x content requires browser/session"
    assert payload["evidence"]["usable"] is False
    assert payload["content"] == ""


def test_read_transport_error_returns_nonzero(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="error",
            source_type="web",
            error_message="Could not extract content",
        ),
    )

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["error"]["code"] == "extraction_error"
    assert payload["evidence"]["transport_ok"] is False


def test_read_routes_error_does_not_imply_disabled_llm_tier_ran(monkeypatch, capsys):
    _fake_extract(
        monkeypatch,
        ExtractionResult(
            status="error",
            source_type="web",
            error_message=(
                "Could not extract content from https://example.com via Hermes "
                "web_extract, direct fetch, or Jina fetch"
            ),
        ),
    )

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["error"]["code"] == "extraction_error"
    assert "disabled for read" in payload["error"]["message"]


def test_read_too_short_success_is_unusable_and_nonzero(monkeypatch, capsys):
    _fake_extract(monkeypatch, _ok_result("tiny"))

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["extraction_status"] == "ok"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unusable_evidence"
    assert payload["evidence"]["usable"] is False
    assert any("usable evidence needs more than" in r for r in payload["evidence"]["reasons"])


def test_read_reports_extractor_truncation_truthfully(monkeypatch, capsys):
    full_measured = 9000
    kept = "A" * 8000
    extraction = ExtractionResult(
        status="ok",
        content=kept,
        content_length=full_measured,
        source_type="web",
    )
    _fake_extract(monkeypatch, extraction)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["truncated"] is True
    assert payload["content_length"] == full_measured
    assert payload["returned_chars"] == len(kept)
    assert len(payload["content"]) == len(kept)
    assert "8000" in payload["truncation_note"]
    assert "9000" in payload["truncation_note"]


def test_read_reports_readable_cap_marker_as_truncation(monkeypatch, capsys):
    capped = ("B" * 20000) + "\n..."
    extraction = ExtractionResult(
        status="ok",
        content=capped,
        content_length=len(capped),
        source_type="web",
    )
    _fake_extract(monkeypatch, extraction)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["content_length"] == payload["returned_chars"]
    assert payload["truncated"] is True
    assert "readable-text cap" in payload["truncation_note"]


def test_read_surfaces_transcript_evidence_fields(monkeypatch, capsys):
    video = VideoEvidence(
        caption_status="ok",
        caption_text="A public caption",
        caption_transcript_status="not_attempted",
        audio_transcript_status="not_configured",
        metadata_url=URL,
    )
    extraction = ExtractionResult(
        status="ok",
        content="YouTube transcript body " * 10,
        content_length=len("YouTube transcript body " * 10),
        source_type="youtube",
        transcript_attempted=True,
        video_evidence=video,
    )
    _fake_extract(monkeypatch, extraction)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["video_evidence"]["caption_status"] == "ok"
    assert payload["video_evidence"]["caption_transcript_status"] == "not_attempted"
    assert payload["video_evidence"]["audio_transcript_status"] == "not_configured"


def test_read_text_surfaces_asr_opt_in_explanation(monkeypatch, capsys):
    video = VideoEvidence(
        caption_status="ok",
        caption_text="A public caption",
        caption_transcript_status="not_available",
        audio_transcript_status="not_configured",
        audio_transcript_error=(
            "ASR is opt-in and never runs during automatic extraction. "
            "Use 'reach-call youtube transcribe <url> --allow-authenticated "
            "--allow-quota-consuming'."
        ),
        metadata_url=URL,
    )
    extraction = ExtractionResult(
        status="ok",
        content="YouTube page body " * 10,
        content_length=len("YouTube page body " * 10),
        source_type="youtube",
        transcript_attempted=True,
        video_evidence=video,
    )
    _fake_extract(monkeypatch, extraction)

    rc = main(["read", URL])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Transcript: caption=ok" in captured.out
    assert "audio=not_configured" in captured.out
    assert "Audio: ASR is opt-in" in captured.out
    assert "reach-call youtube transcribe" in captured.out


def test_read_timeout_is_passed_through(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json", "--timeout", "7"])

    assert rc == 0
    assert payload["timeout_seconds"] == 7
    assert calls[0]["timeout"] == 7


@pytest.mark.parametrize("bad_timeout", ["0", "121", "-3", "nan", "inf"])
def test_read_rejects_out_of_range_timeout_without_extracting(monkeypatch, capsys, bad_timeout):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, _ = _run_json(
        capsys, ["read", URL, "--format", "json", "--timeout", bad_timeout]
    )

    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_timeout"
    assert payload["extraction_status"] == "not_attempted"
    assert calls == []


@pytest.mark.parametrize("timeout", ["1", "120"])
def test_read_accepts_timeout_boundaries(monkeypatch, capsys, timeout):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json", "--timeout", timeout])

    assert rc == 0
    assert payload["timeout_seconds"] == int(timeout)
    assert calls[0]["timeout"] == int(timeout)


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "example.com/no-scheme",
        "https://",
        "https://exa mple.com/",
        "https://example.com:99999/",
    ],
)
def test_read_rejects_unusable_urls_without_extracting(monkeypatch, capsys, bad_url):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, _ = _run_json(capsys, ["read", bad_url, "--format", "json"])

    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_url"
    assert payload["url"] == bad_url.strip()
    assert payload["content"] == ""
    assert calls == []


def test_read_invalid_url_never_echoes_credentials(monkeypatch, capsys):
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20))

    rc, payload, _ = _run_json(
        capsys, ["read", "https://user:secret@example.com/", "--format", "json"]
    )

    assert rc == 2
    assert payload["error"]["code"] == "invalid_url"
    assert "secret" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("bad_url", "echoed"),
    [
        # Malformed port: urlparse refuses before the credential check runs,
        # so only the textual fallback can keep the password out of output.
        ("http://user:SECRET@example.com:bad/", "http://example.com:bad/"),
        # Out-of-range port, same failure mode.
        ("https://user:SECRET@example.com:99999/", "https://example.com:99999/"),
        # Malformed IPv6 bracket: urlparse itself raises "Invalid IPv6 URL".
        ("http://user:SECRET@[::1", "http://[::1"),
        # Password containing '@': the greedy strip must not leave a tail.
        ("http://user:p@ss:SECRET@example.com:bad/", "http://example.com:bad/"),
    ],
)
def test_read_parse_failure_never_echoes_credentials(monkeypatch, capsys, bad_url, echoed):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, err = _run_json(capsys, ["read", bad_url, "--format", "json"])

    blob = json.dumps(payload) + err
    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_url"
    assert payload["extraction_status"] == "not_attempted"
    assert payload["content"] == ""
    assert payload["url"] == echoed
    assert "SECRET" not in blob
    assert "user:" not in blob
    assert "p@ss" not in blob
    assert calls == []


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://user:SECRET@example.com:bad/",
        "http://user:SECRET@[::1",
        "https://user:SECRET@example.com:99999/",
    ],
)
def test_read_parse_failure_message_is_generic(monkeypatch, capsys, bad_url):
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20))

    rc, payload, _ = _run_json(capsys, ["read", bad_url, "--format", "json"])

    assert rc == 2
    assert payload["error"]["code"] == "invalid_url"
    # The parser's own text ("Port could not be cast ...") is never surfaced.
    assert payload["error"]["message"] == (
        "URL could not be parsed; check the scheme, host, and port"
    )


@pytest.mark.parametrize(
    ("bad_url", "echoed"),
    [
        # Scheme-less authority: urlparse puts "SECRET@..." in the path (scheme
        # "user", empty netloc), so userinfo is not detected by parsing.
        ("user:SECRET@example.com:bad/", "example.com:bad/"),
        ("user:SECRET@example.com/path", "example.com/path"),
    ],
)
def test_read_schemeless_credentials_are_stripped(monkeypatch, capsys, bad_url, echoed):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, err = _run_json(capsys, ["read", bad_url, "--format", "json"])

    assert rc == 2
    assert payload["error"]["code"] == "invalid_url"
    assert payload["url"] == echoed
    assert "SECRET" not in json.dumps(payload) + err
    assert calls == []


def test_read_parse_failure_without_credentials_still_echoes_the_input(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc, payload, _ = _run_json(
        capsys, ["read", "http://[::1", "--format", "json"]
    )

    assert rc == 2
    assert payload["error"]["code"] == "invalid_url"
    # Nothing credential-shaped to hide, so the caller sees what failed.
    assert payload["url"] == "http://[::1"
    assert calls == []


def test_read_text_parse_failure_does_not_leak_credentials_to_stderr(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc = main(["read", "http://user:SECRET@example.com:bad/"])
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.out == ""
    assert "SECRET" not in captured.err
    assert "URL could not be parsed" in captured.err
    assert calls == []


def test_read_json_success_and_error_share_top_level_keys(monkeypatch, capsys):
    extraction = _ok_result("Readable page body. " * 20)
    _fake_extract(monkeypatch, extraction)
    _, success, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    _fake_extract(monkeypatch, ExtractionResult(status="error", error_message="nope"))
    _, failure, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert set(success) == set(failure)
    assert set(success["evidence"]) == set(failure["evidence"])


def test_read_text_format_prints_evidence_and_content(monkeypatch, capsys):
    content = "Readable page body for the text contract. " * 4
    _fake_extract(monkeypatch, _ok_result(content))

    rc = main(["read", URL])
    captured = capsys.readouterr()

    assert rc == 0
    assert f"URL: {URL}" in captured.out
    assert "Evidence: usable=yes" in captured.out
    assert "ASR: disabled" in captured.out
    assert "agent-reach not used" in captured.out
    assert content in captured.out
    assert captured.err == ""


def test_read_text_failure_writes_stderr_and_nonzero(monkeypatch, capsys):
    _fake_extract(monkeypatch, ExtractionResult(status="blocked", error_message="blocked by WAF"))

    rc = main(["read", URL])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Error: extraction_blocked: blocked by WAF" in captured.err
    assert captured.out == ""


def test_read_text_invalid_url_exits_two_on_stderr(monkeypatch, capsys):
    calls: list[dict] = []
    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20), calls)

    rc = main(["read", "not-a-url"])
    captured = capsys.readouterr()

    assert rc == 2
    assert "Error: invalid_url" in captured.err
    assert calls == []


def test_read_unexpected_extractor_exception_is_a_stable_error(monkeypatch, capsys):
    def boom(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(cli, "extract_hits", boom)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["error"]["code"] == "internal_error"
    assert "extractor exploded" in payload["error"]["message"]
    assert payload["evidence"]["usable"] is False


def test_read_does_not_import_agent_reach(monkeypatch, capsys):
    """The native path must not depend on the optional forwarding layer."""
    import hermes_trailhead.cli as cli_module

    _fake_extract(monkeypatch, _ok_result("Readable page body. " * 20))

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("read touched Agent Reach")

    monkeypatch.setattr("hermes_trailhead.reach_backend.AgentReachBackend", explode, raising=False)
    monkeypatch.setattr(cli_module, "AgentReachBackend", explode, raising=False)

    rc = main(["read", URL, "--format", "json"])
    assert rc == 0
