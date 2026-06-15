import json
import tempfile
from pathlib import Path

from hermes_trailhead.router import (
    Route,
    ROUTE_CHANNEL_DEPENDENCIES,
    score_route_with_live_state,
    route_for_with_live,
)
from hermes_trailhead.reliability import (
    ReliabilityRecord,
    record_check,
    record_all_checks,
    reliability_summary,
    DEFAULT_STATE_PATH,
)
from hermes_trailhead.channels import Channel, CheckResult


# ── Live route scoring tests ──────────────────────────────────────────────


def test_route_channel_dependencies_exist_for_all_routes():
    from hermes_trailhead.router import ROUTES
    for route in ROUTES:
        assert route.key in ROUTE_CHANNEL_DEPENDENCIES, f"Missing dependencies for {route.key}"


def test_score_healthy_route():
    route = Route(
        key="social-current-signal", task="", primary="", fallbacks=(), avoid=(),
        approval_required=True, rationale="", evidence_needed=(), competitor_lesson="",
    )
    channel_results = {"x-search": "ok", "reddit": "ok", "tiktok": "off", "instagram": "off", "youtube": "warn"}
    scored = score_route_with_live_state(route, channel_results)
    assert scored.health_score == 50  # worst is 'off' (tiktok)
    assert any("tiktok" in w for w in scored.live_warnings)


def test_score_all_healthy():
    route = Route(
        key="discovery-search", task="", primary="", fallbacks=(), avoid=(),
        approval_required=False, rationale="", evidence_needed=(), competitor_lesson="",
    )
    results = {"web-search": "ok", "web-extract": "ok", "x-search": "ok", "reddit": "ok", "github": "ok"}
    scored = score_route_with_live_state(route, results)
    assert scored.health_score == 100
    assert len(scored.live_warnings) == 0


def test_score_all_broken_drops_to_10():
    route = Route(
        key="social-current-signal", task="", primary="", fallbacks=(), avoid=(),
        approval_required=True, rationale="", evidence_needed=(), competitor_lesson="",
    )
    results = {"x-search": "fail", "reddit": "off", "tiktok": "off", "instagram": "off", "youtube": "fail"}
    scored = score_route_with_live_state(route, results)
    assert scored.health_score == 10


def test_score_no_deps_returns_unchanged():
    """Routes with no channel dependencies keep health_score=100."""
    route = Route(
        key="no-deps", task="", primary="", fallbacks=(), avoid=(),
        approval_required=False, rationale="", evidence_needed=(), competitor_lesson="",
    )
    scored = score_route_with_live_state(route, {})
    assert scored.health_score == 100


def test_route_for_with_live_includes_health():
    channel_results = {"web-search": "ok", "web-extract": "ok", "x-search": "ok", "reddit": "ok", "github": "ok", "jina-reader": "ok"}
    route = route_for_with_live("read this url as markdown", channel_results)
    assert route.key == "known-url-read"
    assert route.health_score == 100


# ── Reliability tracker tests ─────────────────────────────────────────────


def test_record_check_creates_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        record_check("github", "ok", "All good", path=p)
        assert p.exists()
        data = json.loads(p.read_text())
        assert len(data["records"]) == 1
        assert data["records"][0]["channel"] == "github"


def test_record_all_checks_from_doctor():
    from hermes_trailhead.channels import Channel, CheckResult, PolicyEvidence

    ch = Channel(
        key="test-chan", title="Test", purpose="testing", default_path="",
        risk="low", check=lambda: CheckResult(status="ok", detail="works", evidence=()),
        setup_plan=(), required=False, approval_required=False,
    )
    res = ch.check()

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        count = record_all_checks([(ch, res)], path=p)
        assert count == 1
        data = json.loads(p.read_text())
        assert data["records"][0]["status"] == "ok"


def test_reliability_summary_empty():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        summary = reliability_summary(path=p)
        assert summary["total_records"] == 0
        assert summary["channels"] == {}


def test_reliability_summary_with_data():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        for i in range(10):
            status = "ok" if i % 2 == 0 else "warn"
            record_check("github", status, f"Check {i}", path=p)

        summary = reliability_summary(path=p, lookback_days=365)
        assert summary["total_records"] == 10
        assert "github" in summary["channels"]
        ch = summary["channels"]["github"]
        assert ch["success_rate"] == 50  # 5 ok out of 10
        assert ch["trend"] in ("stable", "declining", "improving")
        assert ch["check_count"] == 10


def test_reliability_trend_detection():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        # First half: mostly failures
        for i in range(5):
            record_check("reddit", "fail", "Down", path=p)
        # Second half: mostly successes
        for i in range(5):
            record_check("reddit", "ok", "Up", path=p)

        summary = reliability_summary(path=p, lookback_days=365)
        assert summary["channels"]["reddit"]["trend"] == "improving"


def test_record_check_truncates_detail():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test-reliability.json"
        long_detail = "x" * 1000
        record_check("test", "ok", long_detail, path=p)
        data = json.loads(p.read_text())
        assert len(data["records"][0]["detail"]) <= 500
