import json

import pytest

from hermes_reach import __version__
from hermes_reach.channels import CHANNELS, Channel, CheckResult, Evidence, check_x_search
from hermes_reach.cli import main
from hermes_reach.router import all_routes, route_for


CHANNEL_KEYS = {
    "key",
    "title",
    "purpose",
    "default_path",
    "risk",
    "required",
    "approval_required",
    "tags",
    "hermes_native",
    "setup_plan",
    "result",
    "status",
    "detail",
    "action",
}

RESULT_KEYS = {
    "status",
    "detail",
    "action",
    "evidence",
    "confidence",
    "approval_required",
    "category",
}

EVIDENCE_KEYS = {"source", "detail", "command", "path", "return_code"}


def _json_from_cli(capsys, argv):
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured


def test_doctor_json_schema_exact(capsys):
    rc, data, _ = _json_from_cli(capsys, ["doctor", "--format", "json"])

    assert rc in (0, 1, 2)
    assert set(data) == {"summary", "channels"}
    assert set(data["summary"]) == {"ok", "warn", "off", "fail"}
    assert data["channels"]

    for channel in data["channels"]:
        assert set(channel) == CHANNEL_KEYS
        assert set(channel["result"]) == RESULT_KEYS
        assert isinstance(channel["tags"], list)
        assert isinstance(channel["setup_plan"], list)
        for evidence in channel["result"]["evidence"]:
            assert set(evidence) == EVIDENCE_KEYS


def test_route_json_schema_exact(capsys):
    rc, data, _ = _json_from_cli(capsys, ["route", "read this known url as markdown", "--format", "json"])

    assert rc == 0
    assert set(data) == {
        "key",
        "task",
        "primary",
        "fallbacks",
        "avoid",
        "approval_required",
        "rationale",
        "evidence_needed",
        "competitor_lesson",
    }
    assert data["key"] == "known-url-read"
    assert isinstance(data["fallbacks"], list)
    assert isinstance(data["avoid"], list)
    assert isinstance(data["evidence_needed"], list)


def test_routes_command_matches_router_constants(capsys):
    rc, data, _ = _json_from_cli(capsys, ["routes", "--format", "json"])

    assert rc == 0
    assert [item["key"] for item in data["routes"]] == [route.key for route in all_routes()]


def test_agent_brief_json_schema_stable(capsys):
    rc, data, _ = _json_from_cli(capsys, ["agent-brief", "--format", "json"])

    assert rc == 0
    assert set(data) == {"use_first", "approval_required", "warnings", "capability_radar"}
    assert "current_facts" in data["use_first"]
    assert "page_or_pdf_extraction" in data["use_first"]
    assert "x-search" in data["approval_required"]
    assert "agent-reach" in data["approval_required"]
    radar_keys = set(data["capability_radar"])
    for key in ["hermes-upstream", "docs-watcher", "newsletter", "x-search", "agent-reach",
                "tiktok", "instagram", "youtube", "reddit", "github", "web-search", "web-extract"]:
        assert key in radar_keys, f"capability_radar missing key: {key}"


def test_plan_unknown_channel_exits_2_and_lists_known_channels(capsys):
    rc = main(["plan", "no-such-channel"])
    captured = capsys.readouterr()

    assert rc == 2
    assert "Unknown channel" in captured.err
    for channel in CHANNELS:
        assert channel.key in captured.err


def test_sensitive_channels_are_approval_required():
    sensitive = {channel.key for channel in CHANNELS if channel.approval_required}

    assert "x-search" in sensitive
    assert "agent-reach" in sensitive


def test_high_risk_plans_print_guardrails(capsys):
    for key in ["x-search", "agent-reach"]:
        rc = main(["plan", key])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Guardrail" in out
        assert "approval" in out.lower()


def test_x_search_does_not_echo_api_key_value(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "super-secret-test-value")

    result = check_x_search()
    rendered = json.dumps(result.to_dict())

    assert result.status == "ok"
    assert "XAI_API_KEY present" in rendered
    assert "super-secret-test-value" not in rendered


def test_cli_outputs_do_not_dump_secret_env_value(monkeypatch, capsys):
    monkeypatch.setenv("XAI_API_KEY", "super-secret-test-value")

    rc = main(["doctor", "--format", "json", "--channel", "x-search"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "XAI_API_KEY" in out
    assert "super-secret-test-value" not in out


def test_route_for_social_signal_requires_approval():
    route = route_for("current social maintainer discussion on x and reddit")

    assert route.key == "social-current-signal"
    assert route.approval_required is True


def test_route_for_unknown_defaults_to_discovery():
    route = route_for("unrecognized research question with no special surface")

    assert route.key == "discovery-search"


def test_browser_login_beats_extraction_when_account_boundary_present():
    route = route_for("login to a website then extract the dashboard data")

    assert route.key == "interactive-browser"
    assert route.approval_required is True


def test_queue_filters_are_intersections(capsys):
    rc, data, _ = _json_from_cli(capsys, ["queue", "--format", "json", "--all", "--risk", "high", "--channel", "x-search"])

    assert rc == 0
    assert [item["key"] for item in data["channels"]] == ["x-search"]
    assert data["channels"][0]["risk"] == "high"


def test_queue_top_limits_after_sorting(capsys):
    rc, data, _ = _json_from_cli(capsys, ["queue", "--format", "json", "--all", "--top", "1"])

    assert rc == 0
    assert len(data["channels"]) == 1


def test_channel_base_dict_shape():
    channel = CHANNELS[0]
    data = channel.base_dict()

    assert set(data) == {
        "key",
        "title",
        "purpose",
        "default_path",
        "risk",
        "required",
        "approval_required",
        "tags",
        "hermes_native",
        "setup_plan",
    }
    assert isinstance(data["tags"], list)
    assert isinstance(data["setup_plan"], list)


def test_checkresult_to_dict_shape():
    result = CheckResult(status="ok", detail="fine", evidence=(Evidence(source="unit", detail="proof"),))
    data = result.to_dict()

    assert set(data) == RESULT_KEYS
    assert set(data["evidence"][0]) == EVIDENCE_KEYS


def test_version_arg_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    out = capsys.readouterr().out

    assert exc.value.code == 0
    assert f"hermes-reach {__version__}" in out


def test_public_readme_does_not_claim_to_be_crawler_or_registry():
    readme = __import__("pathlib").Path("README.md").read_text()

    assert "not:" in readme
    assert "a public MCP registry" in readme
    assert "a crawler" in readme
    assert "BSD 3-Clause" in readme
    assert "Prior art" in readme
