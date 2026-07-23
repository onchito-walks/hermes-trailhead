import subprocess
from pathlib import Path

import hermes_trailhead.extract as extract_mod


def test_browser_harness_invokes_repo_local_adapter(monkeypatch):
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, "TITLE: Example\nVisible page text", "")

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)
    result = extract_mod._fetch_browser_harness("https://example.test/page", timeout=7)
    adapter = Path(extract_mod.__file__).resolve().parent.parent / "scripts" / "browser-harness.js"
    assert result.startswith("TITLE: Example")
    assert calls["command"] == ["node", str(adapter)]
    assert 'goto_url("https://example.test/page")' in calls["input"]
    assert "range(1, 8)" in calls["input"]


def test_browser_harness_adapter_is_valid_node_source():
    adapter = Path(__file__).parents[1] / "scripts" / "browser-harness.js"
    result = subprocess.run(["node", "--check", str(adapter)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
