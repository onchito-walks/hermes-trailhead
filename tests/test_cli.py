from source_scout.cli import main


def test_doctor_json_contract(capsys):
    rc = main(["doctor", "--format", "json"])
    out = capsys.readouterr().out
    assert '"summary"' in out
    assert '"channels"' in out
    assert '"key": "web-search"' in out
    assert '"evidence"' in out
    assert rc in (0, 1, 2)


def test_queue_json_contract(capsys):
    rc = main(["queue", "--format", "json", "--all"])
    out = capsys.readouterr().out
    assert '"key": "agent-reach"' in out
    assert '"approval_required"' in out
    assert rc == 0


def test_queue_filters(capsys):
    rc = main(["queue", "--risk", "high", "--top", "1"])
    out = capsys.readouterr().out
    assert "risk=high" in out
    assert rc == 0


def test_plan_known_channel(capsys):
    rc = main(["plan", "x-search"])
    out = capsys.readouterr().out
    assert "Setup / usage plan" in out
    assert "Guardrail" in out
    assert rc == 0


def test_capability_radar(capsys):
    rc = main(["capability-radar"])
    out = capsys.readouterr().out
    assert "Hermes Capability Radar" in out
    assert "newsletter" in out.lower()
    assert rc == 0


def test_agent_brief(capsys):
    rc = main(["agent-brief", "--format", "json"])
    out = capsys.readouterr().out
    assert '"use_first"' in out
    assert '"approval_required"' in out
    assert "web_search" in out
    assert rc == 0


def test_routes_command(capsys):
    rc = main(["routes", "--format", "json"])
    out = capsys.readouterr().out
    assert '"routes"' in out
    assert "interactive-browser" in out
    assert rc == 0


def test_route_command(capsys):
    rc = main(["route", "extract schema from website", "--format", "json"])
    out = capsys.readouterr().out
    assert '"key": "structured-extraction"' in out
    assert "Firecrawl" in out
    assert rc == 0
