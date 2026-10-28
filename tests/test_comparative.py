"""Tests for the measured Trailhead-vs-Agent-Reach comparative benchmark.

The property under test is honesty: matched outcomes per case, evidence-based
assessment instead of character counting, a sandboxed environment on both
sides, and no aggregate winner. No test touches the network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from hermes_trailhead import comparative as cp


# ── helpers ──────────────────────────────────────────────────────────────────


def _trailhead_ok(chars: int = 4000, ms: int = 10, text: str | None = None):
    def runner(case, timeout_s, **kwargs):
        body = text if text is not None else "word " * (chars // 5)
        return cp._result_from_text(
            tool="trailhead",
            case=case,
            status="ok",
            text=body,
            duration_ms=ms,
        )

    return runner


def _agent_reach_ok(
    chars: int = 4000, ms: int = 20, text: str | None = None, status: cp.CaseStatus = "ok"
):
    def runner(case, timeout_s, executable, *, env=None):
        body = text if text is not None else "word " * (chars // 5)
        return cp._result_from_text(
            tool="agent_reach",
            case=case,
            status=status,
            text=body if status == "ok" else "",
            duration_ms=ms,
        )

    return runner


def _fake_cli(tmp_path, body: str):
    script = tmp_path / "agent-reach"
    script.write_text(f"#!{sys.executable}\n" + body)
    script.chmod(0o755)
    return str(script)


ENVELOPE_OK = """
import json, sys
print(json.dumps({"schema_version": 1, "ok": True, "channel": "youtube",
                  "action": "subtitle", "backend": "yt-dlp",
                  "items": [{"title": "t", "url": "", "author": None,
                             "published_at": None, "text": "WEBVTT\\n\\n00:00:01.000 --> 00:00:03.000\\n"
                             + "spoken subtitle line " * 40, "raw": None}],
                  "meta": {"elapsed_ms": 5, "attempts": []}, "error": None}))
"""


# ── manifest honesty ─────────────────────────────────────────────────────────


def test_every_case_declares_the_agent_reach_outcome_it_asks_for():
    for case in cp.CASES:
        assert case.agent_reach_command, case.id
        assert case.agent_reach_command[0] != "transcribe"


def test_youtube_case_requests_subtitles_not_metadata_read():
    case = cp.CASES_BY_ID["video-youtube-transcript"]
    assert case.agent_reach_command[:2] == ("youtube", "subtitle")
    assert case.evidence_requirement == "transcript"
    assert "read" not in case.agent_reach_command


def test_v2ex_node_case_uses_the_node_action_not_read():
    case = cp.CASES_BY_ID["forum-v2ex-node"]
    assert case.agent_reach_command == ("v2ex", "node", "python")
    assert "{prompt}" not in " ".join(case.agent_reach_command)


def test_question_case_is_scoped_to_one_lane_on_both_sides():
    case = cp.CASES_BY_ID["question-typing-protocol"]
    assert case.kind == "question"
    assert case.trailhead_lane == "web"
    assert case.agent_reach_command[0] == "web"


def test_auth_cases_are_declared_and_skipped_by_default():
    auth_ids = {case.id for case in cp.CASES if case.requires_auth}
    assert auth_ids
    report = cp.run_compare(
        timeout_s=5,
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    for entry in report["cases"]:
        if entry["case"]["id"] in auth_ids:
            assert entry["comparison"] is None
            assert entry["skip"]["status"] == "not_run"
    assert report["summary"]["cases_skipped_auth"] == len(auth_ids)


def test_include_auth_runs_auth_cases():
    report = cp.run_compare(
        case_ids=["instagram-profile-session-tier"],
        include_auth=True,
        timeout_s=5,
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    entry = report["cases"][0]
    assert entry["comparison"] is not None
    assert report["summary"]["cases_skipped_auth"] == 0
    # An --include-auth case is an unauthenticated attempt, never a consent run.
    assert entry["auth"]["mode"] == "unauthenticated_attempt"
    assert entry["auth"]["configured"] is False
    assert "not an authenticated comparison" in entry["auth"]["note"].lower()
    assert report["summary"]["cases_auth_unauthenticated"] == 1
    text = cp.format_compare_text(report)
    assert "unauthenticated_attempt" in text
    assert "not a filesystem or OS sandbox" in text


def test_skipped_auth_case_is_labeled_not_configured():
    report = cp.run_compare(
        case_ids=["instagram-profile-session-tier"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    entry = report["cases"][0]
    assert entry["auth"]["mode"] == "skipped"
    assert entry["auth"]["configured"] is False
    assert report["summary"]["cases_auth_unauthenticated"] == 0


# ── evidence assessment ──────────────────────────────────────────────────────


def test_plain_readable_text_is_evidence():
    result = cp.assess_evidence("word " * 400)
    assert result["verdict"] == "evidence"
    assert result["evidence_ok"] is True


def test_markup_is_stripped_and_does_not_count_as_evidence():
    raw = "<div class='nav'>" + "<span class='i' data-x='1'></span>" * 2000 + "</div>"
    result = cp.assess_evidence(raw, min_chars=200)
    assert result["raw_chars"] > 20000
    assert result["cleaned_chars"] < 200
    assert result["verdict"] in {"empty", "thin"}
    assert result["evidence_ok"] is False


def test_html_with_real_prose_is_evidence_but_reports_both_lengths():
    body = "<html><body>" + "<p>" + ("real article sentence " * 100) + "</p></body></html>"
    result = cp.assess_evidence(body)
    assert result["evidence_ok"] is True
    assert result["raw_chars"] > result["cleaned_chars"]
    assert result["markup_ratio"] > 0


def test_nav_chrome_shell_is_not_evidence():
    shell = (
        "Skip to content Menu Cookie policy Privacy policy Terms of service "
        "Sign up Log in All rights reserved Advertisement Breadcrumb"
    )
    result = cp.assess_evidence(shell)
    assert result["chrome_signals"] >= 3
    assert result["verdict"] in {"chrome_heavy", "thin"}
    assert result["evidence_ok"] is False


def test_substantial_prose_with_one_nav_phrase_stays_evidence():
    prose = (
        "Privacy policy aside, the protocol requires structural subtyping. "
        + "This paragraph explains the requirement in depth. " * 40
    )
    result = cp.assess_evidence(prose)
    assert result["evidence_ok"] is True


def test_long_markup_heavy_page_is_accepted_on_cleaned_text_only():
    # The documented rule: markup-heaviness rejects only *short* payloads. A
    # long page clearing 4x the floor is accepted on cleaned text, which is a
    # "readable text came back" signal, not a content-quality promise.
    raw = "<div class='x'>" * 20_000 + "real prose sentence " * 400
    result = cp.assess_evidence(raw)
    assert result["markup_ratio"] > 0.5
    assert result["cleaned_chars"] >= 800
    assert result["verdict"] == "evidence"


def test_login_wall_is_not_success():
    wall = "Log in to continue. Enable JavaScript to sign in. " * 3
    result = cp.assess_evidence(wall)
    assert result["verdict"] == "login_wall"
    assert result["evidence_ok"] is False


def test_short_metadata_does_not_satisfy_a_transcript_case():
    metadata = "Video title and description. " * 20
    result = cp.assess_evidence(metadata, requirement="transcript")
    assert result["transcript_detected"] is False
    assert result["evidence_ok"] is False


def test_vtt_cues_satisfy_a_transcript_case():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\nhello there\n\n"
        "00:00:03.000 --> 00:00:05.000\nhello again\n\n"
        "00:00:05.000 --> 00:00:07.000\nand again\n\n" + "more speech " * 60
    )
    result = cp.assess_evidence(vtt, requirement="transcript")
    assert result["transcript_detected"] is True
    assert result["evidence_ok"] is True


def test_supplied_transcript_payload_satisfies_transcript_requirement():
    result = cp.assess_evidence(
        "caption text " * 60, requirement="transcript", transcript_supplied=True
    )
    assert result["evidence_ok"] is True


# ── sandbox ──────────────────────────────────────────────────────────────────


def test_sandbox_drops_credentials_and_disables_billable_asr(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    sandbox = cp.build_sandbox(tmp_path / "sbx")
    env = sandbox["env"]
    assert env["HOME"].startswith(str(tmp_path / "sbx"))
    assert env["HERMES_HOME"].startswith(env["HOME"])
    assert "OPENAI_API_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert env[cp.ASR_DISABLE_ENV] == "1"
    assert env["PYTHONPATH"] == str(cp.package_root())
    assert all(not cp.is_sensitive_env(name) for name in env)


def test_sandbox_asr_flag_is_honored_by_extract():
    # Pins the contract with extract.py: the existing switch really does gate
    # the paid ASR tier inside the sandboxed environment. No network involved.
    env = cp.build_sandbox()["env"]
    code = "from hermes_trailhead import extract; print('disabled=', extract._asr_disabled())"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(cp.package_root()),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "disabled= True" in completed.stdout


def test_run_compare_never_mutates_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_a_real_token")
    monkeypatch.setenv("HOME", str(tmp_path / "operator-home"))
    before = dict(os.environ)
    cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    assert os.environ == before


def test_both_runners_receive_the_sandbox_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILHEAD_CAMOFOX_USER", "operator-session")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_not_a_real_key")
    seen: dict[str, dict] = {}

    def trailhead_runner(case, timeout_s, *, env=None, **kwargs):
        seen["trailhead"] = dict(env or {})
        return cp._result_from_text(
            tool="trailhead", case=case, status="ok", text="word " * 400, duration_ms=1
        )

    def agent_reach_runner(case, timeout_s, executable, *, env=None):
        seen["agent_reach"] = dict(env or {})
        return cp._result_from_text(
            tool="agent_reach", case=case, status="ok", text="word " * 400, duration_ms=1
        )

    cp.run_compare(
        case_ids=["web-wikipedia-http"],
        timeout_s=5,
        agent_reach="/bin/sh",
        trailhead_runner=trailhead_runner,
        agent_reach_runner=agent_reach_runner,
    )
    for tool in ("trailhead", "agent_reach"):
        env = seen[tool]
        assert "TRAILHEAD_CAMOFOX_USER" not in env
        assert "GROQ_API_KEY" not in env
        assert env[cp.ASR_DISABLE_ENV] == "1"
        assert "trailhead-compare-" in env["HOME"]


def test_default_run_is_cold_and_reused_sandbox_is_warm(tmp_path):
    cold = cp.run_compare(
        case_ids=["web-wikipedia-http"], with_agent_reach=False, trailhead_runner=_trailhead_ok()
    )
    assert cold["environment"]["sandbox"]["run_kind"] == "cold"
    assert cold["environment"]["sandbox"]["credentials_forwarded"] is False

    warm = cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
        sandbox_dir=str(tmp_path / "warm"),
    )
    assert warm["environment"]["sandbox"]["run_kind"] == "warm"
    again = cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
        sandbox_dir=str(tmp_path / "warm"),
    )
    assert again["environment"]["sandbox"]["root"] == warm["environment"]["sandbox"]["root"]


# ── Trailhead worker subprocess ──────────────────────────────────────────────


def test_trailhead_worker_argv_is_a_python_module_call():
    argv = cp.trailhead_worker_argv()
    assert argv[0] == (sys.executable or "python3")
    assert argv[1:] == ["-m", "hermes_trailhead.comparative", "--worker"]
    assert "shell" not in argv


def test_worker_request_round_trips_the_case():
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    request = cp.worker_request(case, timeout_s=7, search_limit=2)
    assert request["schema"] == cp.WORKER_SCHEMA
    assert cp.case_from_dict(request["case"]) == case


def test_worker_result_cannot_relabel_itself():
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    original = cp._result_from_text(
        tool="agent_reach", case=case, status="ok", text="word " * 400, duration_ms=3
    )
    rebuilt = cp.case_result_from_dict(
        original.to_dict(), tool="trailhead", case_id="a-different-case"
    )
    assert rebuilt.tool == "trailhead"
    assert rebuilt.case_id == "a-different-case"
    assert rebuilt.evidence_ok is True


def test_worker_payload_reports_bad_requests_without_raising():
    payload = cp.worker_payload({"case": {"id": "x"}})
    assert payload["schema"] == cp.WORKER_SCHEMA
    assert payload["ok"] is False
    assert "bad worker request" in payload["error"]


def test_trailhead_runner_parses_worker_json(tmp_path):
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result_fields = {
        "tool": "trailhead",
        "case_id": "x",
        "status": "ok",
        "duration_ms": 5,
        "raw_chars": 2000,
        "cleaned_chars": 2000,
        "markup_ratio": 0.0,
        "evidence_verdict": "evidence",
        "evidence_note": "2000 cleaned chars",
        "item_count": 1,
        "backend": "fake-worker",
        "error": "",
        "exit_code": 0,
        "command": [],
        "preview": "word",
        "detail": "",
        "freshness": "fresh",
    }
    body = (
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request['schema'] == 'trailhead.comparative.worker/1'\n"
        f"payload = {{'schema': 'trailhead.comparative.worker/1', 'ok': True, "
        f"'result': {result_fields!r}}}\n"
        "print(json.dumps(payload))\n"
    )
    result = cp.trailhead_case_runner(
        case,
        5,
        env=cp.build_sandbox()["env"],
        worker_argv=[sys.executable, "-c", body],
    )
    assert result.status == "ok"
    assert result.backend == "fake-worker"
    assert result.evidence_ok is True
    assert result.case_id == case.id
    assert "worker wall" in result.detail


def test_trailhead_runner_defaults_to_a_sandbox_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_not_a_real_key")
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    body = (
        "import json, os\n"
        "payload = {'schema': 'trailhead.comparative.worker/1', 'ok': True, 'result': {"
        "'status': 'ok', 'preview': os.environ.get('HOME', ''), "
        "'detail': os.environ.get('GROQ_API_KEY', 'no-key')}}\n"
        "print(json.dumps(payload))\n"
    )
    result = cp.trailhead_case_runner(
        case, 5, worker_argv=[sys.executable, "-c", body]
    )
    assert "trailhead-compare-" in result.preview
    assert result.detail.startswith("no-key")


def test_trailhead_runner_kills_the_worker_at_the_shared_wall_timeout():
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result = cp.trailhead_case_runner(
        case,
        1,
        env=cp.build_sandbox()["env"],
        worker_argv=[sys.executable, "-c", "import time; time.sleep(30)"],
    )
    assert result.status == "timeout"
    assert "same budget as Agent Reach" in result.error
    assert result.duration_ms is not None and result.duration_ms < 15_000


def test_trailhead_runner_reports_non_json_worker_output_as_error():
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result = cp.trailhead_case_runner(
        case,
        5,
        env=cp.build_sandbox()["env"],
        worker_argv=[sys.executable, "-c", "print('not json at all')"],
    )
    assert result.status == "error"
    assert "worker" in result.error.lower()


# ── Agent Reach argv and subprocess behaviour ────────────────────────────────


def test_agent_reach_argv_is_a_list_with_timeout_and_terminator():
    case = cp.CASES_BY_ID["video-youtube-transcript"]
    argv = cp.agent_reach_command(case, "/opt/bin/agent-reach", timeout_s=12)
    assert isinstance(argv, list)
    assert argv[0] == "/opt/bin/agent-reach"
    assert argv[1:3] == ["youtube", "subtitle"]
    assert argv[-2:] == ["--timeout", "12"]
    assert case.prompt in argv
    assert "--" not in argv


def test_v2ex_node_argv_uses_node_action():
    case = cp.CASES_BY_ID["forum-v2ex-node"]
    argv = cp.agent_reach_command(case, "agent-reach", timeout_s=9)
    assert argv[1:4] == ["v2ex", "node", "python"]
    assert argv[-2:] == ["--timeout", "9"]


def test_agent_reach_runner_parses_envelope_and_detects_transcript(tmp_path):
    exe = _fake_cli(tmp_path, ENVELOPE_OK)
    case = cp.CASES_BY_ID["video-youtube-transcript"]
    result = cp.agent_reach_case_runner(case, 10, exe, env=cp.build_sandbox()["env"])
    assert result.status == "ok"
    assert result.backend == "yt-dlp"
    assert result.transcript_detected is True
    assert result.evidence_ok is True
    assert result.command[1:3] == ["youtube", "subtitle"]


def test_agent_reach_runner_maps_need_login_to_blocked(tmp_path):
    exe = _fake_cli(
        tmp_path,
        """
import json
print(json.dumps({"schema_version": 1, "ok": False, "channel": "instagram",
                  "action": "profile", "backend": None, "items": [],
                  "meta": {}, "error": {"code": "NEED_LOGIN", "message": "login required"}}))
""",
    )
    case = cp.CASES_BY_ID["instagram-profile-session-tier"]
    result = cp.agent_reach_case_runner(case, 10, exe, env=cp.build_sandbox()["env"])
    assert result.status == "blocked"
    assert "NEED_LOGIN" in result.error
    assert result.evidence_ok is False


def test_agent_reach_runner_reports_timeout_without_shell(tmp_path):
    exe = _fake_cli(tmp_path, "import time\ntime.sleep(30)\n")
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result = cp.agent_reach_case_runner(case, 1, exe, env=cp.build_sandbox()["env"])
    assert result.status == "timeout"
    assert result.duration_ms is not None


def test_agent_reach_runner_treats_non_json_as_error(tmp_path):
    exe = _fake_cli(tmp_path, "print('not json at all')\n")
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result = cp.agent_reach_case_runner(case, 5, exe, env=cp.build_sandbox()["env"])
    assert result.status == "error"
    assert "not JSON" in result.error


def test_agent_reach_runner_marks_missing_executable_unavailable(tmp_path):
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    result = cp.agent_reach_case_runner(case, 5, str(tmp_path / "nope"))
    assert result.status == "unavailable"
    assert result.exercised is False


# ── comparison and summary ───────────────────────────────────────────────────


def test_no_aggregate_winner_even_when_trailhead_wins_every_case():
    report = cp.run_compare(
        timeout_s=5,
        with_agent_reach=True,
        agent_reach="/bin/sh",
        trailhead_runner=_trailhead_ok(chars=8000),
        agent_reach_runner=_agent_reach_ok(chars=0, status="blocked"),
    )
    summary = report["summary"]
    assert summary["aggregate_ranking"] is None
    assert "winner" not in summary
    assert summary["verdict_counts"]["trailhead_only_evidence"] >= 5
    assert "no aggregate winner" in summary["ranking_note"]


def test_verdicts_never_reward_character_count_alone():
    case = cp.CASES_BY_ID["web-wikipedia-http"]
    huge_markup = cp._result_from_text(
        tool="trailhead",
        case=case,
        status="ok",
        text="<div>" * 5000,
        duration_ms=100,
    )
    short_prose = cp._result_from_text(
        tool="agent_reach",
        case=case,
        status="ok",
        text="A concise, complete answer. " * 30,
        duration_ms=100,
    )
    assert huge_markup.raw_chars > short_prose.raw_chars
    assert huge_markup.evidence_ok is False
    assert short_prose.evidence_ok is True
    comparison = cp.compare_case(case, huge_markup, short_prose)
    assert comparison.verdict == "agent_reach_only_evidence"


def test_transcript_case_does_not_reward_metadata_reads():
    case = cp.CASES_BY_ID["video-youtube-transcript"]
    metadata = cp._result_from_text(
        tool="agent_reach",
        case=case,
        status="ok",
        text="Title: gradient descent. Description: " + "blah " * 200,
        duration_ms=50,
    )
    assert metadata.evidence_ok is False


def test_unavailable_agent_reach_makes_cases_not_comparable(tmp_path):
    report = cp.run_compare(
        case_ids=["web-wikipedia-http", "video-youtube-transcript"],
        timeout_s=5,
        agent_reach=str(tmp_path / "missing-agent-reach"),
        trailhead_runner=_trailhead_ok(),
    )
    assert report["summary"]["cases_both_exercised"] == 0
    assert report["summary"]["verdict_counts"]["not_comparable"] == 2
    assert report["environment"]["agent_reach"]["available"] is False
    assert report["summary"]["aggregate_ranking"] is None


def test_no_agent_reach_flag_records_not_run():
    report = cp.run_compare(
        case_ids=["web-wikipedia-http"], with_agent_reach=False, trailhead_runner=_trailhead_ok()
    )
    row = report["cases"][0]["comparison"]["agent_reach"]
    assert row["status"] == "not_run"
    assert row["exercised"] is False
    assert "disabled" in report["summary"]["ranking_note"]


def test_question_case_searches_only_its_declared_lane(monkeypatch):
    from hermes_trailhead import search as search_mod

    seen: list[str] = []

    class _Hit:
        def __init__(self):
            self.title = "t"
            self.url = "https://example.com/x"
            self.snippet = "s"
            self.platform = "web"

    class _Execution:
        platform = "web"
        error = ""
        hits = (_Hit(),)

    class _Run:
        executions = (_Execution(),)

    def fake_search(platform, query, live=False, limit=3):
        seen.append(platform)
        return _Run()

    monkeypatch.setattr(search_mod, "execute_search", fake_search)
    monkeypatch.setattr(
        "hermes_trailhead.extract.extract_hits",
        lambda hits, limit=3, timeout=10: [],
    )
    case = cp.CASES_BY_ID["question-typing-protocol"]
    cp.trailhead_worker_case(case, 5, search_limit=2)
    assert seen == ["web"]


def test_unknown_case_id_raises():
    with pytest.raises(KeyError):
        cp.run_compare(case_ids=["nope"], with_agent_reach=False)


# ── freshness ────────────────────────────────────────────────────────────────


def test_fast_video_read_without_cache_write_is_flagged():
    freshness, note = cp.classify_freshness("youtube", "ok", 3, (0, 0.0), (0, 0.0))
    assert freshness == "possibly_cached"
    assert "cached" in note


def test_fast_video_read_that_wrote_cache_is_fresh():
    freshness, _ = cp.classify_freshness("youtube", "ok", 250, (0, 0.0), (1, 99.0))
    assert freshness == "fresh"


def test_slow_or_non_video_reads_are_fresh():
    assert cp.classify_freshness("youtube", "ok", 4000, (3, 1.0), (3, 1.0))[0] == "fresh"
    assert cp.classify_freshness("web", "ok", 5, (3, 1.0), (3, 1.0))[0] == "fresh"


# ── reports ──────────────────────────────────────────────────────────────────


def test_report_labels_injected_runners_and_environment_only_isolation():
    report = cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    execution = report["environment"]["execution"]
    assert execution["trailhead"] == "injected"
    assert execution["agent_reach"] == "not_run"
    assert "test-only" in execution["note"]

    isolation = report["environment"]["isolation"]
    assert isolation["kind"] == "environment-only"
    assert isolation["filesystem_sandbox"] is False
    assert isolation["credential_proof"] is False
    assert report["environment"]["sandbox"]["filesystem_sandbox"] is False
    assert report["environment"]["billable_asr"]["disabled"] is True
    assert report["environment"]["billable_asr"]["env"] == f"{cp.ASR_DISABLE_ENV}=1"
    assert report["environment"]["wall_timeout_s"] == report["environment"]["host_timeout_s"]

    text = cp.format_compare_text(report)
    assert "trailhead=injected" in text
    assert "Billable ASR: disabled" in text
    assert "not a filesystem or OS sandbox" in text


def test_evidence_rule_names_the_markup_threshold_instead_of_a_blanket_claim():
    report = cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    rule = report["methodology"]["evidence_rule"]
    assert "cleaned" in rule
    assert "4x the floor" in rule
    assert "not relevance or content quality" in rule
    assert "markup-dominated" not in rule


def test_report_serializes_and_contains_no_grades(tmp_path):
    report = cp.run_compare(
        case_ids=["web-wikipedia-http"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    target = cp.write_report(report, tmp_path / "out" / "report.json")
    loaded = json.loads(open(target, encoding="utf-8").read())
    assert loaded["schema"] == cp.REPORT_SCHEMA
    assert loaded["summary"]["aggregate_ranking"] is None
    text = cp.format_compare_text(loaded)
    assert "aggregate ranking: none" in text.lower()
    assert "A-" not in text
    md = cp.format_compare_markdown(loaded)
    assert "Aggregate ranking:** none" in md


def test_text_report_marks_skipped_auth_cases(tmp_path):
    report = cp.run_compare(
        case_ids=["instagram-profile-session-tier"],
        with_agent_reach=False,
        trailhead_runner=_trailhead_ok(),
    )
    text = cp.format_compare_text(report)
    assert "auth-gated" in text
    assert "skipped" in text
    assert "no comparison is possible" in text or "not run" in text.lower()
