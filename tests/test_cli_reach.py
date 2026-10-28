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
        {
            "name": "xiaoyuzhou",
            "description": "podcast",
            "level": "optional",
            "login": None,
            "actions": [
                {
                    "name": "transcribe",
                    "help": "podcast asr",
                    "params": [
                        {"name": "target", "help": "url", "required": True, "type": "str", "default": None}
                    ],
                    "backends": ["groq-whisper"],
                    "public_web": [],
                }
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
    rows = {(row["channel"], row["action"]): row for row in payload["capabilities"]}
    assert ("v2ex", "read") in rows
    assert ("web", "read") in rows
    # Paid transcription is discoverable but blocked and never public.
    quota = rows[("youtube", "transcribe")]
    assert quota["gate"] == "quota"
    assert quota["public"] is False
    assert quota["quota_consuming"] is True
    assert quota["blocked_by_default"] is True
    assert rows[("xiaoyuzhou", "transcribe")]["gate"] == "quota"
    # The pinned inventory travels with the inventory command.
    parity = payload["parity"]
    assert parity["reference"]["commit"] == "14c213405669414492bda0f8d52cc6531d062c45"
    assert parity["counts"] == {
        **parity["counts"],
        "actions": 40,
        "channels": 14,
        "gated_quota": 2,
        "live_verified": 5,
        "fixture_only": 35,
    }
    assert payload["quota_consuming_allowed"] is False
    assert payload["asr_disabled"] is False


def test_reach_inventory_text_marks_auth_gated_actions(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(["reach", "--agent-reach", exe])
    out = capsys.readouterr().out
    assert rc == 0
    assert "public-only" in out
    assert "instagram" in out and "needs --allow-authenticated" in out
    assert "needs --allow-quota-consuming + --allow-authenticated" in out
    # Parity table is printed even though only a subset exists upstream here.
    assert "Parity reference: Panniantong/Agent-Reach 1.6.0" in out
    assert "40/40 inventoried" in out
    assert "not live runs" in out
    assert "xiaoyuzhou" in out and "transcribe" in out


def test_reach_inventory_parity_survives_a_missing_executable(tmp_path, capsys):
    rc = main(["reach", "--agent-reach", str(tmp_path / "nope"), "--format", "json"])
    payload = _json(capsys)
    assert rc == 0
    assert payload["found"] is False
    assert payload["capabilities"] == []
    # Static pinned inventory is still reported, without pretending it is live.
    assert payload["parity"]["counts"]["actions"] == 40
    assert payload["parity"]["counts"]["live_verified"] == 5


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


def test_reach_call_transcription_is_blocked_by_default(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        ["reach-call", "youtube", "transcribe", "https://youtu.be/x", "--agent-reach", exe, "--format", "json"]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "quota_required"
    assert "--allow-quota-consuming" in payload["error"]["message"]
    assert payload["argv"] == []  # nothing spawned


def test_reach_call_transcription_needs_both_flags(tmp_path, capsys):
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "xiaoyuzhou",
            "transcribe",
            "https://www.xiaoyuzhoufm.com/episode/x",
            "--allow-quota-consuming",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["error"]["code"] == "auth_required"
    assert "allow_authenticated" in payload["error"]["message"]
    assert payload["argv"] == []


def test_reach_call_transcription_runs_with_both_flags(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TRAILHEAD_DISABLE_ASR", raising=False)
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "youtube",
            "transcribe",
            "https://youtu.be/x",
            "--allow-quota-consuming",
            "--allow-authenticated",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0, payload
    assert payload["ok"] is True
    assert payload["provenance"]["quota_consuming"] is True
    assert payload["provenance"]["route"] == "quota"
    assert payload["provenance"]["public_only"] is False
    assert "--backend" not in payload["argv"]
    assert any("quota" in line.lower() for line in payload["limitations"])


def test_reach_call_asr_veto_wins_over_both_cli_flags(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    exe = _fake_cli(tmp_path)
    rc = main(
        [
            "reach-call",
            "youtube",
            "transcribe",
            "https://youtu.be/x",
            "--allow-quota-consuming",
            "--allow-authenticated",
            "--agent-reach",
            exe,
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["error"]["code"] == "asr_disabled"
    assert payload["argv"] == []


def test_reach_inventory_reports_quota_consent_and_asr_veto(tmp_path, capsys, monkeypatch):
    exe = _fake_cli(tmp_path)
    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    rc = main(
        [
            "reach",
            "--agent-reach",
            exe,
            "--allow-quota-consuming",
            "--allow-authenticated",
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0
    assert payload["quota_consuming_allowed"] is True
    assert payload["asr_disabled"] is True
    quota = {(r["channel"], r["action"]): r for r in payload["capabilities"]}[
        ("youtube", "transcribe")
    ]
    assert quota["asr_veto"] is True


def test_gate_refusals_spawn_no_process_at_all(tmp_path, capsys, monkeypatch):
    """A refused quota call must not even read the upstream registry."""
    monkeypatch.delenv("TRAILHEAD_DISABLE_ASR", raising=False)
    marker = tmp_path / "spawned.txt"
    script = tmp_path / "agent-reach"
    script.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print('{}')\n"
    )
    script.chmod(0o755)

    attempts = [
        ["reach-call", "youtube", "transcribe", "https://youtu.be/x"],
        ["reach-call", "youtube", "transcribe", "https://youtu.be/x", "--allow-quota-consuming"],
        ["reach-call", "xiaoyuzhou", "transcribe", "https://x.test/e", "--allow-authenticated"],
    ]
    for argv in attempts:
        rc = main([*argv, "--agent-reach", str(script), "--format", "json"])
        payload = _json(capsys)
        assert rc == 1
        assert payload["error"]["code"] in {"quota_required", "auth_required"}
        assert payload["argv"] == []
        assert not marker.exists(), f"spawned a process for {argv}: {marker.read_text()}"
        marker.unlink(missing_ok=True)

    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    rc = main(
        [
            "reach-call",
            "youtube",
            "transcribe",
            "https://youtu.be/x",
            "--allow-quota-consuming",
            "--allow-authenticated",
            "--agent-reach",
            str(script),
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 1
    assert payload["error"]["code"] == "asr_disabled"
    assert not marker.exists()


def test_search_cli_has_no_quota_consent_flag():
    """A normal search run cannot opt into billable transcription."""
    import argparse

    from hermes_trailhead.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    search_parser = sub.choices["search"]
    options = {opt for action in search_parser._actions for opt in action.option_strings}
    assert "--allow-quota-consuming" not in options
    assert "--allow-authenticated" not in options


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


def test_reach_call_text_shows_body_cut_and_unknown_continuation(tmp_path, capsys):
    """Text mode must not let a locally cut body look whole or complete."""
    payload = {
        "schema_version": 1,
        "ok": True,
        "channel": "v2ex",
        "action": "read",
        "backend": "v2ex-api",
        "items": [
            {
                "title": "a long topic",
                "url": "https://www.v2ex.com/t/1",
                "author": "someone",
                "published_at": "2026-01-01T00:00:00Z",
                "text": "line " * 60_000,  # 300 000 chars: past the shared budget
                "raw": None,
            }
        ],
        "meta": {"elapsed_ms": 1, "attempts": []},
        "error": None,
    }
    body = (
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        'if argv and argv[0] == "channels":\n'
        f"    print(json.dumps({REGISTRY!r}))\n"
        "    sys.exit(0)\n"
        f"print(json.dumps({payload!r}))\n"
    )
    exe = _fake_cli(tmp_path, body=body)
    rc = main(["reach-call", "v2ex", "read", "https://www.v2ex.com/t/1", "--agent-reach", exe])
    out = capsys.readouterr().out

    assert rc == 0
    assert "250000 of 300000 chars" in out
    assert "[cut at Trailhead's shared body budget]" in out
    assert "Upstream:    continuation unknown" in out
    # The 160-char preview is marked as a preview, not the artifact.
    assert "…" in out
    assert "local forwarding bound" in out


def test_reach_inventory_gate_vocabulary_and_quota_readiness(tmp_path, capsys, monkeypatch):
    """Capabilities and the parity inventory share public/consent/quota, and
    quota consent is reported separately from quota readiness."""
    exe = _fake_cli(tmp_path)
    monkeypatch.delenv("TRAILHEAD_DISABLE_ASR", raising=False)
    rc = main(
        [
            "reach",
            "--agent-reach",
            exe,
            "--allow-quota-consuming",
            "--allow-authenticated",
            "--format",
            "json",
        ]
    )
    payload = _json(capsys)
    assert rc == 0
    gates = {row["gate"] for row in payload["capabilities"]}
    assert gates <= {"public", "consent", "quota"}
    assert "authenticated" not in gates
    assert payload["authenticated_allowed"] is True
    assert payload["quota_consuming_allowed"] is True
    assert payload["quota_ready"] is True
    assert payload["asr_disabled"] is False
    assert payload["credential_source"] == "upstream-home-config"

    monkeypatch.setenv("TRAILHEAD_DISABLE_ASR", "1")
    rc = main(
        ["reach", "--agent-reach", exe, "--allow-quota-consuming", "--allow-authenticated"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Quota now:  not ready" in out
    assert "auth consent: consented" in out
    assert "ASR veto (TRAILHEAD_DISABLE_ASR): on" in out


def test_search_text_prints_attribution_when_present(monkeypatch, capsys):
    from types import SimpleNamespace

    from hermes_trailhead import cli as cli_module

    execution = SimpleNamespace(
        platform="web",
        status="ok",
        result_count=0,
        engine="agent_reach_web",
        attribution="Agent Reach (third-party CLI), forwarded by Hermes Trailhead",
        caveat="",
        error="",
        hits=[],
    )
    executed = SimpleNamespace(
        plan=SimpleNamespace(query="hermes", paid_api_required=False),
        executions=(execution,),
    )
    monkeypatch.setattr(cli_module, "search_execute_data", lambda *a, **k: executed)
    rc = main(["search", "web", "hermes", "--execute", "--no-extract"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Engine: agent_reach_web" in out
    assert "Attribution: Agent Reach (third-party CLI), forwarded by Hermes Trailhead" in out


def test_search_text_omits_attribution_when_absent(monkeypatch, capsys):
    from types import SimpleNamespace

    from hermes_trailhead import cli as cli_module

    execution = SimpleNamespace(
        platform="web",
        status="ok",
        result_count=0,
        engine="exa",
        attribution="",
        caveat="",
        error="",
        hits=[],
    )
    executed = SimpleNamespace(
        plan=SimpleNamespace(query="hermes", paid_api_required=False),
        executions=(execution,),
    )
    monkeypatch.setattr(cli_module, "search_execute_data", lambda *a, **k: executed)
    rc = main(["search", "web", "hermes", "--execute", "--no-extract"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Engine: exa" in out
    assert "Attribution:" not in out


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
