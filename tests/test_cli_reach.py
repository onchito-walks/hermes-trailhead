"""CLI tests for the Agent Reach forwarding surface (reach / reach-call).

These tests exercise cli.py wiring only: capability inventory, argv assembly for
read-only forwarding, explicit auth consent, error passthrough, and the pinned
executable discovery shared with `compare`.  A local fake CLI stands in for
Agent Reach; nothing here installs, logs in to, or contacts it.
"""
from __future__ import annotations

import json
import sys

import pytest

from hermes_trailhead import comparative as cp
from hermes_trailhead.cli import main


REGISTRY = {
    "schema_version": 1,
    "ok": True,
    "channels": [
        {
            "name": "v2ex",
            "description": "forum",
            "level": "default",
            "login": None,
            "actions": [
                {
                    "name": "read",
                    "help": "Read a topic",
                    "params": [
                        {"name": "target", "help": "topic", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["v2ex-api"],
                    "public_web": [],
                },
                {
                    "name": "node",
                    "help": "Latest topics in a node",
                    "params": [
                        {"name": "name", "help": "node", "required": True, "type": "str", "default": None},
                        {"name": "limit", "help": "max", "required": False, "type": "int", "default": None},
                    ],
                    "backends": ["v2ex-api"],
                    "public_web": [],
                },
            ],
        },
        {
            "name": "web",
            "description": "web",
            "level": "default",
            "login": None,
            "actions": [
                {
                    "name": "read",
                    "help": "Read a page",
                    "params": [
                        {"name": "target", "help": "url", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["jina", "exa"],
                    "public_web": ["example.com/"],
                }
            ],
        },
        {
            "name": "instagram",
            "description": "instagram",
            "level": "experimental",
            "login": {"via": "browser", "logged_in": None, "command": "agent-reach login instagram"},
            "actions": [
                {
                    "name": "profile",
                    "help": "A user's profile",
                    "params": [
                        {"name": "username", "help": "user", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["opencli"],
                    "public_web": [],
                }
            ],
        },
        {
            "name": "youtube",
            "description": "youtube",
            "level": "default",
            "login": None,
            "actions": [
                {
                    "name": "read",
                    "help": "video",
                    "params": [
                        {"name": "target", "help": "url", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["yt-dlp"],
                    "public_web": [],
                },
                {
                    "name": "transcribe",
                    "help": "asr",
                    "params": [
                        {"name": "target", "help": "url", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["whisper"],
                    "public_web": [],
                },
            ],
        },
    ],
}


def _fake_cli(tmp_path, *, body: str | None = None):
    script = tmp_path / "agent-reach"
    if body is None:
        body = f"""
import json, sys
argv = sys.argv[1:]
if argv and argv[0] == "channels":
    print(json.dumps({REGISTRY!r}))
    sys.exit(0)
if argv and argv[0] == "version":
    print(json.dumps({{"schema_version": 1, "ok": True, "result": {{"version": "9.9.9"}}, "error": None}}))
    sys.exit(0)
backend = argv[argv.index("--backend") + 1] if "--backend" in argv else "fake-backend"
print(json.dumps({{"schema_version": 1, "ok": True, "channel": argv[0] if argv else None,
                  "action": argv[1] if len(argv) > 1 else None, "backend": backend,
                  "items": [{{"title": "t", "url": "", "author": None, "published_at": None,
                              "text": json.dumps(argv), "raw": None}}],
                  "meta": {{"elapsed_ms": 1, "attempts": []}}, "error": None}}))
"""
    script.write_text(f"#!{sys.executable}\n" + body)
    script.chmod(0o755)
    return str(script)


def _json(capsys):
    out = capsys.readouterr().out
    return json.loads(out)


# ── inventory ────────────────────────────────────────────────────────────────


def test_reach_inventory_json_reports_forwarded_surface(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach", "--agent-reach", exe, "--format", "json"])
    payload = _json(capsys)
    assert rc == 0
    assert payload["found"] is True
    assert payload["engine"] == "agent-reach"
    pairs = {(row["channel"], row["action"]) for row in payload["capabilities"]}
    assert ("v2ex", "read") in pairs
    assert ("web", "read") in pairs
    # transcribe is paid/key-consuming -> never forwarded
    assert ("youtube", "transcribe") not in pairs


def test_reach_inventory_text_marks_auth_gated_actions(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach", "--agent-reach", exe])
    out = capsys.readouterr().out
    assert rc == 0
    assert "public-only" in out
    assert "instagram" in out and "needs --allow-authenticated" in out
    assert "transcribe" in out  # mentioned in the "not forwarded" line


def test_reach_inventory_reports_missing_cli_honestly(tmp_path, capsys):
    rc = main(["reach", "--agent-reach", str(tmp_path / "nope"), "--format", "json"])
    payload = _json(capsys)
    assert rc == 0
    assert payload["found"] is False
    assert payload["reason"].endswith("missing")
    assert payload["capabilities"] == []
    assert payload["error"]["code"] == "not_configured"


def test_reach_inventory_uses_pinned_env(tmp_path, monkeypatch, capsys):
    exe = _fake_cli(tmp_path)
    monkeypatch.setenv("TRAILHEAD_AGENT_REACH_BIN", exe)
    rc = main(["reach", "--format", "json"])
    payload = _json(capsys)
    assert rc == 0
    assert payload["executable"] == exe
    assert payload["capabilities"]


# ── forwarding ───────────────────────────────────────────────────────────────


def test_reach_call_maps_positional_args_and_options(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "v2ex",
            "node",
            "python",
            "--param",
            "limit=3",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0
    argv = payload["argv"]
    assert argv[1:3] == ["v2ex", "node"]
    assert "--limit" in argv and "3" in argv
    assert argv[-2:] == ["--", "python"]
    assert payload["engine"] == "agent-reach"
    assert payload["provenance"]["native"] is False
    assert "Agent Reach" in payload["provenance"]["attribution"]
    assert payload["backend"] == "v2ex-api"


def test_reach_call_forces_public_web_for_public_routes(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "web",
            "read",
            "https://example.com/page?x=1&y=2",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0
    argv = payload["argv"]
    assert "--backend" in argv and "public-web" in argv
    assert "https://example.com/page?x=1&y=2" in argv
    assert payload["provenance"]["forced_backend"] == "public-web"


def test_reach_call_requires_explicit_consent_for_session_actions(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach-call", "instagram", "profile", "nasa", "--agent-reach", exe, "--format", "json"])
    payload = _json(capsys)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth_required"
    assert "allow_authenticated" in payload["error"]["message"]


def test_reach_call_forwards_with_consent_flag(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "instagram",
            "profile",
            "nasa",
            "--allow-authenticated",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0
    assert payload["provenance"]["public_only"] is False
    assert "--backend" not in payload["argv"]


def test_reach_call_rejects_unlisted_action(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        ["reach-call", "youtube", "transcribe", "https://youtu.be/x", "--agent-reach", exe, "--format", "json"]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["error"]["code"] in {"action_not_allowlisted", "unknown_action"}


def test_reach_call_missing_executable_is_not_configured(tmp_path, capsys):
    rc = main(
        ["reach-call", "v2ex", "read", "https://v2ex.com/t/1", "--agent-reach", str(tmp_path / "gone"), "--format", "json"]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["error"]["code"] == "not_configured"


def test_reach_call_text_mode_prints_attribution(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach-call", "v2ex", "read", "https://www.v2ex.com/t/1", "--agent-reach", exe])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Attribution: Agent Reach" in out
    assert "Route:" in out
    assert "Items:" in out


def test_reach_call_rejects_bad_param_and_extra_positionals(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach-call", "v2ex", "node", "--param", "oops", "--agent-reach", exe])
    assert rc == 2
    assert "NAME=VALUE" in capsys.readouterr().err

    rc = main(["reach-call", "v2ex", "read", "a", "b", "--agent-reach", exe])
    assert rc == 2
    assert "positional" in capsys.readouterr().err


# ── shared pinned discovery ──────────────────────────────────────────────────


def test_compare_resolver_honours_the_pinned_env(tmp_path, monkeypatch):
    exe = _fake_cli(tmp_path)
    monkeypatch.setenv("TRAILHEAD_AGENT_REACH_BIN", exe)
    assert cp.resolve_agent_reach() == exe


def test_compare_resolver_returns_none_for_bad_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILHEAD_AGENT_REACH_BIN", str(tmp_path / "missing-agent-reach"))
    assert cp.resolve_agent_reach() is None


def test_compare_uses_pinned_executable_end_to_end(tmp_path, monkeypatch, capsys):
    exe = _fake_cli(tmp_path)
    monkeypatch.setenv("TRAILHEAD_AGENT_REACH_BIN", exe)
    monkeypatch.setattr(
        cp,
        "trailhead_case_runner",
        lambda case, timeout_s, **kw: cp._result_from_text(
            tool="trailhead", case=case, status="ok", text="word " * 800, duration_ms=5
        ),
    )
    rc = main(["compare", "--case", "web-wikipedia-http", "--format", "json"])
    report = _json(capsys)
    assert rc == 0
    assert report["environment"]["agent_reach"]["available"] is True
    assert report["environment"]["agent_reach"]["path"] == exe
    assert report["environment"]["agent_reach"]["version"] == "9.9.9"
    assert report["cases"][0]["comparison"]["agent_reach"]["status"] == "ok"
