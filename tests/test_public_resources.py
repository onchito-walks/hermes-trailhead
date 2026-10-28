"""Contract tests for the frozen per-tool public resource campaign (no network).

What is pinned here:

* the frozen manifest is hashed, immutable in shape and carries no host paths;
* one measured invocation is one tool process under one killable deadline, and
  its RSS/CPU come from that child's rusage (never a comparator);
* artifact assessment separates ``present`` / ``absent`` / ``unverified``,
  attributes metadata matches to metadata, and **cannot** turn marker presence
  into a completeness claim;
* the published evidence keeps per-tool separation, the planned denominators
  and the "no winner" framing.

The live campaign itself is not run here: these tests use synthetic payloads and
local child processes only.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "evaluate_public_resources.py"
MANIFEST = REPO / "docs" / "evidence" / "public-remaining-manifest.json"
EVIDENCE = REPO / "docs" / "evidence" / "public-resource.json"


def _load():
    spec = importlib.util.spec_from_file_location("evaluate_public_resources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load()


# ── manifest ────────────────────────────────────────────────────────────────

def test_manifest_covers_docs_github_and_v2ex_with_placeholders():
    manifest = MODULE.build_manifest("reviewer", 25.0, 5)
    cases = manifest["cases"]
    assert {c["family"] for c in cases} == {"docs", "github", "v2ex"}
    assert len(cases) == 3
    for case in cases:
        assert case["lane"] == "public"
        assert case["requested_outcome"]
        assert case["artifact_units"]
        assert case["truncation_matters"] is True
        for unit in case["artifact_units"]:
            assert unit["kind"] in {"text_any_of", "regex_distinct", "field_present"}
            assert "min_chars" not in unit, "completeness is never a length gate"
            assert isinstance(unit.get("whole_artifact"), bool)
        argv = case["tool_argv"]
        # Published argv must not leak a host path or a venv location.
        assert argv["trailhead"][0] == "python"
        assert argv["agent_reach"][0] == "<agent-reach>"
        for parts in argv.values():
            assert "<path>" not in parts
            assert not any(part.startswith("/") for part in parts), parts
            assert "--timeout" in parts and parts[parts.index("--timeout") + 1] == "25"

    frozen_rules = manifest["rules"]
    assert frozen_rules["completeness_claim"].startswith("none")
    assert frozen_rules["pagination_unknown"].startswith("counts as not exhausted")
    assert "markers_present" in frozen_rules["verdict_vocabulary"]
    assert "complete" not in frozen_rules["verdict_vocabulary"]


def test_manifest_hash_is_canonical_and_tamper_evident():
    manifest = MODULE.build_manifest("reviewer", 25.0, 5, frozen_at="2026-10-28T00:00:00Z")
    assert manifest["manifest_sha256"] == MODULE.manifest_hash(manifest)
    # Key order must not matter for the hash.
    reordered = dict(reversed(list(manifest.items())))
    assert MODULE.manifest_hash(reordered) == manifest["manifest_sha256"]
    assert MODULE.verify_manifest(manifest) == (True, "")

    tampered = json.loads(json.dumps(manifest))
    tampered["cases"][0]["artifact_units"][0]["values"].append("extra")
    ok, why = MODULE.verify_manifest(tampered)
    assert not ok and "mismatch" in why

    missing = json.loads(json.dumps(manifest))
    missing.pop("manifest_sha256")
    ok, why = MODULE.verify_manifest(missing)
    assert not ok and "no manifest_sha256" in why


def test_frozen_manifest_on_disk_verifies_and_is_not_rewritten(tmp_path):
    assert MANIFEST.exists(), "freeze with --freeze before any measured run"
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["schema"] == MODULE.MANIFEST_SCHEMA
    assert manifest["frozen_by"]
    assert manifest["frozen_at"].endswith("Z")
    assert MODULE.verify_manifest(manifest)[0], "frozen manifest no longer matches its hash"
    assert len(manifest["cases"]) == 3

    # A second freeze must not silently replace a frozen manifest.
    before = MANIFEST.read_text()
    assert MODULE.main(["--freeze", "--manifest", str(MANIFEST)]) == 2
    assert MANIFEST.read_text() == before
    # ... and an explicit refreeze is what a new campaign would use.
    copy = tmp_path / "copy.json"
    copy.write_text(before)
    assert MODULE.main(["--freeze", "--refreeze", "--manifest", str(copy)]) == 0
    assert json.loads(copy.read_text())["manifest_sha256"] != manifest["manifest_sha256"]


# ── payload reading ─────────────────────────────────────────────────────────

def test_trailhead_payload_splits_body_from_metadata():
    raw = json.dumps({
        "ok": True, "url": "https://example.org/page", "source_type": "http",
        "extraction_status": "ok", "content": "body text with Protocol",
        "truncated": False, "pagination": {"more": False, "next_offset": None},
        "returned_chars": 21,
    })
    payload = MODULE.read_payload("trailhead", raw)
    assert payload["parsed"] and payload["ok"]
    assert payload["body"] == "body text with Protocol"
    assert "example.org" in payload["metadata"]
    assert "Protocol" not in payload["metadata"]
    assert payload["truncated"] is False
    assert payload["continuation"]["state"] == "exhausted"


def test_trailhead_pagination_pending_is_not_exhausted():
    raw = json.dumps({"ok": True, "content": "x", "truncated": True,
                      "pagination": {"more": True, "next_offset": 20000}})
    payload = MODULE.read_payload("trailhead", raw)
    assert payload["continuation"]["state"] == "pending"
    assert payload["truncated"] is True


def test_agent_reach_payload_leaves_truncation_and_pagination_unknown():
    raw = json.dumps({
        "ok": True, "backend": "gh", "channel": "github", "action": "read",
        "items": [{"title": "psf/requests", "url": "https://github.com/psf/requests",
                   "text": "install: pip install requests"}],
    })
    payload = MODULE.read_payload("agent_reach", raw)
    assert payload["body"] == "install: pip install requests"
    assert "psf/requests" in payload["metadata"]
    # The upstream payload says nothing about truncation: unknown, never False.
    assert payload["truncated"] is None
    assert payload["continuation"]["state"] == "unknown"
    assert payload["items"] == 1


def test_unparsable_stdout_is_not_an_artifact():
    payload = MODULE.read_payload("trailhead", "<html>502 bad gateway</html>")
    assert payload["parsed"] is False
    assert payload["body"] == ""


# ── artifact units ──────────────────────────────────────────────────────────

DOCS_UNITS = [
    {"id": "identity", "kind": "text_any_of", "values": ["Support for type hints"],
     "required": True, "whole_artifact": True},
    {"id": "entry", "kind": "text_any_of", "values": ["Protocol"], "required": True},
    {"id": "urls", "kind": "regex_distinct", "pattern": r"v2ex\.com/t/\d+",
     "min_distinct": 2, "required": True},
    {"id": "url_field", "kind": "field_present", "field": "url", "required": False},
]


def _th(content: str, **extra) -> dict:
    payload = {"ok": True, "url": "https://example.org/p", "content": content,
               "truncated": False, "pagination": {"more": False, "next_offset": None}}
    payload.update(extra)
    return MODULE.read_payload("trailhead", json.dumps(payload))


def test_unit_states_present_absent_unverified():
    present = MODULE.assess_units(DOCS_UNITS, _th(
        "Support for type hints Protocol https://www.v2ex.com/t/1 https://www.v2ex.com/t/2"))
    states = {u["id"]: u["state"] for u in present}
    assert states["identity"] == "present"
    assert states["urls"] == "present"
    assert states["url_field"] == "present"

    absent = MODULE.assess_units(DOCS_UNITS, _th("x" * 50_000))
    states = {u["id"]: u["state"] for u in absent}
    assert states["identity"] == "absent"
    assert states["entry"] == "absent"
    assert absent[2]["distinct_found"] == 0

    unverified = MODULE.assess_units(DOCS_UNITS, MODULE.read_payload("trailhead", "not json"))
    assert {u["state"] for u in unverified} == {"unverified"}, \
        "no artifact means unverified, never absent"


def test_metadata_match_is_not_body_text():
    units = [{"id": "identity", "kind": "text_any_of",
              "values": ["https://example.org/p"], "required": True}]
    payload = MODULE.read_payload("trailhead", json.dumps(
        {"ok": True, "url": "https://example.org/p", "content": "nothing here"}))
    row = MODULE.assess_units(units, payload)[0]
    assert row["state"] == "present"
    assert row["region"] == "metadata_field"
    assert row["reason"], "a metadata hit must say it is not body text"


def test_regex_distinct_counts_distinct_not_repeats():
    units = [{"id": "urls", "kind": "regex_distinct", "pattern": r"v2ex\.com/t/\d+",
              "min_distinct": 2, "required": True}]
    row = MODULE.assess_units(
        units, _th("https://www.v2ex.com/t/7 https://www.v2ex.com/t/7"))[0]
    assert row["state"] == "absent"
    assert row["distinct_found"] == 1


def test_context_is_bounded():
    row = MODULE.assess_units(DOCS_UNITS, _th("a" * 500 + "Protocol" + "b" * 500))[1]
    assert row["state"] == "present"
    assert len(row["context"]) <= 2 * MODULE.CONTEXT_CHARS + len("Protocol") + 2


# ── verdicts: marker presence is never completeness ────────────────────────

def test_all_markers_present_is_markers_present_not_complete():
    payload = _th("Support for type hints Protocol")
    units = MODULE.assess_units(DOCS_UNITS[:2], payload)
    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "markers_present"
    assert verdict["completeness_claim"] == "none"
    assert verdict["verdict"] != "complete"


def test_missing_required_unit_is_incomplete():
    payload = _th("Support for type hints")
    units = MODULE.assess_units(DOCS_UNITS[:2], payload)
    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "incomplete"
    assert any(r.startswith("required_unit_absent:entry") for r in verdict["reasons"])


def test_truncation_blocks_markers_present():
    payload = _th("Support for type hints Protocol", truncated=True)
    units = MODULE.assess_units(DOCS_UNITS[:2], payload)
    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "incomplete"
    assert any("truncated" in r for r in verdict["reasons"])


def test_unknown_truncation_blocks_markers_present():
    ar = MODULE.read_payload("agent_reach", json.dumps(
        {"ok": True, "items": [{"text": "Support for type hints Protocol"}]}))
    units = MODULE.assess_units(DOCS_UNITS[:2], ar)
    verdict = MODULE.case_verdict(units, ar,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "incomplete"
    assert any("truncation_unverified" in r for r in verdict["reasons"])


def test_unexhausted_continuation_blocks_markers_present():
    payload = _th("Support for type hints Protocol",
                  pagination={"more": True, "next_offset": 20000})
    units = MODULE.assess_units(DOCS_UNITS[:2], payload)
    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "page"})
    assert verdict["verdict"] == "incomplete"
    assert any("continuation_not_exhausted" in r for r in verdict["reasons"])


def test_no_payload_is_unverified():
    payload = MODULE.read_payload("trailhead", "")
    units = MODULE.assess_units(DOCS_UNITS, payload)
    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "unverified"


def test_tool_error_envelope_is_unverified_not_incomplete():
    """A failed run returned no artifact: its units are unverified, not absent.

    Counting a rate limit as "required marker absent" would publish a failure to
    produce an artifact as a statement about the artifact's contents.
    """
    raw = json.dumps({
        "ok": False, "channel": "github", "action": "read", "backend": None,
        "items": [],
        "error": {"code": "RATE_LIMITED", "message": "GitHub API rate limit (60/hour)"},
    })
    payload = MODULE.read_payload("agent_reach", raw)
    assert payload["parsed"] is True and payload["ok"] is False
    units = MODULE.assess_units(DOCS_UNITS, payload)
    assert {u["state"] for u in units} == {"unverified"}
    assert all("RATE_LIMITED" in u["reason"] or u["reason"] for u in units)

    verdict = MODULE.case_verdict(units, payload,
                                 {"whole_artifact": True, "continuation": "none"})
    assert verdict["verdict"] == "unverified", verdict
    assert verdict["required_total"] == 3
    assert verdict["required_present"] == 0
    assert verdict["required_assessed"] == 0
    assert verdict["completeness_claim"] == "none"


def test_presence_denominator_reports_unassessed_units():
    """Denominators must show units that never had an artifact to be judged on."""
    assessed_row = {
        "verdict": "incomplete", "required_present": 1, "required_total": 3,
        "required_assessed": 3, "status": "ok", "truncated": None,
        "wall_s": 1.0, "cpu_user_s": 0.1, "cpu_sys_s": 0.0, "peak_rss_kb": 1024,
        "stdout_bytes": 10, "stderr_bytes": 0, "raw_capped": False, "timed_out": False,
    }
    failed_row = {
        "verdict": "unverified", "required_present": 0, "required_total": 2,
        "required_assessed": 0, "status": "exit:1", "truncated": None,
        "wall_s": 0.2, "cpu_user_s": 0.0, "cpu_sys_s": 0.0, "peak_rss_kb": 1024,
        "stdout_bytes": 10, "stderr_bytes": 0, "raw_capped": False, "timed_out": False,
    }
    presence = MODULE._summarize([assessed_row, failed_row])["required_unit_presence"]
    assert presence["present"] == 1
    assert presence["total"] == 5
    assert presence["assessed"] == 3
    assert presence["unassessed"] == 2
    assert presence["present"] <= presence["assessed"] <= presence["total"]


def test_frozen_by_default_is_not_an_independence_claim():
    assert "independent" not in MODULE.DEFAULT_FROZEN_BY.lower()
    manifest = MODULE.build_manifest(MODULE.DEFAULT_FROZEN_BY, 25.0, 1)
    assert manifest["frozen_by"] == MODULE.DEFAULT_FROZEN_BY


def test_verdict_vocabulary_never_claims_completeness():
    for word in MODULE.FORBIDDEN_VERDICTS:
        assert word not in {"markers_present", "incomplete", "unverified"}


# ── statistics / argv / env ────────────────────────────────────────────────

def test_distribution_reports_median_and_range():
    dist = MODULE.distribution([3, 1, 2, None, "x"])
    assert dist == {"n": 3, "min": 1, "median": 2, "max": 3}
    assert MODULE.distribution([]) == {"n": 0, "min": None, "median": None, "max": None}


def test_tool_argv_resolves_placeholders_and_keeps_one_deadline():
    manifest = MODULE.build_manifest("reviewer", 25.0, 5)
    case = manifest["cases"][0]
    th = MODULE.tool_argv("trailhead", case, "/opt/x/bin/agent-reach", 25.0)
    ar = MODULE.tool_argv("agent_reach", case, "/opt/x/bin/agent-reach", 25.0)
    assert th[0] == sys.executable
    assert ar[0] == "/opt/x/bin/agent-reach"
    assert th[th.index("--timeout") + 1] == "25"
    assert ar[ar.index("--timeout") + 1] == "25"
    assert "<agent-reach>" not in ar


def test_check_env_fails_closed_on_credentials_and_asr():
    ok = {"PATH": "/usr/bin", "HOME": "/tmp/x", "TRAILHEAD_DISABLE_ASR": "1"}
    MODULE.check_env(ok)
    for bad in (
        {**ok, "GITHUB_TOKEN": "x"},
        {**ok, "HTTP_PROXY": "http://p"},
        {"PATH": "/usr/bin", "HOME": "/tmp/x"},
        {**ok, "LD_PRELOAD": "/x.so"},
    ):
        with pytest.raises(SystemExit):
            MODULE.check_env(bad)


def test_scrub_removes_host_paths():
    scrubbed = MODULE._scrub("failed at /home/alice/work/.venv/bin/python and /srv/minio/x")
    assert "/home/alice" not in scrubbed
    assert "/srv/minio" not in scrubbed
    assert "<path>" in scrubbed


# ── measurement: one tool child per invocation ─────────────────────────────

def test_measure_once_measures_one_child_and_kills_at_the_deadline(tmp_path):
    fast = MODULE.measure_once(
        [sys.executable, "-c", "print('hi')"],
        env={"PATH": "/usr/bin", "TRAILHEAD_DISABLE_ASR": "1"},
        cwd=str(tmp_path), timeout_s=20.0,
        stdout_path=tmp_path / "fast.out", stderr_path=tmp_path / "fast.err",
        max_raw_bytes=1024,
    )
    assert fast["status"] == "ok", fast
    assert fast["exit_code"] == 0
    assert fast["peak_rss_kb"] and fast["peak_rss_kb"] > 0
    assert fast["cpu_user_s"] is not None and fast["cpu_sys_s"] is not None
    assert fast["wall_s"] and fast["wall_s"] < 20
    assert fast["stdout_bytes"] > 0

    slow = MODULE.measure_once(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        env={"PATH": "/usr/bin", "TRAILHEAD_DISABLE_ASR": "1"},
        cwd=str(tmp_path), timeout_s=0.5,
        stdout_path=tmp_path / "slow.out", stderr_path=tmp_path / "slow.err",
        max_raw_bytes=1024,
    )
    assert slow["timed_out"] is True
    assert slow["status"] == "timeout"
    assert slow["wall_s"] is not None and slow["wall_s"] < 15, \
        "the group deadline must actually kill the child"


def test_measure_once_caps_raw_stdout(tmp_path):
    result = MODULE.measure_once(
        [sys.executable, "-c", "print('x' * 5000)"],
        env={"PATH": "/usr/bin", "TRAILHEAD_DISABLE_ASR": "1"},
        cwd=str(tmp_path), timeout_s=20.0,
        stdout_path=tmp_path / "big.out", stderr_path=tmp_path / "big.err",
        max_raw_bytes=1024,
    )
    assert result["raw_capped"] is True
    assert (tmp_path / "big.out").stat().st_size == 1024
    assert result["stdout_bytes"] > 1024, "the pre-cap size is what gets recorded"


def test_measure_once_records_a_missing_executable_as_harness_error(tmp_path):
    result = MODULE.measure_once(
        [str(tmp_path / "does-not-exist")],
        env={"PATH": "/usr/bin", "TRAILHEAD_DISABLE_ASR": "1"},
        cwd=str(tmp_path), timeout_s=5.0,
        stdout_path=tmp_path / "missing.out", stderr_path=tmp_path / "missing.err",
        max_raw_bytes=1024,
    )
    assert result["status"] == "harness_error"


def test_a_wrapper_that_writes_no_measurement_is_not_a_success(tmp_path, monkeypatch):
    """No rusage record means nothing was measured — never `status: ok`."""
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], -9, stdout="", stderr="killed by timeout")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    result = MODULE.measure_once(
        [sys.executable, "-c", "print('hi')"],
        env={"PATH": "/usr/bin", "TRAILHEAD_DISABLE_ASR": "1"},
        cwd=str(tmp_path), timeout_s=1.0,
        stdout_path=tmp_path / "gone.out", stderr_path=tmp_path / "gone.err",
        max_raw_bytes=1024,
    )
    assert result["status"] == "harness_error", result
    assert result["wall_s"] is None and result["peak_rss_kb"] is None
    assert "killed by timeout" in result["wrapper"]["stderr"]


# ── published evidence ────────────────────────────────────────────────────

def test_published_evidence_is_per_tool_and_bounded():
    assert EVIDENCE.exists(), "run the campaign to produce docs/evidence/public-resource.json"
    text = EVIDENCE.read_text()
    evidence = json.loads(text)

    assert evidence["schema"] == MODULE.SCHEMA
    assert evidence["manifest"]["recomputed_match"] is True
    frozen = json.loads(MANIFEST.read_text())
    assert evidence["manifest"]["manifest_sha256"] == frozen["manifest_sha256"]

    # No host paths or user names in a published artifact.
    assert not re.search(r"(?<![\w:/])/(?:home|srv|tmp|var|usr|opt|root|mnt)/", text), \
        "published evidence leaks an absolute path"
    assert "@" not in evidence["host"].get("hostname", "")

    design = evidence["design"]
    assert design["tools_per_invocation"] == 1
    assert design["asr"].startswith("TRAILHEAD_DISABLE_ASR=1")

    tool_rows = {r["tool"] for r in evidence["runs"]}
    assert tool_rows == {"trailhead", "agent_reach"}, tool_rows
    for run in evidence["runs"]:
        assert run["state"] in {"cold", "warm"}
        assert run["verdict"] in {"markers_present", "incomplete", "unverified"}
        assert run["verdict"] != "complete"
        assert run["peak_rss_kb"] is None or run["peak_rss_kb"] > 0
        assert run["wall_s"] is None or run["wall_s"] >= 0
        assert run["units"], "a run without per-unit assessment is not evidence"

    assert evidence["totals"]["invocations"] == evidence["totals"]["planned_invocations"]
    assert evidence["totals"]["invocations"] == 3 * 2 * 2 * 5
    for tool in ("trailhead", "agent_reach"):
        assert evidence["totals"]["by_tool"][tool]["paid_calls"] == 0
        assert evidence["totals"]["by_tool"][tool]["auth_calls"] == 0
    assert set(evidence["aggregates"]) == {"trailhead", "agent_reach"}

    claims = json.dumps(evidence["claims"]).lower()
    assert claims.count("none") or "none —" in claims
    assert "not established" in claims
    lowered = text.lower()
    for forbidden in ("is faster", "is better", "winner is", "outperforms"):
        assert forbidden not in lowered
