"""Contract tests for the 40-action artifact-evaluation harness (no network).

These pin the parts that must not drift silently:

- the frozen manifest covers the pinned parity inventory exactly, with the
  documented gate split (26 public / 12 consent / 2 quota) and no length
  thresholds;
- units are evaluated from the actual artifact (body vs metadata vs structured
  fields), never from a returned-item count;
- a whole-artifact unit is never reported as proven, and truncation makes a row
  incomplete;
- gated rows are refused without an action process existing;
- the published evidence is internally consistent, sanitized, and makes no
  superiority claim.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from hermes_trailhead.reach_backend import PARITY_ACTIONS, parse_registry

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "evaluate_action_artifacts.py"
EVIDENCE = REPO / "docs" / "evidence" / "action-artifacts-live.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("evaluate_action_artifacts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return _load_script()


@pytest.fixture(scope="module")
def manifest(module):
    return module.build_manifest(limit=2)


def _rows(manifest) -> dict:
    return {(row["channel"], row["action"]): row for row in manifest["rows"]}


def _result(items, *, ok=True, error=None, backend="public-web"):
    return {
        "ok": ok,
        "channel": None,
        "action": None,
        "backend": backend,
        "items": items,
        "error": error,
        "provenance": {"route": "public_web", "home_mode": "isolated-temp"},
        "limitations": [],
        "elapsed_ms": 1,
        "attempts": [],
        "exit_code": 0,
        "timed_out": False,
    }


def _item(**overrides):
    item = {
        "title": "a title",
        "url": "https://example.test/x",
        "url_rejected": False,
        "author": "someone",
        "published_at": "2026-01-01T00:00:00Z",
        "text": "",
        "text_truncated": False,
        "raw": None,
    }
    item.update(overrides)
    return item


# ── manifest ────────────────────────────────────────────────────────────────

def test_manifest_covers_pinned_inventory_exactly(manifest):
    rows = manifest["rows"]
    assert len(rows) == 40 == len(PARITY_ACTIONS)
    assert {(r["channel"], r["action"]) for r in rows} == {p.pair for p in PARITY_ACTIONS}
    assert len({r["channel"] for r in rows}) == 14

    gates = [r["gate"] for r in rows]
    assert (gates.count("public"), gates.count("consent"), gates.count("quota")) == (26, 12, 2)

    for row in rows:
        assert row["requested_outcome"], row
        assert row["units"], row
        assert row["scope"] in {"bounded_request", "whole_artifact"}
        assert row["unknown"], row  # every row names what it cannot know
        for unit in row["units"]:
            assert unit["kind"] in {
                "items_min", "item_field_all", "body_text",
                "no_shell_marker", "target_match", "raw_fields", "raw_fields_any",
            }
            assert "min_chars" not in unit, "completeness must never be a length gate"

    public = [r for r in rows if r["gate"] == "public"]
    gated = [r for r in rows if r["gate"] != "public"]
    assert all(r["params"] for r in public), "a public row needs a frozen real target"
    assert all("source" in r["target_origin"] for r in public)
    assert all(r["params"] == {} for r in gated), "a gated row must not carry a target"


def test_manifest_digest_is_stable(module):
    first = module.build_manifest(limit=2)
    second = module.build_manifest(limit=2)
    assert module.manifest_digest(first) == module.manifest_digest(second)
    assert first == second
    # A changed limit is a different frozen manifest, not a silent edit.
    assert module.manifest_digest(first) != module.manifest_digest(module.build_manifest(limit=3))


# ── unit evaluation ─────────────────────────────────────────────────────────

def test_returned_item_count_does_not_satisfy_a_body_unit(module, manifest):
    frozen = _rows(manifest)[("web", "read")]
    items = [_item(url=frozen["params"]["target"], text=""), _item(text="   ")]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    body = {u["id"]: u for u in row["units"]}
    assert body["body_text"]["status"] == "absent"
    assert row["verdict"] == "incomplete"
    assert row["verdict_reason"].startswith("required_unit_not_present:body_text")
    assert row["artifact"]["max_body_chars"] == 0


def test_metadata_only_listing_is_complete_for_its_bounded_units(module, manifest):
    frozen = _rows(manifest)[("github", "search")]
    items = [
        _item(title="repo one", url="https://github.com/a/one", text=""),
        _item(title="repo two", url="https://github.com/a/two", text=""),
    ]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    units = {u["id"]: u for u in row["units"]}
    assert units["snippet_text"]["status"] == "absent"      # optional unit, recorded
    assert units["snippet_text"]["required"] is False
    assert row["artifact_kind"] == "metadata_only"
    assert row["verdict"] == "complete"                     # bounded request satisfied
    assert row["completeness"]["whole_artifact_requested"] is False


def test_body_and_metadata_regions_are_separate(module, manifest):
    frozen = _rows(manifest)[("v2ex", "read")]
    items = [_item(title="topic", url=frozen["params"]["target"],
                   text="topic body text", author="member")]
    row = module.build_row(frozen, status="inspected", result=_result(items, backend="v2ex-api"),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    regions = {u["id"]: u["region"] for u in row["units"]}
    assert regions["item_identity"] == "metadata"
    assert regions["body_text"] == "body"
    assert regions["requested_target"] == "metadata"


@pytest.mark.parametrize("body", [
    "You've been blocked by network security. To continue, log in to your Reddit account.",
    "你访问的页面不见了，你还可以 返回上一页",
    "## Siden blev ikke fundet",
    "<title>Page not found</title>",
])
def test_shell_pages_are_not_accepted_as_the_requested_artifact(module, manifest, body):
    frozen = _rows(manifest)[("web", "read")]
    items = [_item(url=frozen["params"]["target"], text=body)]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    shell = {u["id"]: u for u in row["units"]}["body_not_error_shell"]
    assert shell["status"] == "absent"
    assert shell["evidence"]
    assert row["artifact_kind"] == "unusable_shell"
    assert row["verdict"] == "incomplete"


def test_shell_scan_is_bounded_to_the_head_window(module):
    # A long article may legitimately discuss a 404 page far below the fold.
    text = "x" * module.SHELL_WINDOW + " page not found"
    assert module._shell_hit(text) is None
    assert module._shell_hit("page not found " + "x" * 50) is not None


def test_truncated_whole_artifact_is_incomplete(module, manifest):
    frozen = _rows(manifest)[("web", "read")]
    text = "a" * module.MAX_TEXT_CHARS
    items = [_item(url=frozen["params"]["target"], text=text, text_truncated=True)]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    assert row["verdict"] == "incomplete"
    assert row["verdict_reason"] == "artifact_truncated_at_output_bound"
    assert row["completeness"]["whole_artifact_proven"] is False
    assert row["completeness"]["caps"]["text_truncated_items"] == 1


def test_caps_report_the_bound_that_governed_the_action(module, manifest):
    """A body read is not capped at the 4000-char discovery snippet bound."""
    rows = _rows(manifest)

    body = rows[("v2ex", "read")]
    assert body["action"] in module.BODY_READ_ACTIONS
    body_text = "a" * (module.MAX_TOTAL_BODY_CHARS + 10)
    row = module.build_row(
        body, status="inspected",
        result=_result([_item(url=body["params"]["target"], text=body_text)]),
        error=None, wall_ms=1, raw_file=None, gate_probe=None,
    )
    caps = row["completeness"]["caps"]
    assert module.MAX_TOTAL_BODY_CHARS == 250_000
    assert caps["max_body_chars_per_result"] == module.MAX_TOTAL_BODY_CHARS
    assert caps["body_budget_shared_across_items"] is True
    assert caps["text_truncated_scope"] == "local_body_budget_cut"
    assert "max_text_chars_per_item" not in caps

    discovery = rows[("github", "search")]
    assert discovery["action"] not in module.BODY_READ_ACTIONS
    row = module.build_row(
        discovery, status="inspected",
        result=_result([_item(
            url="https://github.com/example/repo",
            text="s" * (module.MAX_TEXT_CHARS + 1), text_truncated=True,
        )]),
        error=None, wall_ms=1, raw_file=None, gate_probe=None,
    )
    caps = row["completeness"]["caps"]
    assert module.MAX_TEXT_CHARS == 4000
    assert caps["max_text_chars_per_item"] == module.MAX_TEXT_CHARS
    assert caps["text_truncated_scope"] == "discovery_snippet_clip"
    assert "max_body_chars_per_result" not in caps


def test_untruncated_whole_artifact_is_still_not_proven(module, manifest):
    frozen = _rows(manifest)[("web", "read")]
    items = [_item(url=frozen["params"]["target"], text="short page text")]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    assert row["verdict"] == "incomplete"
    assert row["verdict_reason"] == "end_of_artifact_not_proven"
    assert row["completeness"]["whole_artifact_proven"] is False
    assert "page_end_not_proven" in row["completeness"]["unknown"]


def test_upstream_error_is_preserved_and_unverified(module, manifest):
    frozen = _rows(manifest)[("youtube", "subtitle")]
    result = _result([], ok=False, error={
        "code": "upstream_error",
        "upstream_code": "PLATFORM_BLOCKED",
        "message": "HTTP 403: Forbidden",
        "hint": "platform problem",
    })
    row = module.build_row(frozen, status="failed", result=result, error=None,
                           wall_ms=1, raw_file=None, gate_probe=None)
    assert row["verdict"] == "unverified"
    assert row["error"]["upstream_code"] == "PLATFORM_BLOCKED"
    assert row["error"]["message"] == "HTTP 403: Forbidden"
    assert all(u["status"] == "unverified" for u in row["units"])


def test_error_details_are_preserved_not_flattened(module, manifest):
    frozen = _rows(manifest)[("reddit", "read")]
    result = _result([], ok=False, error={
        "code": "content_unusable",
        "message": "returned no readable content",
        "withheld_items": 1,
        "reasons": ["blocked"],
    })
    row = module.build_row(frozen, status="failed", result=result, error=None,
                           wall_ms=1, raw_file=None, gate_probe=None)
    assert row["error"]["details"] == {"withheld_items": 1, "reasons": ["blocked"]}


def test_deadline_row_is_not_run_and_not_executed(module, manifest):
    frozen = _rows(manifest)[("github", "search")]
    row = module.build_row(frozen, status="deadline_exhausted", result=None, error=None,
                           wall_ms=None, raw_file=None, gate_probe=None)
    assert row["verdict"] == "not_run"
    assert "deadline" in row["verdict_reason"]
    assert all(u["status"] == "not_run" for u in row["units"])


def test_uninspectable_required_unit_is_not_reported_as_absent(module, manifest):
    """A unit that could not be inspected says so; it is not called missing."""
    frozen = _rows(manifest)[("youtube", "read")]
    # Metadata-only artifact: body_text is optional on this row, but the shell
    # scan cannot run without a body, so that required unit is unverified.
    items = [_item(url=frozen["params"]["target"], title="video", author="channel", text="")]
    row = module.build_row(frozen, status="inspected", result=_result(items),
                           error=None, wall_ms=1, raw_file=None, gate_probe=None)
    units = {u["id"]: u for u in row["units"]}
    assert units["body_not_error_shell"]["status"] == "unverified"
    assert row["verdict"] == "incomplete"
    assert row["verdict_reason"] == "required_unit_unverified:body_not_error_shell"


def test_gate_spawn_count_ignores_discovery_argv(module):
    calls = [
        ["/exe", "channels"],
        ["/exe", "channels", "--json"],
        ["/exe", "web", "read", "--"],
    ]
    assert module._action_calls(calls) == [["/exe", "web", "read", "--"]]


# ── gates ───────────────────────────────────────────────────────────────────

def test_gated_rows_refuse_without_an_action_process(module, tmp_path):
    registry = parse_registry({
        "schema_version": 1,
        "ok": True,
        "channels": [
            {
                "name": "twitter",
                "description": "x",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None},
                "actions": [{"name": "profile", "help": "profile", "params": [
                    {"name": "username", "required": True, "type": "str"}]}],
            },
            {
                "name": "youtube",
                "description": "y",
                "level": "default",
                "login": None,
                "actions": [{"name": "transcribe", "help": "asr", "params": [
                    {"name": "target", "required": True, "type": "str"}]}],
            },
        ],
    })
    env = {"TRAILHEAD_DISABLE_ASR": "1"}
    # The executable only has to exist for availability(); the gate refuses
    # before any argv would be built.
    executable = module.sys.executable

    consent = module.check_gate("twitter", "profile", executable, env, registry)
    assert consent["error_code"] == "auth_required"
    assert consent["result_ok"] is False
    assert consent["runner_calls"] == 0
    assert consent["spawned_action_process"] is False
    assert consent["action_argv"] == []

    quota = module.check_gate("youtube", "transcribe", executable, env, registry)
    assert quota["error_code"] == "asr_disabled"
    assert quota["runner_calls"] == 0
    assert quota["spawned_action_process"] is False


# ── summary + published evidence ────────────────────────────────────────────

def test_summary_counts_are_recomputable(module, manifest):
    rows_by = _rows(manifest)
    complete = module.build_row(
        rows_by[("github", "search")], status="inspected",
        result=_result([_item(title="r", url="https://github.com/a/b")]),
        error=None, wall_ms=1, raw_file=None, gate_probe=None)
    truncated = module.build_row(
        rows_by[("github", "read")], status="inspected",
        result=_result([_item(url="https://github.com/a/b", title="a/b",
                              text="a" * module.MAX_TEXT_CHARS, text_truncated=True,
                              raw={"license": "MIT"})], backend="github-api"),
        error=None, wall_ms=1, raw_file=None, gate_probe=None)
    failed = module.build_row(
        rows_by[("twitter", "search")], status="failed",
        result=_result([], ok=False, error={"code": "upstream_error",
                                            "upstream_code": "UPSTREAM_BROKEN",
                                            "message": "broken"}),
        error=None, wall_ms=1, raw_file=None, gate_probe=None)
    gated = module.build_row(
        rows_by[("twitter", "profile")], status="gated_not_run", result=None, error=None,
        wall_ms=None, raw_file=None,
        gate_probe={"error_code": "auth_required", "result_ok": False,
                    "runner_calls": 0, "spawned_action_process": False,
                    "action_argv": [], "asr_veto": True})

    summary = module.summarize([complete, truncated, failed, gated],
                              frozen_at="t", manifest_sha="sha",
                              reference={"version": "1.6.0"},
                              conditions={"auth_consent": False})
    ledger = summary["ledger"]
    assert ledger["actions_total"] == 4
    assert ledger["public"] == 3 and ledger["consent"] == 1 and ledger["quota"] == 0
    assert ledger["executed_public"] == 3
    assert ledger["gated_not_run"] == 1
    assert ledger["failed"] == 1 and ledger["inspected"] == 2

    artifacts = summary["artifact_summary"]
    assert artifacts["verdicts"] == {"complete": 1, "incomplete": 1,
                                     "unverified": 1, "not_run": 1}
    assert artifacts["whole_artifact_proven"] == 0
    units = [u for row in (complete, truncated, failed, gated) for u in row["units"]]
    assert artifacts["units_total"] == len(units)
    assert artifacts["units_required"] == sum(1 for u in units if u["required"])
    assert artifacts["units_present_required"] == sum(
        1 for u in units if u["required"] and u["status"] == "present")
    assert sum(artifacts["units_by_status"].values()) == len(units)
    assert summary["attempt_accounting"]["authenticated_calls"] == 0
    assert summary["attempt_accounting"]["quota_consuming_calls"] == 0
    assert summary["claims"]["superiority_claim"].startswith("not established")


def test_summary_records_the_evaluator_that_judged_the_rows(module):
    """Rounds can share one manifest hash while the evaluator changes."""
    summary = module.summarize([], frozen_at="t", manifest_sha="sha",
                               reference={"version": "1.6.0"},
                               conditions={"auth_consent": False})
    evaluator = summary["evaluator"]
    assert evaluator["sha256"] == module.hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest()
    assert evaluator["script"] == "scripts/evaluate_action_artifacts.py"
    # The identity lives outside the frozen manifest, whose digest must not move.
    assert "evaluator" not in summary["manifest"]
    assert module.manifest_digest(module.build_manifest(limit=2)) == module.manifest_digest(
        module.build_manifest(limit=2))


def test_scrub_removes_absolute_paths(module):
    cleaned = module._scrub("failed at /srv/minio/x/y and <home>/.agent-reach")
    assert "/srv/" not in cleaned and "/home/" not in cleaned
    assert "<path>" in cleaned


def test_published_evidence_is_consistent_and_honest(module, manifest):
    assert EVIDENCE.exists(), "run scripts/evaluate_action_artifacts.py to produce evidence"
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["schema"] == module.SCHEMA

    assert evidence["manifest"]["rows"] == 40
    assert evidence["manifest"]["frozen_before_calls"] is True
    assert evidence["manifest"]["sha256"] == module.manifest_digest(manifest)
    assert evidence["reference"]["version"].startswith("1.6.")
    assert evidence["reference"]["commit"] == "14c213405669414492bda0f8d52cc6531d062c45"
    assert evidence["reference"]["pinned_commit_recorded"] is True
    assert evidence["reference"]["registry_actions"] == 40

    rows = evidence["rows"]
    assert len(rows) == 40
    assert {r["channel"] for r in rows}.__len__() == 14
    assert len({(r["channel"], r["action"]) for r in rows}) == 40

    ledger = evidence["ledger"]
    assert ledger["actions_total"] == len(rows)
    assert ledger["public"] == sum(1 for r in rows if r["gate"] == "public") == 26
    assert ledger["consent"] == 12 and ledger["quota"] == 2
    assert ledger["gated_not_run"] == 14
    assert ledger["executed_public"] == 26
    assert ledger["inspected"] + ledger["failed"] + ledger["deadline_exhausted"] == 26

    artifacts = evidence["artifact_summary"]
    for key, value in artifacts["verdicts"].items():
        assert value == sum(1 for r in rows if r["verdict"] == key)
    assert artifacts["whole_artifact_proven"] == 0
    assert all(r["completeness"]["whole_artifact_proven"] in (False, None) for r in rows)

    # Gated rows were refused without an action process and are not failures.
    for row in rows:
        if row["gate"] != "public":
            assert row["status"] == "gated_not_run"
            assert row["verdict"] == "not_run"
            assert row["error"]["code"] in {"auth_required", "asr_disabled"}
            assert row["gate_probe"]["spawned_action_process"] is False
            assert row["gate_probe"]["runner_calls"] == 0

    # Every inspected artifact carries evaluated units, an artifact digest and
    # explicit known/unknown completeness.
    for row in rows:
        assert row["requested_outcome"] and row["units"]
        if row["status"] == "inspected":
            assert any(u["status"] == "present" for u in row["units"])
            assert row["artifact"]["items"] >= 1
            assert row["completeness"]["known"] and row["completeness"]["unknown"]
            assert "caps" in row["completeness"]

    # Errors are preserved, not converted into absences.
    failed = [r for r in rows if r["status"] == "failed"]
    assert failed, "this campaign recorded upstream failures; they must be visible"
    for row in failed:
        assert row["error"]["code"]
        assert all(u["status"] == "unverified" for u in row["units"])

    # No credential/account attempt and no host path in the published record.
    accounting = evidence["attempt_accounting"]
    assert accounting["authenticated_calls"] == 0
    assert accounting["quota_consuming_calls"] == 0
    assert accounting["asr_calls"] == 0
    assert evidence["conditions"]["auth_consent"] is False
    assert evidence["conditions"]["asr_disabled"] is True

    published = EVIDENCE.read_text()
    for needle in ("/srv/", "/home/", "/tmp/", "sk-", "Bearer "):
        assert needle not in published, f"{needle!r} leaked into published evidence"
