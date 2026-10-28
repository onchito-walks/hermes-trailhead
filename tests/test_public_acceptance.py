"""Contract tests for the public acceptance evidence harness (no network).

These tests pin the parts that must not drift: the frozen manifest covers more
than one language, artifact checks are explicit presence checks (never length
thresholds), and the published evidence keeps its honest shape.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "evaluate_public_acceptance.py"
EVIDENCE = REPO / "docs" / "evidence" / "public-acceptance.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("evaluate_public_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_multilingual_and_explicit():
    module = _load_script()
    manifest = module.MANIFEST
    assert manifest["manifest_version"] >= 1
    languages = {case["language"] for case in manifest["cases"]}
    assert {"en", "zh-Hans"} <= languages
    assert len(manifest["cases"]) >= 3
    for case in manifest["cases"]:
        assert case["artifacts"], case["case_id"]
        assert case["requested_outcome"], case["case_id"]
        for artifact in case["artifacts"]:
            assert artifact["kind"] in {"any_of", "regex_distinct"}
            assert "min_chars" not in artifact  # completeness is never a length gate


def test_artifact_checks_are_presence_not_length():
    module = _load_script()
    artifacts = [
        {"label": "install", "kind": "any_of", "values": ["pip install requests"]},
        {"label": "topic_urls", "kind": "regex_distinct",
         "pattern": r"v2ex\.com/t/\d+", "min_distinct": 2},
    ]
    passing = module.check_artifacts(
        "pip install requests\nhttps://www.v2ex.com/t/1 https://www.v2ex.com/t/2", artifacts
    )
    assert all(check["present"] for check in passing)

    # A very long page with none of the requested artifacts must still fail.
    failing = module.check_artifacts("x" * 50_000, artifacts)
    assert [check["present"] for check in failing] == [False, False]
    assert failing[1]["distinct_found"] == 0


def test_published_evidence_keeps_honest_shape():
    assert EVIDENCE.exists(), "run scripts/evaluate_public_acceptance.py to produce evidence"
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["schema"] == "trailhead.public-acceptance/1"
    claim = evidence["summary"]["superiority_claim"].lower()
    assert claim.startswith("not established"), claim

    # The reference tool must be identified by source, not just a version string.
    distribution = evidence["tools"]["agent_reach"]["distribution"]
    assert distribution["version"].startswith("1.6.")
    assert "14c213405669414492bda0f8d52cc6531d062c45" in distribution["direct_url"]

    assert len(evidence["runs"]) >= 3
    for run in evidence["runs"]:
        assert run["run_kind"] in {"cold", "warm"}
        assert run["wall_s"] > 0
        assert run["outcomes"], "a run without per-case outcomes is not evidence"

    # Artifact checks, not character counts, must drive completeness.
    for entry in evidence["completeness"]:
        for side in entry["sides"].values():
            assert side["artifacts_required"] == len(side["checks"])
            assert side["complete"] == all(c["present"] for c in side["checks"])


def test_recorded_counts_are_internally_consistent():
    """Every count in the published JSON must be recomputable from the record."""
    evidence = json.loads(EVIDENCE.read_text())
    runs = evidence["runs"]
    summary = evidence["summary"]

    assert summary["runs"] == len(runs)
    assert summary["cold_runs"] == sum(1 for r in runs if r["run_kind"] == "cold")
    assert summary["warm_runs"] == sum(1 for r in runs if r["run_kind"] == "warm")
    assert summary["wall_s"]["cold"] == [r["wall_s"] for r in runs if r["run_kind"] == "cold"]
    assert summary["peak_rss_kb"]["warm"] == [
        r["peak_rss_kb"] for r in runs if r["run_kind"] == "warm"
    ]

    completeness = evidence["completeness"]
    assert summary["cases_total"] == len(completeness)
    for side in ("trailhead", "agent_reach"):
        recomputed = sum(1 for e in completeness if e["sides"][side]["complete"])
        assert summary["artifact_complete_cases"][side] == recomputed
        assert all(
            e["sides"][side]["artifacts_present"]
            == sum(1 for c in e["sides"][side]["checks"] if c["present"])
            for e in completeness
        )

    # Gaps are exactly the failing markers, no more and no fewer.
    recomputed_gaps = sorted(
        (e["case_id"], side, tuple(sorted(
            c["label"] for c in e["sides"][side]["checks"] if not c["present"]
        )))
        for e in completeness
        for side in ("trailhead", "agent_reach")
        if any(not c["present"] for c in e["sides"][side]["checks"])
    )
    recorded_gaps = sorted(
        (g["case_id"], g["side"], tuple(sorted(g["missing_artifacts"])))
        for g in evidence["gaps"]
    )
    assert recorded_gaps == recomputed_gaps

    # The advertised reference surface is counted by the product, not retyped.
    from hermes_trailhead.reach_backend import parity_inventory

    assert evidence["reference_actions"]["actions_total"] == (
        parity_inventory()["counts"]["actions"]
    )

    # Marker presence is explicitly not completeness proof, and RSS is not per tool.
    assert "presence only" in summary["artifact_marker_scope"]
    assert evidence["measurement"]["per_tool_rss"] is False

    # The shipped `read` command was exercised for every case.
    assert summary["read_cli_cases_ok"] == len(completeness)
    for entry in completeness:
        read_cli = entry["read_cli"]
        assert read_cli["artifacts_required"] == len(read_cli["checks"])
        assert read_cli["artifacts_present"] == sum(
            1 for c in read_cli["checks"] if c["present"]
        )


def test_before_fix_evidence_is_retained():
    before_path = EVIDENCE.parent / "public-acceptance-before.json"
    assert before_path.exists(), "pre-fix evidence must stay available for comparison"
    before = json.loads(before_path.read_text())
    after = json.loads(EVIDENCE.read_text())
    assert before["schema"] == after["schema"]
    # It is a snapshot of the earlier run, not a copy of the current one.
    assert before["generated_at"] != after["generated_at"]
    assert before["summary"]["artifact_complete_cases"] != after["summary"]["artifact_complete_cases"]


def test_evidence_is_sanitized():
    evidence = json.loads(EVIDENCE.read_text())
    blob = json.dumps(evidence)
    # No credential-shaped values, no absolute host usernames, no tokens.
    assert not re.search(r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}", blob)
    for prefix in ("/srv/", "/home/", "/Users/", "/root/"):
        assert prefix not in blob, prefix
    for forbidden in ("Authorization", "Cookie", "Bearer "):
        assert forbidden not in blob
