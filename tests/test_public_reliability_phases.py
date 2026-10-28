"""Contract tests for the resumable P2 cold/warm phases (no network).

What is pinned here:

* the phase gate runs **before** any measured call, and refuses a premature
  warm round, a cold rerun, a warm rerun, a manifest/tool mismatch and a
  symlinked or partial state tree;
* the warm phase reuses the *same* sandbox homes the cold phase built, and a
  cold phase produces exactly one observation per case/tool (3 × 2 = 6);
* the published phase record can never read as a 5-day reliability result:
  coverage lists the observed calendar days and every remaining day as a gap.

Every measurement here runs local child processes only (``python -c print(...)``
standing in for each tool), so nothing in this module touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "evaluate_public_resources.py"

T0 = datetime(2026, 10, 28, 16, 30, tzinfo=timezone.utc)
FINGERPRINT = {
    "trailhead_commit": "a" * 40,
    "trailhead_python": "3.14.9",
    "agent_reach_version": "0.7.0",
    "agent_reach_pinned_commit": "b" * 40,
    "agent_reach_executable_sha256": "c" * 64,
}
TH_STDOUT = json.dumps({
    "ok": True, "url": "https://example.org/p",
    "content": "Support for type hints Protocol", "truncated": False,
    "pagination": {"more": False, "next_offset": None}, "returned_chars": 33,
})
AR_STDOUT = json.dumps({
    "ok": True, "backend": "local",
    "items": [{"text": "local payload", "url": "https://example.org/p"}],
})


def _load():
    spec = importlib.util.spec_from_file_location("evaluate_public_resources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load()


class FakeClock:
    """Injected wall clock: the warm gate is tested without sleeping 30 min."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(MODULE, "_CLOCK", fake)
    return fake


def _fake_manifest(cases: int = 3) -> dict:
    """A frozen-shaped manifest whose 'tools' are local, network-free children."""
    rows = []
    for index in range(cases):
        rows.append({
            "case_id": f"fake-case-{index}",
            "lane": "public",
            "requested_outcome": "a synthetic local payload",
            "tool_argv": {
                "trailhead": ["python", "-c",
                              "import json,sys;sys.stdout.write(json.loads(sys.argv[1]))",
                              TH_STDOUT],
                "agent_reach": ["<agent-reach>", "-c",
                                "import json,sys;sys.stdout.write(json.loads(sys.argv[1]))",
                                AR_STDOUT],
            },
            "artifact_units": [{
                "id": "identity", "kind": "text_any_of",
                "values": ["Support for type hints"], "required": True,
                "whole_artifact": True,
            }],
            "pagination_expectation": {"whole_artifact": True, "continuation": "none"},
        })
    manifest = {
        "schema": MODULE.MANIFEST_SCHEMA, "frozen_at": "2026-10-28T00:00:00Z",
        "frozen_by": "test fixture", "cases": rows,
    }
    manifest["manifest_sha256"] = MODULE.manifest_hash(manifest)
    return manifest


def _cold_session(manifest: dict, *, observations: list[dict] | None = None,
                  ended_at: datetime = T0,
                  fingerprint: dict | None = None) -> dict:
    return {
        "schema": MODULE.STATE_SCHEMA,
        "session": "p2-test",
        "window": MODULE.build_window("2026-10-28", "16:00", "18:00",
                                      MODULE.iso(T0), "cli"),
        "manifest": {"manifest_sha256": manifest["manifest_sha256"], "cases": 3},
        "tools_fingerprint": fingerprint or dict(FINGERPRINT),
        "phases": {
            "cold": {
                "phase": "cold", "started_at": MODULE.iso(T0 - timedelta(minutes=2)),
                "ended_at": MODULE.iso(ended_at), "late": False,
                "planned": 6, "recorded": len(observations or []),
                "observations": observations if observations is not None else [
                    {"case_id": f"fake-case-{i}", "tool": tool,
                     "home": f"homes/fake-case-{i}/{tool}"}
                    for i in range(3) for tool in MODULE.TOOLS
                ],
            },
        },
    }


def _write_session(state_dir: Path, session: str, state: dict) -> None:
    MODULE.save_session(state, state_dir, session)


def _homes(state_dir: Path, session: str) -> Path:
    return state_dir / session / "homes"


def _make_homes(state_dir: Path, session: str, manifest: dict) -> None:
    for case in manifest["cases"]:
        for tool in MODULE.TOOLS:
            tool_home = _homes(state_dir, session) / case["case_id"] / tool
            for child in ("home", "agent-reach-home", "tmp"):
                (tool_home / child).mkdir(parents=True, exist_ok=True)


def _gate(state_dir, session, manifest, *, phase="warm", clock=None,
          fingerprint=None):
    return MODULE.check_phase_gate(
        phase=phase, state_dir=state_dir, session=session, manifest=manifest,
        fingerprint=fingerprint or dict(FINGERPRINT),
        now=(clock.now if clock else T0))


# ── gates run before any call ───────────────────────────────────────────────

def test_warm_before_thirty_minutes_is_refused(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)

    clock.advance(minutes=29)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "premature warm" in reason
    assert "no call was made" in reason

    clock.advance(minutes=1)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is True, reason


def test_warm_after_exactly_thirty_minutes_is_allowed(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)
    clock.advance(minutes=30)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is True, reason


def test_cold_rerun_is_refused_not_merged(tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    ok, reason, _ = MODULE.check_phase_gate(
        phase="cold", state_dir=state_dir, session="p2-test",
        manifest=manifest, fingerprint=FINGERPRINT)
    assert ok is False
    assert "already recorded" in reason


def test_cold_refuses_a_session_dir_left_by_a_partial_run(tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    (_homes(state_dir, "p2-test") / "fake-case-0" / "trailhead" / "home").mkdir(parents=True)
    ok, reason, _ = MODULE.check_phase_gate(
        phase="cold", state_dir=state_dir, session="p2-test",
        manifest=manifest, fingerprint=FINGERPRINT)
    assert ok is False
    assert "partial cold" in reason


def test_warm_without_cold_state_is_refused(tmp_path):
    ok, reason, _ = MODULE.check_phase_gate(
        phase="warm", state_dir=tmp_path / "state", session="p2-test",
        manifest=_fake_manifest(), fingerprint=FINGERPRINT)
    assert ok is False
    assert "run the cold phase first" in reason


def test_warm_refuses_a_partial_cold_instead_of_topping_it_up(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    partial = [{"case_id": "fake-case-0", "tool": "trailhead",
                "home": "homes/fake-case-0/trailhead"}]
    _write_session(state_dir, "p2-test", _cold_session(manifest, observations=partial))
    clock.advance(minutes=31)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "1 of 6" in reason
    assert "not completed by a rerun" in reason


def test_warm_refuses_a_second_warm(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    state = _cold_session(manifest)
    state["phases"]["warm"] = {"phase": "warm", "observations": [{}] * 6}
    _write_session(state_dir, "p2-test", state)
    _make_homes(state_dir, "p2-test", manifest)
    clock.advance(minutes=31)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "refusing to overwrite" in reason


def test_warm_refuses_a_different_manifest_hash(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    state = _cold_session(manifest)
    state["manifest"]["manifest_sha256"] = "0" * 64
    _write_session(state_dir, "p2-test", state)
    _make_homes(state_dir, "p2-test", manifest)
    clock.advance(minutes=31)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "manifest hash differs" in reason


def test_warm_refuses_a_changed_tool_version(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)
    clock.advance(minutes=31)
    changed = {**FINGERPRINT, "agent_reach_version": "0.8.0"}
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock,
                          fingerprint=changed)
    assert ok is False
    assert "agent_reach_version" in reason


def test_warm_refuses_a_missing_or_incomplete_home(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)
    shutil.rmtree(_homes(state_dir, "p2-test") / "fake-case-1" / "agent_reach")
    clock.advance(minutes=31)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "missing" in reason or "not a directory" in reason


def test_symlinked_state_path_is_refused(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "p2-test").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(SystemExit):
        MODULE._assert_safe_state_path(root / "p2-test", root)


def test_symlinked_home_inside_state_is_refused(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)
    tool_home = _homes(state_dir, "p2-test") / "fake-case-2" / "trailhead"
    outside = tmp_path / "outside-home"
    outside.mkdir()
    for child in ("home", "agent-reach-home", "tmp"):
        (tool_home / child).rename(outside / child)
    for child in ("home", "agent-reach-home", "tmp"):
        (tool_home / child).symlink_to(outside / child, target_is_directory=True)
    clock.advance(minutes=31)
    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "symlink" in reason


def test_symlinked_state_root_is_refused(clock, tmp_path):
    manifest = _fake_manifest()
    real = tmp_path / "real-state"
    _write_session(real, "p2-test", _cold_session(manifest))
    _make_homes(real, "p2-test", manifest)
    linked = tmp_path / "linked-state"
    linked.symlink_to(real, target_is_directory=True)
    clock.advance(minutes=31)
    ok, reason, _ = _gate(linked, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "symlink" in reason


def test_symlinked_session_file_is_refused_before_it_is_read(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test", _cold_session(manifest))
    _make_homes(state_dir, "p2-test", manifest)
    session_json = state_dir / "p2-test" / "session.json"
    stolen = tmp_path / "stolen.json"
    session_json.rename(stolen)
    session_json.symlink_to(stolen)
    clock.advance(minutes=31)

    with pytest.raises(SystemExit) as excinfo:
        MODULE.load_session(session_json)
    assert "symlink" in str(excinfo.value)

    ok, reason, _ = _gate(state_dir, "p2-test", manifest, clock=clock)
    assert ok is False
    assert "symlink" in reason

    with pytest.raises(SystemExit):
        MODULE.save_session({}, state_dir, "p2-test")


def test_unsafe_session_names_are_refused_before_any_path_is_built(tmp_path):
    for name in ("../escape", "a/b", "/absolute", "..", ".", "", "a b",
                 "p2/../p2", "-leading-dash"):
        assert MODULE.valid_session_name(name) is False, name
    assert MODULE.valid_session_name("p2-2026-10-28") is True
    assert MODULE.valid_session_name("p2_2026.10.28") is True

    ok, reason, _ = MODULE.check_phase_gate(
        phase="cold", state_dir=tmp_path / "state", session="../escape",
        manifest=_fake_manifest(), fingerprint=FINGERPRINT)
    assert ok is False
    assert "unsafe session name" in reason
    assert (tmp_path / "escape").exists() is False

    args = SimpleNamespace(
        session="../../escape", state_dir=str(tmp_path / "state"),
        show_next=True, agent_reach=None, out=None, timeout=25.0,
    )
    assert MODULE._run_phase_cli(args, _fake_manifest(),
                                 tmp_path / "manifest.json") == 2


# ── a docs-only HEAD move must not block the warm round ─────────────────────

OLD = "1" * 40
NEW = "2" * 40
OLD_TREE = {"hermes_trailhead": "a" * 40, "pyproject.toml": "b" * 40}
NEW_DOCS_ONLY = dict(OLD_TREE)
NEW_PRODUCT = {**OLD_TREE, "hermes_trailhead": "c" * 40}


def _mock_tree_lookup(monkeypatch, recorded_tree: dict, current_tree: dict) -> list:
    """Stand-in for git: no repository, no subprocess, explicit per-commit ids."""
    calls: list[tuple[str, str]] = []

    def lookup(commit, path, repo=None):
        calls.append((commit, path))
        if commit == OLD:
            return recorded_tree.get(path, "")
        if commit == NEW:
            return current_tree.get(path, "")
        return ""

    monkeypatch.setattr(MODULE, "git_object_id", lookup)
    return calls


def _gate_with_commit(state_dir, session, manifest, clock, commit,
                      fingerprint_extra=None):
    fingerprint = {**FINGERPRINT, "trailhead_commit": commit,
                   **(fingerprint_extra or {})}
    return MODULE.check_phase_gate(
        phase="warm", state_dir=state_dir, session=session, manifest=manifest,
        fingerprint=fingerprint, now=clock.now)


def test_docs_only_commit_move_allows_warm_and_records_both_commits(
        clock, tmp_path, monkeypatch):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test",
                   _cold_session(manifest,
                                 fingerprint={**FINGERPRINT,
                                              "trailhead_commit": OLD}))
    _make_homes(state_dir, "p2-test", manifest)
    calls = _mock_tree_lookup(monkeypatch, OLD_TREE, NEW_DOCS_ONLY)
    clock.advance(minutes=31)

    ok, reason, state = _gate_with_commit(state_dir, "p2-test", manifest,
                                         clock, NEW)
    assert ok is True, reason
    assert ("/srv" not in reason)
    decision = state["compatibility"]
    assert decision["equivalent"] is True
    assert decision["recorded_commit"] == OLD
    assert decision["current_commit"] == NEW
    assert decision["objects"]["hermes_trailhead"] == {
        "recorded": OLD_TREE["hermes_trailhead"],
        "current": NEW_DOCS_ONLY["hermes_trailhead"],
    }
    assert decision["objects"]["pyproject.toml"] == {
        "recorded": OLD_TREE["pyproject.toml"],
        "current": NEW_DOCS_ONLY["pyproject.toml"],
    }
    assert "identical" in decision["reason"]
    # Every product path was compared at both commits.
    assert {path for _, path in calls} == set(MODULE.PRODUCT_PATHS)


def test_product_change_still_blocks_warm(clock, tmp_path, monkeypatch):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test",
                   _cold_session(manifest,
                                 fingerprint={**FINGERPRINT,
                                              "trailhead_commit": OLD}))
    _make_homes(state_dir, "p2-test", manifest)
    _mock_tree_lookup(monkeypatch, OLD_TREE, NEW_PRODUCT)
    clock.advance(minutes=31)

    ok, reason, _ = _gate_with_commit(state_dir, "p2-test", manifest, clock, NEW)
    assert ok is False
    assert "product source changed" in reason
    assert OLD[:12] in reason and NEW[:12] in reason
    assert "hermes_trailhead" in reason


def test_unknown_or_unavailable_commit_ref_is_refused(clock, tmp_path, monkeypatch):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test",
                   _cold_session(manifest,
                                 fingerprint={**FINGERPRINT,
                                              "trailhead_commit": OLD}))
    _make_homes(state_dir, "p2-test", manifest)
    clock.advance(minutes=31)

    # Recorded commit object missing from this repository.
    _mock_tree_lookup(monkeypatch, {}, NEW_DOCS_ONLY)
    ok, reason, _ = _gate_with_commit(state_dir, "p2-test", manifest, clock, NEW)
    assert ok is False
    assert "unavailable" in reason and "refusal" in reason

    # Current commit unreadable (e.g. git missing, malformed ref).
    _mock_tree_lookup(monkeypatch, OLD_TREE, {})
    ok, reason, _ = _gate_with_commit(state_dir, "p2-test", manifest, clock, NEW)
    assert ok is False
    assert "unavailable" in reason

    # A non-hex "commit" never reaches git at all.
    ok, reason, _ = _gate_with_commit(state_dir, "p2-test", manifest, clock,
                                      "not-a-sha refs/heads/main")
    assert ok is False
    assert "unavailable" in reason


def test_git_object_id_rejects_malformed_refs_without_calling_git(monkeypatch):
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("git must not be reached for a malformed ref")

    monkeypatch.setattr(MODULE.subprocess, "run", boom)
    assert MODULE.git_object_id("../etc", "hermes_trailhead") == ""
    assert MODULE.git_object_id("refs/heads/main", "hermes_trailhead") == ""
    assert MODULE.git_object_id("", "hermes_trailhead") == ""
    assert calls == []


def test_other_tool_fields_still_block_a_commit_compatible_warm(
        clock, tmp_path, monkeypatch):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test",
                   _cold_session(manifest,
                                 fingerprint={**FINGERPRINT,
                                              "trailhead_commit": OLD}))
    _make_homes(state_dir, "p2-test", manifest)
    _mock_tree_lookup(monkeypatch, OLD_TREE, NEW_DOCS_ONLY)
    clock.advance(minutes=31)
    ok, reason, _ = _gate_with_commit(state_dir, "p2-test", manifest, clock, NEW,
                                      {"agent_reach_executable_sha256": "d" * 64})
    assert ok is False
    assert "agent_reach_executable_sha256" in reason


# ── end-to-end: 6 cold calls, then the same homes warm ─────────────────────

def test_cold_phase_records_six_rows_and_warm_reuses_the_same_homes(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    session = "p2-test"

    ok, reason, _ = MODULE.check_phase_gate(
        phase="cold", state_dir=state_dir, session=session,
        manifest=manifest, fingerprint=FINGERPRINT)
    assert ok, reason
    state = {
        "schema": MODULE.STATE_SCHEMA, "session": session,
        "window": MODULE.build_window("2026-10-28", "16:00", "18:00",
                                      MODULE.iso(clock.now), "cli"),
        "manifest": {"manifest_sha256": manifest["manifest_sha256"], "cases": 3},
        "tools_fingerprint": dict(FINGERPRINT),
        "phases": {},
    }
    persist = lambda current: MODULE.save_session(current, state_dir, session)
    cold = MODULE.run_phase(
        manifest, phase="cold", session_state=state, agent_reach=sys.executable,
        state_dir=state_dir, session=session, timeout_s=30.0,
        max_raw_bytes=1 << 20, persist=persist)

    assert len(cold["observations"]) == 6
    pairs = [(row["case_id"], row["tool"]) for row in cold["observations"]]
    assert len(set(pairs)) == 6, "one observation per case/tool, no duplicates"
    assert {row["tool"] for row in cold["observations"]} == set(MODULE.TOOLS)
    assert all(row["state"] == "cold" and row["sandbox_reused"] is False
               for row in cold["observations"])
    assert cold["ended_at"] and cold["warm_earliest_at"]
    assert MODULE.parse_iso(cold["warm_earliest_at"]) == (
        MODULE.parse_iso(cold["ended_at"]) + timedelta(minutes=30))
    cold_homes = {row["home"] for row in cold["observations"]}
    assert cold_homes == {f"homes/fake-case-{i}/{tool}"
                          for i in range(3) for tool in MODULE.TOOLS}
    for home in cold_homes:
        assert (state_dir / session / home / "home").is_dir(), home

    # Premature: refused before any call, state untouched.
    clock.advance(minutes=10)
    ok, reason, _ = _gate(state_dir, session, manifest, clock=clock)
    assert not ok and "premature warm" in reason
    assert (state_dir / session / "raw" / "warm").exists() is False

    clock.advance(minutes=21)
    ok, reason, loaded = _gate(state_dir, session, manifest, clock=clock)
    assert ok, reason
    warm = MODULE.run_phase(
        manifest, phase="warm", session_state=loaded, agent_reach=sys.executable,
        state_dir=state_dir, session=session, timeout_s=30.0,
        max_raw_bytes=1 << 20, persist=persist)

    assert len(warm["observations"]) == 6
    assert {row["home"] for row in warm["observations"]} == cold_homes
    assert all(row["sandbox_reused"] is True for row in warm["observations"])
    # Same homes really are the same directories the cold run created.
    for home in cold_homes:
        assert (state_dir / session / home / "home").is_dir()

    saved = json.loads((state_dir / session / "session.json").read_text())
    assert set(saved["phases"]) == {"cold", "warm"}
    assert len(saved["phases"]["warm"]["observations"]) == 6


def test_phase_evidence_cannot_read_as_a_five_day_campaign(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    session = "p2-test"
    state = _cold_session(manifest)
    record = state["phases"]["cold"]
    record["observations"] = [
        {"case_id": f"fake-case-{i}", "tool": tool, "state": "cold",
         "phase": "cold", "home": f"homes/fake-case-{i}/{tool}",
         "status": "ok", "verdict": "markers_present", "timed_out": False,
         "truncated": False, "required_present": 1, "required_total": 1,
         "required_assessed": 1, "wall_s": 0.5, "cpu_user_s": 0.0,
         "cpu_sys_s": 0.0, "peak_rss_kb": 1000, "stdout_bytes": 10,
         "stderr_bytes": 0, "raw_capped": False}
        for i in range(3) for tool in MODULE.TOOLS
    ]
    args = SimpleNamespace(timeout=25.0)
    evidence = MODULE.build_phase_evidence(
        session_state=state, phase_record=record, manifest=manifest,
        manifest_path=REPO / "docs" / "evidence" / "public-remaining-manifest.json",
        inventory={"trailhead": {}, "agent_reach": {}}, args=args,
        phase="cold")

    coverage = evidence["coverage"]
    assert coverage["multi_day_complete"] is False
    assert coverage["days_observed"] == ["2026-10-28"]
    assert coverage["days_required"] == ["2026-10-28", "2026-10-29",
                                        "2026-10-30", "2026-10-31", "2026-11-01"]
    assert [gap["utc_date"] for gap in coverage["gaps"]] == [
        "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]
    assert coverage["warm_pending"] is True
    assert "not a multi-day reliability result" in coverage["claim"]
    assert evidence["claims"]["multi_day_reliability"].startswith("none")
    assert evidence["claims"]["winner"].startswith("none")
    assert evidence["totals"]["invocations"] == 6
    # The record must not contain absolute host paths.
    text = json.dumps(evidence)
    assert "/home/" not in text and "/srv/" not in text and str(tmp_path) not in text


def test_window_is_frozen_and_late_runs_are_labelled(clock, tmp_path):
    window = MODULE.build_window("2026-10-28", "16:00", "18:00", MODULE.iso(T0), "cli")
    assert window["start_at"] == "2026-10-28T16:00:00Z"
    assert window["end_at"] == "2026-10-28T18:00:00Z"
    assert MODULE.in_window(T0, window) is True
    assert MODULE.in_window(T0.replace(hour=18, minute=1), window) is False
    with pytest.raises(ValueError):
        MODULE.build_window("2026-10-28", "18:00", "16:00", MODULE.iso(T0))
    with pytest.raises(ValueError):
        MODULE.build_window("2026-10-28", "16:00", "16:00", MODULE.iso(T0))


def test_session_state_survives_a_reload(clock, tmp_path):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    state = _cold_session(manifest)
    MODULE.save_session(state, state_dir, "p2-test")
    reloaded = MODULE.load_session(MODULE.session_file(state_dir, "p2-test"))
    assert reloaded["manifest"]["manifest_sha256"] == manifest["manifest_sha256"]
    assert reloaded["tools_fingerprint"] == FINGERPRINT
    assert MODULE.load_session(tmp_path / "missing.json") is None


# ── a published phase record never reads as multi-day ───────────────────────

def _phase_rows(phase: str) -> list[dict]:
    return [
        {"case_id": f"fake-case-{i}", "tool": tool, "state": phase,
         "phase": phase, "home": f"homes/fake-case-{i}/{tool}",
         "status": "ok", "verdict": "markers_present", "timed_out": False,
         "truncated": False, "required_present": 1, "required_total": 1,
         "required_assessed": 1, "wall_s": 0.5, "cpu_user_s": 0.0,
         "cpu_sys_s": 0.0, "peak_rss_kb": 1000, "stdout_bytes": 10,
         "stderr_bytes": 0, "raw_capped": False}
        for i in range(3) for tool in MODULE.TOOLS
    ]


def _warm_record(started_at: str) -> dict:
    return {"phase": "warm", "started_at": started_at,
            "ended_at": started_at, "late": False, "planned": 6, "recorded": 6,
            "observations": _phase_rows("warm")}


def _evidence_for(state: dict, manifest: dict, phase: str) -> dict:
    return MODULE.build_phase_evidence(
        session_state=state, phase_record=state["phases"][phase],
        manifest=manifest,
        manifest_path=REPO / "docs" / "evidence" / "public-remaining-manifest.json",
        inventory={"trailhead": {}, "agent_reach": {}},
        args=SimpleNamespace(timeout=25.0), phase=phase)


def test_warm_evidence_does_not_report_the_warm_round_as_unmeasured(
        clock, tmp_path):
    manifest = _fake_manifest()
    state = _cold_session(manifest)
    state["phases"]["warm"] = _warm_record(
        MODULE.iso(T0 + timedelta(minutes=31)))
    evidence = _evidence_for(state, manifest, "warm")

    assert evidence["coverage"]["warm_pending"] is False
    assert not [line for line in evidence["not_measured"]
                if "warm round" in line], evidence["not_measured"]
    assert evidence["totals"]["invocations"] == 6
    assert evidence["claims"]["multi_day_reliability"].startswith("none")


def test_cold_evidence_still_reports_the_warm_round_as_unmeasured(
        clock, tmp_path):
    manifest = _fake_manifest()
    state = _cold_session(manifest)
    state["phases"]["cold"]["observations"] = _phase_rows("cold")
    evidence = _evidence_for(state, manifest, "cold")
    assert evidence["coverage"]["warm_pending"] is True
    assert [line for line in evidence["not_measured"] if "warm round" in line]


def test_warm_on_a_later_date_is_late_not_a_second_campaign_day(
        clock, tmp_path):
    manifest = _fake_manifest()
    state = _cold_session(manifest)  # cold round: 2026-10-28
    state["phases"]["warm"] = _warm_record("2026-10-29T16:05:00Z")
    coverage = MODULE.coverage_block(state, state["window"])

    assert coverage["days_observed"] == ["2026-10-28"]
    assert coverage["days_observed_count"] == 1
    assert coverage["campaign_days_observed"] == 1
    assert coverage["days_with_any_round"] == ["2026-10-28", "2026-10-29"]
    assert coverage["warm_days"] == ["2026-10-29"]
    assert coverage["warm_late_days"] == ["2026-10-29"]
    assert coverage["warm_late"] is True
    assert "does not count as a second campaign day" in coverage["warm_late_note"]
    assert coverage["multi_day_complete"] is False
    assert [gap["utc_date"] for gap in coverage["gaps"]] == [
        "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]
    assert "late day-1" in coverage["claim"]

    # The same evidence cannot read as two covered days.
    evidence = _evidence_for(state, manifest, "warm")
    assert evidence["coverage"]["days_observed_count"] == 1
    assert evidence["claims"]["multi_day_reliability"].startswith("none")


def test_docs_only_commit_decision_is_carried_into_the_evidence(
        clock, tmp_path, monkeypatch):
    manifest = _fake_manifest()
    state_dir = tmp_path / "state"
    _write_session(state_dir, "p2-test",
                   _cold_session(manifest,
                                 fingerprint={**FINGERPRINT,
                                              "trailhead_commit": OLD}))
    _make_homes(state_dir, "p2-test", manifest)
    _mock_tree_lookup(monkeypatch, OLD_TREE, NEW_DOCS_ONLY)
    clock.advance(minutes=31)
    ok, reason, state = _gate_with_commit(state_dir, "p2-test", manifest,
                                          clock, NEW)
    assert ok, reason
    state["phases"]["warm"] = _warm_record(
        MODULE.iso(T0 + timedelta(minutes=31)))
    evidence = _evidence_for(state, manifest, "warm")

    assert evidence["compatibility"]["recorded_commit"] == OLD
    assert evidence["compatibility"]["current_commit"] == NEW
    assert evidence["compatibility"]["equivalent"] is True
    assert evidence["tools_fingerprint"]["trailhead_commit"] == OLD
