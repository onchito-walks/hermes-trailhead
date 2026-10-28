"""Tests for the per-lane scorecard (hermes_trailhead.scores).

The core contract under test: static grades stay static.  ``--live`` may add
measured probes, but it must never present them as re-derived grades, and a
transcript cache count must never be reported as a transcript success.
"""
from __future__ import annotations

import json

from hermes_trailhead import scores as sc


def test_lane_scores_has_all_seven_lanes():
    payload = sc.lane_scores(live=False)
    lanes = {row["lane"] for row in payload["lanes"]}
    assert lanes == {"youtube", "github", "web", "reddit", "x", "tiktok", "instagram"}
    assert all(row["grade"] for row in payload["lanes"])
    assert all(row["what"] for row in payload["lanes"])
    assert payload["verified"]


def test_every_grade_is_marked_as_a_static_snapshot():
    payload = sc.lane_scores(live=False)
    assert payload["grade_source"] == sc.GRADE_SOURCE == "static_snapshot"
    assert payload["verified"] == sc.VERIFIED
    assert payload["grade_snapshot"]["date"] == sc.VERIFIED
    assert payload["grade_snapshot"]["measured_by_live"] is False
    assert payload["grades_measured"] is False
    assert all(row["grade_source"] == "static_snapshot" for row in payload["lanes"])
    assert all(row["verified"] == sc.VERIFIED for row in payload["lanes"])
    assert all(row["grade_source"] == "static_snapshot" for row in payload["dimensions"])


def test_live_probes_never_flip_grades_into_measurements(monkeypatch):
    monkeypatch.setattr(
        sc, "_probe_for", lambda lane: sc._probe_payload(lane, "fake", "http 200", True)
    )
    payload = sc.lane_scores(live=True)
    assert payload["grades_measured"] is False
    assert payload["grade_source"] == "static_snapshot"
    assert payload["grade_snapshot"]["measured_by_live"] is False
    assert payload["probes_run_at"]
    assert len(payload["measured_probes"]) == len(sc.LANE_SCORES)
    for row in payload["lanes"]:
        # Backwards-compatible short string, plus the structured probe.
        assert row["live"] == "http 200"
        assert row["live_probe"]["counts_as_evidence"] is True
        assert row["grade"] == next(s["grade"] for s in sc.LANE_SCORES if s["lane"] == row["lane"])


def test_without_live_there_are_no_probes():
    payload = sc.lane_scores(live=False)
    assert payload["measured_probes"] == []
    assert payload["probes_run_at"] is None
    assert all("live" not in row for row in payload["lanes"])
    assert any("no live probes" in note.lower() for note in payload["limitations"]) or any(
        "static claims" in note.lower() for note in payload["limitations"]
    )


def test_youtube_cache_count_is_not_a_transcript_success(monkeypatch):
    monkeypatch.setattr(sc, "_transcript_cache_count", lambda: 12)
    monkeypatch.setattr(sc, "_probe", lambda url, timeout=8, headers=None: "http 200")
    probe = sc._probe_for("youtube")
    assert probe["details"]["cached_transcripts"] == 12
    assert probe["details"]["cached_transcripts_counts_as_success"] is False
    assert "not counted as a fresh transcript success" in probe["note"].lower()
    assert probe["counts_as_evidence"] is True  # metadata endpoint answered
    assert "cache" not in probe["result"].lower()


def test_youtube_cache_alone_cannot_count_when_metadata_fails(monkeypatch):
    monkeypatch.setattr(sc, "_transcript_cache_count", lambda: 99)
    monkeypatch.setattr(
        sc, "_probe", lambda url, timeout=8, headers=None: "unreachable (URLError)"
    )
    probe = sc._probe_for("youtube")
    assert probe["counts_as_evidence"] is False
    assert probe["details"]["cached_transcripts"] == 99


def test_instagram_without_session_is_reported_unmeasured(monkeypatch):
    monkeypatch.delenv("TRAILHEAD_CAMOFOX_USER", raising=False)
    probe = sc._probe_for("instagram")
    assert probe["counts_as_evidence"] is False
    assert "not measured" in probe["note"].lower()
    assert "unset" in probe["result"]


def test_format_scores_text_separates_static_from_measured(monkeypatch):
    monkeypatch.setattr(
        sc, "_probe_for", lambda lane: sc._probe_payload(lane, "fake", "http 200", True)
    )
    out = sc.format_scores_text(sc.lane_scores(live=True))
    assert "Static claims snapshot" in out
    assert "historical" in out
    assert "Measured probes" in out
    assert "verified live" not in out
    assert out.index("Static claims snapshot") < out.index("Measured probes")
    for lane in ("youtube", "github", "web", "reddit", "x", "tiktok", "instagram"):
        assert lane in out
    assert "Limitations" in out


def test_format_scores_text_says_no_probes_when_not_live():
    out = sc.format_scores_text(sc.lane_scores(live=False))
    assert "Measured probes: none" in out
    assert "verified live" not in out


def test_format_scores_text_keeps_youtube_cache_honest(monkeypatch):
    monkeypatch.setattr(sc, "_transcript_cache_count", lambda: 7)
    monkeypatch.setattr(sc, "_probe", lambda url, timeout=8, headers=None: "http 200")
    out = sc.format_scores_text(sc.lane_scores(live=True))
    assert "cached transcript files: 7" in out
    assert "not a transcript success" in out


def test_scores_json_serializable(monkeypatch):
    monkeypatch.setattr(
        sc, "_probe_for", lambda lane: sc._probe_payload(lane, "fake", "http 200", True)
    )
    json.dumps(sc.lane_scores(live=True))
    json.dumps(sc.lane_scores(live=False))
