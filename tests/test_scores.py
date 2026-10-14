"""Tests for the per-lane scorecard (hermes_trailhead.scores)."""
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


def test_lane_scores_live_annotates_via_probes(monkeypatch):
    monkeypatch.setattr(sc, "_probe_for", lambda lane: f"probe-ok-{lane}")
    payload = sc.lane_scores(live=True)
    for row in payload["lanes"]:
        assert row["live"] == f"probe-ok-{row['lane']}"


def test_lane_scores_without_live_has_no_live_field():
    payload = sc.lane_scores(live=False)
    assert all("live" not in row for row in payload["lanes"])


def test_format_scores_text_renders_all_lanes():
    out = sc.format_scores_text(sc.lane_scores(live=False))
    for lane in ("youtube", "github", "web", "reddit", "x", "tiktok", "instagram"):
        assert lane in out
    assert "verified live" in out


def test_scores_json_serializable(monkeypatch):
    monkeypatch.setattr(sc, "_probe_for", lambda lane: "http 200")
    payload = sc.lane_scores(live=True)
    # probes mocked — payload must always serialize
    json.dumps(payload)
