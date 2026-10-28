"""Contract tests for the optional Agent Reach backend.

No network and no real Agent Reach install are required: a fake executable and
an injected runner stand in for upstream.  The suite pins the safety envelope
(read-only allowlist, no shell, public-mode behaviour, untrusted registry
validation) and the attribution contract.
"""
from __future__ import annotations

from types import SimpleNamespace
import json
import os
import pathlib
import sys
import tempfile

import pytest

from hermes_trailhead import reach_backend as reach


# ── fixtures ──────────────────────────────────────────────────────────────


def _param(name: str, *, required: bool = False, ptype: str = "str") -> dict:
    return {"name": name, "help": "", "required": required, "type": ptype, "default": None}


def registry_payload() -> dict:
    """A trimmed but shape-accurate `agent-reach channels` payload (v1.6.0)."""
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {
            "read": "agent-reach read <url>  (picks the channel from the URL)",
            "action": "agent-reach <channel> <action> [args] [--timeout SECONDS]",
        },
        "channels": [
            {
                "name": "github",
                "description": "GitHub 仓库和代码",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "Search repositories",
                        "usage": "agent-reach github search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a repository or an issue / PR",
                        "usage": "agent-reach github read <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "v2ex",
                "description": "V2EX 节点、主题与回复",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "hot",
                        "help": "Hot topics",
                        "usage": "agent-reach v2ex hot [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                    {
                        "name": "node",
                        "help": "A node's topics",
                        "usage": "agent-reach v2ex node <node_name> [--limit LIMIT]",
                        "params": [_param("node_name", required=True), _param("limit", ptype="int")],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "twitter",
                "description": "Twitter/X 推文",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login twitter"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search tweets",
                        "usage": "agent-reach twitter search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["opencli"],
                        "public_web": ["x.com/", "twitter.com/"],
                    },
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach twitter profile <username>",
                        "params": [_param("username", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "bilibili",
                "description": "B站视频、字幕和搜索",
                "level": "default",
                "login": {"via": "session", "logged_in": False, "command": "agent-reach login bilibili"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search videos",
                        "usage": "agent-reach bilibili search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read one video",
                        "usage": "agent-reach bilibili read <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot",
                        "help": "Hot videos",
                        "usage": "agent-reach bilibili hot [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "subtitle",
                        "help": "Video subtitles (needs the bili-cli login)",
                        "usage": "agent-reach bilibili subtitle <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "xueqiu",
                "description": "雪球股票行情与社区动态",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login xueqiu"},
                "actions": [
                    {
                        "name": "quote",
                        "help": "Real-time quote",
                        "usage": "agent-reach xueqiu quote <symbol>",
                        "params": [_param("symbol", required=True)],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "search",
                        "help": "Find stocks",
                        "usage": "agent-reach xueqiu search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_posts",
                        "help": "Trending community posts (needs a session)",
                        "usage": "agent-reach xueqiu hot_posts [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_stocks",
                        "help": "Most-watched stocks (needs a session)",
                        "usage": "agent-reach xueqiu hot_stocks [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "youtube",
                "description": "YouTube 视频和字幕",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "transcribe",
                        "help": "Transcribe audio",
                        "usage": "agent-reach youtube transcribe <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["whisper"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "xiaoyuzhou",
                "description": "小宇宙播客转文字",
                "level": "optional",
                "login": None,
                "actions": [
                    {
                        "name": "transcribe",
                        "help": "Transcribe a podcast",
                        "usage": "agent-reach xiaoyuzhou transcribe <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["groq-whisper"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "instagram",
                "description": "Instagram 主页与帖子",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login instagram"},
                "actions": [
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach instagram profile <username>",
                        "params": [_param("username", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "rogue",
                "description": "a channel Trailhead never forwards",
                "level": "optional",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "not allowlisted",
                        "usage": "agent-reach rogue search <query>",
                        "params": [_param("query", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    }
                ],
            },
        ],
    }


#: Backend label a cooperating upstream reports for each channel's default
#: route.  Forced-route tests override it to simulate a mismatched upstream.
DEFAULT_BACKEND = {
    "github": "github-api",
    "v2ex": "v2ex-api",
    "bilibili": "bilibili-api",
    "xueqiu": "tencent",
    "twitter": "public-web",
}


def ok_envelope(channel: str, action: str, *, items=None, backend=None, attempts=None) -> dict:
    if backend is None:
        backend = DEFAULT_BACKEND.get(channel, "public-web")
    return {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": backend,
        "items": items
        if items is not None
        else [
            {
                "title": "thedevs-network/kutt",
                "url": "https://github.com/thedevs-network/kutt",
                "author": "thedevs-network",
                "published_at": "2018-02-13T12:33:16Z",
                "text": "Free Modern URL Shortener.",
                "raw": {"stargazers_count": 11179},
            }
        ],
        "meta": {
            "elapsed_ms": 332,
            "attempts": attempts
            if attempts is not None
            else [{"backend": "gh", "result": "NEED_SETUP", "message": "no credentials"},
                  {"backend": "github-api", "result": "ok"}],
        },
        "error": None,
    }


def error_envelope(channel: str, action: str, code="UPSTREAM_BROKEN", message="boom", hint="") -> dict:
    return {
        "schema_version": 1,
        "ok": False,
        "channel": channel,
        "action": action,
        "backend": None,
        "items": [],
        "meta": {"elapsed_ms": 12, "attempts": []},
        "error": {"code": code, "message": message, "hint": hint},
    }


class FakeRunner:
    """Records argv/timeout/env and replays a queued upstream response."""

    def __init__(self, payload=None, *, action_response=None, raise_timeout=False):
        self.payload = payload if payload is not None else registry_payload()
        self.action_response = action_response
        self.raise_timeout = raise_timeout
        self.calls: list[dict] = []

    def __call__(self, argv, *, timeout, env):
        self.calls.append({"argv": list(argv), "timeout": timeout, "env": dict(env)})
        if list(argv)[1:] == ["channels"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.payload, ensure_ascii=False), stderr="")
        if self.raise_timeout:
            raise __import__("subprocess").TimeoutExpired(argv, timeout)
        response = self.action_response
        if response is None:
            response = ok_envelope(argv[1], argv[2], backend=self.forced_backend(argv))
        if isinstance(response, str):
            return SimpleNamespace(returncode=0, stdout=response, stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(response, ensure_ascii=False), stderr="")

    @staticmethod
    def forced_backend(argv) -> str | None:
        """Real upstream echoes the pinned label; None means 'pick the default'."""
        argv = list(argv)
        if "--backend" in argv:
            return argv[argv.index("--backend") + 1]
        return None

    @property
    def action_calls(self) -> list[dict]:
        return [c for c in self.calls if c["argv"][1:2] != ["channels"]]


@pytest.fixture()
def backend_factory(tmp_path_factory):
    stub = tmp_path_factory.mktemp("agent-reach") / "agent-reach"
    stub.write_text("#!/usr/bin/env python3\n")
    stub.chmod(0o755)

    def make(payload=None, *, action_response=None, raise_timeout=False, executable=None, **kwargs):
        runner = FakeRunner(payload, action_response=action_response, raise_timeout=raise_timeout)
        backend = reach.AgentReachBackend(str(stub) if executable is None else executable, runner=runner, **kwargs)
        return backend, runner

    return make


# ── discovery ─────────────────────────────────────────────────────────────


def test_discover_prefers_explicit_then_env_then_path(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    other = tmp_path / "other-agent-reach"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o755)

    found = reach.discover_agent_reach(str(exe), env={reach.AGENT_REACH_ENV: str(other)})
    assert found.found is True
    assert found.path == str(exe)
    assert found.reason == "explicit_ok"

    found = reach.discover_agent_reach(None, env={reach.AGENT_REACH_ENV: str(other)})
    assert found.path == str(other)
    assert found.reason == "env_ok"

    found = reach.discover_agent_reach(None, env={}, which=lambda name: str(exe) if name == "agent-reach" else None)
    assert found.path == str(exe)
    assert found.reason == "path_ok"


def test_discover_reports_missing_and_non_executable(tmp_path):
    missing = reach.discover_agent_reach(str(tmp_path / "nope"), env={})
    assert missing.found is False
    assert missing.reason == "explicit_missing"

    plain = tmp_path / "plain"
    plain.write_text("not executable")
    plain.chmod(0o644)
    found = reach.discover_agent_reach(str(plain), env={})
    assert found.found is False
    assert found.reason == "explicit_not_executable"

    directory = tmp_path / "dir"
    directory.mkdir()
    found = reach.discover_agent_reach(str(directory), env={})
    assert found.found is False
    assert found.reason == "explicit_is_directory"

    not_installed = reach.discover_agent_reach(None, env={}, which=lambda name: None)
    assert not_installed.found is False
    assert not_installed.reason == "not_installed"


def test_params_must_be_a_mapping(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("github", "search", ["query"])  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert runner.action_calls == []


def test_discover_accepts_pathlib_and_relative_names(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    found = reach.discover_agent_reach(exe)  # type: ignore[arg-type]
    assert found.found is True
    assert found.path == str(exe)

    found = reach.discover_agent_reach("agent-reach", env={}, which=lambda name: str(exe))
    assert found.found is True
    assert found.reason == "explicit_ok"


# ── untrusted registry validation ─────────────────────────────────────────


def test_parse_registry_accepts_real_shape():
    registry = reach.parse_registry(registry_payload())
    assert registry.schema_version == 1
    assert set(registry.channels) >= {"github", "v2ex", "twitter", "bilibili"}
    github = registry.channels["github"]
    assert github.login_via is None
    assert github.actions["search"].required_params[0].name == "query"
    assert github.actions["search"].optional_params[0].type == "int"


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p.update(schema_version=2), "schema_version"),
        (lambda p: p.update(schema_version=True), "schema_version"),
        (lambda p: p.update(ok=False), "ok=true"),
        (lambda p: p.update(channels=None), "channel list"),
        (lambda p: p.update(channels=[]), "channel list"),
        (lambda p: p["channels"].append(dict(p["channels"][0])), "duplicate channel"),
        (lambda p: p["channels"][0].update(name="Bad Name"), "invalid channel name"),
        (lambda p: p["channels"][0].update(name="github;rm -rf /"), "invalid channel name"),
        (lambda p: p["channels"][0].update(actions=[]), "no actions"),
        (lambda p: p["channels"][0].update(login={"via": "cookie"}), "login.via"),
        (lambda p: p["channels"][0].update(login={"via": "browser", "logged_in": "yes"}), "logged_in"),
        (lambda p: p["channels"][0]["actions"][0].update(params="query"), "params"),
        (lambda p: p["channels"][0]["actions"][0].update(public_web="x.com"), "public_web"),
        (lambda p: p["channels"][0]["actions"][0].update(public_web=["bad prefix"]), "public_web"),
        (lambda p: p["channels"][0]["actions"][0].update(backends=["ok", "bad label!"]), "backend label"),
        (lambda p: p["channels"][0]["actions"][0]["params"][0].update(required="yes"), "required"),
        (lambda p: p["channels"][0]["actions"][0]["params"][0].update(type="dict"), "type"),
        (lambda p: p["channels"][0]["actions"][0]["params"].append(dict(p["channels"][0]["actions"][0]["params"][0])), "duplicate param"),
    ],
)
def test_parse_registry_rejects_malformed_payloads(mutate, needle):
    payload = registry_payload()
    mutate(payload)
    with pytest.raises(reach.RegistryError) as excinfo:
        reach.parse_registry(payload)
    assert needle in str(excinfo.value)


def test_malformed_channels_output_never_spawns_an_action(backend_factory):
    backend, runner = backend_factory(action_response="this is not json")
    runner.payload = {"schema_version": 1, "ok": False, "channels": []}
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "registry_invalid"
    assert runner.action_calls == []


# ── allowlist / forbidden surface ─────────────────────────────────────────


def test_unknown_channel_and_action_are_rejected_without_spawning(backend_factory):
    backend, runner = backend_factory()
    unknown_channel = backend.execute("myspace", "search", {"query": "x"})
    assert unknown_channel.error["code"] == "unknown_channel"

    unknown_action = backend.execute("github", "delete", {"query": "x"})
    assert unknown_action.error["code"] == "unknown_action"
    assert runner.action_calls == []


@pytest.mark.parametrize("channel", ["login", "setup", "browser", "configure", "update", "uninstall", "skill", "read", "doctor"])
def test_management_verbs_are_rejected_as_channels(backend_factory, channel):
    backend, runner = backend_factory()
    result = backend.execute(channel, "search", {"query": "x"})
    assert result.ok is False
    assert result.error["code"] == "forbidden_command"
    assert runner.action_calls == []


def test_registry_action_outside_allowlist_is_rejected(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("rogue", "search", {"query": "x"})
    assert result.error["code"] == "action_not_allowlisted"
    assert runner.action_calls == []


def test_paid_transcription_is_never_run(backend_factory):
    backend, runner = backend_factory()
    for channel in ("youtube", "xiaoyuzhou"):
        result = backend.execute(channel, "transcribe", {"target": "abc"})
        assert result.ok is False
        assert result.error["code"] == "action_not_allowlisted"
    assert runner.action_calls == []


def test_allowlist_contains_no_mutating_actions():
    names = {a for actions in reach.READ_ONLY_ACTION_ALLOWLIST.values() for a in actions}
    assert names.isdisjoint(reach.FORBIDDEN_ACTIONS)
    assert "transcribe" not in names
    assert "xiaoyuzhou" not in reach.READ_ONLY_ACTION_ALLOWLIST


# ── public mode ───────────────────────────────────────────────────────────


def test_public_mode_forces_public_web_backend(backend_factory):
    backend, runner = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="public-web/exa", items=[])
    )
    result = backend.execute("twitter", "search", {"query": "rust lang", "limit": 2})
    assert result.ok is True
    argv = runner.action_calls[0]["argv"]
    assert argv[1:3] == ["twitter", "search"]
    assert ["--backend", "public-web"] == argv[argv.index("--backend"): argv.index("--backend") + 2]
    assert ["--limit", "2"] == argv[argv.index("--limit"): argv.index("--limit") + 2]
    assert argv[-2:] == ["--", "rust lang"]
    assert result.provenance["route"] == "public_web"
    assert result.provenance["forced_backend"] == "public-web"
    assert result.provenance["public_only"] is True


@pytest.mark.parametrize(
    "channel, action, params, label",
    [
        ("github", "search", {"query": "rust"}, "github-api"),
        ("github", "read", {"target": "owner/repo"}, "github-api"),
        ("v2ex", "hot", {"limit": 3}, "v2ex-api"),
        ("v2ex", "node", {"node_name": "python", "limit": 1}, "v2ex-api"),
        ("bilibili", "hot", {"limit": 1}, "bilibili-api"),
        ("bilibili", "read", {"target": "BV1xx411c7mD"}, "bilibili-api"),
        ("bilibili", "search", {"query": "rust", "limit": 1}, "bili-cli"),
        ("xueqiu", "quote", {"symbol": "SH600519"}, "tencent"),
        ("xueqiu", "search", {"query": "茅台", "limit": 1}, "tencent"),
    ],
)
def test_public_mode_forces_the_per_action_public_backend(
    backend_factory, channel, action, params, label
):
    """Public CN/API actions are reachable without consent via a pinned backend."""
    backend, runner = backend_factory()
    result = backend.execute(channel, action, params)
    assert result.ok is True, result.error
    argv = runner.action_calls[0]["argv"]
    assert argv[argv.index("--backend") + 1] == label
    assert result.provenance["route"] == "public_api"
    assert result.provenance["forced_backend"] == label
    assert result.provenance["public_only"] is True
    assert result.backend == label


def test_public_chinese_channels_need_no_login(backend_factory):
    """A declared session/browser login must not gate public actions."""
    backend, runner = backend_factory()
    for channel, action, params in (
        ("bilibili", "hot", {"limit": 1}),
        ("bilibili", "read", {"target": "BV1xx411c7mD"}),
        ("xueqiu", "quote", {"symbol": "SH600519"}),
    ):
        result = backend.execute(channel, action, params)
        assert result.ok is True, (channel, action, result.error)
    assert len(runner.action_calls) == 3
    assert all("--backend" in call["argv"] for call in runner.action_calls)


@pytest.mark.parametrize(
    "channel, action, params",
    [
        ("bilibili", "subtitle", {"target": "BV1xx411c7mD"}),
        ("xueqiu", "hot_posts", {"limit": 1}),
        ("xueqiu", "hot_stocks", {"limit": 1}),
        ("twitter", "profile", {"username": "nasa"}),
        ("instagram", "profile", {"username": "nasa"}),
    ],
)
def test_session_only_actions_require_explicit_consent(backend_factory, channel, action, params):
    backend, runner = backend_factory()
    result = backend.execute(channel, action, params)
    assert result.ok is False
    assert result.error["code"] == "auth_required"
    assert "allow_authenticated=True" in result.error["message"]
    assert result.provenance["route"] == "authenticated"
    assert result.provenance["forced_backend"] is None
    assert runner.action_calls == []


def test_authenticated_consent_runs_without_public_web(backend_factory):
    backend, runner = backend_factory(action_response=ok_envelope("bilibili", "subtitle", backend="bili-cli", items=[]))
    result = backend.execute("bilibili", "subtitle", {"target": "BV1xx411c7mD"}, allow_authenticated=True)
    assert result.ok is True
    argv = runner.action_calls[0]["argv"]
    assert "--backend" not in argv
    assert result.provenance["public_only"] is False
    assert result.provenance["home_mode"] == "operator"
    assert any("allow_authenticated=True" in line for line in result.limitations)


def test_consent_constructor_flag_also_allows_session_actions(backend_factory):
    backend, runner = backend_factory(
        action_response=ok_envelope("xueqiu", "hot_posts", backend="xueqiu-api", items=[]),
        allow_authenticated=True,
    )
    result = backend.execute("xueqiu", "hot_posts", {"limit": 1})
    assert result.ok is True
    assert result.provenance["public_only"] is False
    assert "--backend" not in runner.action_calls[0]["argv"]


# ── public mode runs blind (B1) ───────────────────────────────────────────


def test_public_mode_ignores_the_operator_home_and_home_override(backend_factory, tmp_path):
    op_home = tmp_path / "operator-home"
    (op_home / ".agent-reach").mkdir(parents=True)
    (op_home / ".agent-reach" / "config.yaml").write_text("xueqiu_cookie: secret\n")
    (op_home / ".config" / "gh").mkdir(parents=True)
    (op_home / ".config" / "gh" / "hosts.yml").write_text("oauth_token: secret\n")
    backend, runner = backend_factory(
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(op_home),
            "TRAILHEAD_AGENT_REACH_HOME": str(op_home),
            "XDG_CONFIG_HOME": str(op_home / ".config"),
            "GH_TOKEN": "secret",
        }
    )
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    for call in runner.calls:  # registry call and action call alike
        env = call["env"]
        home = env["HOME"]
        assert home != str(op_home)
        assert pathlib.Path(home).is_absolute()
        assert not str(home).startswith(str(op_home))
        assert env["USERPROFILE"] == home
        assert env["XDG_CONFIG_HOME"] != str(op_home / ".config")
        assert str(env["XDG_CONFIG_HOME"]).startswith(home)
        assert str(env["XDG_CACHE_HOME"]).startswith(home)
        assert str(env["XDG_DATA_HOME"]).startswith(home)
        assert str(env["XDG_STATE_HOME"]).startswith(home)
        assert "GH_TOKEN" not in env
    assert result.provenance["home_mode"] == "isolated-temp"
    assert reach.LIMITATION_PUBLIC_HOME in result.limitations


def test_public_home_is_empty_and_removed_after_the_call(backend_factory, tmp_path):
    observed = {}

    backend, runner = backend_factory(env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    original = runner.__call__

    def spying(argv, *, timeout, env):
        if list(argv)[1:2] != ["channels"]:
            observed["home"] = env["HOME"]
            observed["entries"] = sorted(os.listdir(env["HOME"]))
            observed["exists"] = os.path.isdir(env["HOME"])
        return original(argv, timeout=timeout, env=env)

    backend._runner = spying
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    assert observed["exists"] is True
    assert observed["entries"] == []  # fresh, no operator config copied in
    assert not os.path.exists(observed["home"])  # cleaned up on return


def test_public_home_is_cleaned_up_on_upstream_failure(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        "import os\n"
        "print(os.environ['HOME'], file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(str(exe), env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "malformed_output"
    reported_home = result.error["message"].rsplit(": ", 1)[-1].strip()
    assert reported_home.startswith(os.sep) and reported_home != str(tmp_path)
    assert result.provenance["home_mode"] == "isolated-temp"
    assert not os.path.exists(reported_home)


def test_authenticated_mode_uses_the_configured_home(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/usr/bin/env python3\n")
    exe.chmod(0o755)
    seen = {}

    def spy(argv, *, timeout, env):
        seen.update(env)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(ok_envelope("bilibili", "subtitle", backend="bili-cli", items=[])),
            stderr="",
        )

    backend = reach.AgentReachBackend(
        str(exe),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "op"), "TRAILHEAD_AGENT_REACH_HOME": str(tmp_path / "alt")},
        runner=spy,
        allow_authenticated=True,
    )
    backend.execute("bilibili", "subtitle", {"target": "BV1xx411c7mD"})
    assert seen["HOME"] == str(tmp_path / "alt")
    # the override isolates the whole config surface, not just HOME
    assert seen["XDG_CONFIG_HOME"] == str(tmp_path / "alt" / ".config")
    assert seen["USERPROFILE"] == str(tmp_path / "alt")


# ── forced-route verification (B2) ───────────────────────────────────────


def test_backend_mismatch_is_a_route_violation(backend_factory):
    """A payload from a different route must not be forwarded as success."""
    backend, runner = backend_factory(action_response=ok_envelope("v2ex", "hot", backend="opencli"))
    result = backend.execute("v2ex", "hot", {"limit": 2})
    assert result.ok is False
    assert result.error["code"] == "route_violation"
    assert "opencli" in result.error["message"] and "v2ex-api" in result.error["message"]
    assert result.items == ()
    assert result.provenance["forced_backend"] == "v2ex-api"
    assert result.provenance["reported_backend"] == "opencli"


def test_missing_reported_backend_on_a_forced_route_is_a_violation(backend_factory):
    envelope = ok_envelope("xueqiu", "quote", items=[])
    envelope["backend"] = None
    backend, _ = backend_factory(action_response=envelope)
    result = backend.execute("xueqiu", "quote", {"symbol": "SH600519"})
    assert result.ok is False
    assert result.error["code"] == "route_violation"
    assert result.items == ()


def test_public_web_route_accepts_its_own_sub_labels_only(backend_factory):
    backend, _ = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="public-web/exa", items=[])
    )
    assert backend.execute("twitter", "search", {"query": "rust"}).ok is True

    backend2, _ = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="opencli", items=[])
    )
    mismatch = backend2.execute("twitter", "search", {"query": "rust"})
    assert mismatch.ok is False
    assert mismatch.error["code"] == "route_violation"


def test_missing_declared_public_backend_is_not_silently_unforced(backend_factory):
    """If upstream renames its public backend, do not fall back to an unverified route."""
    payload = registry_payload()
    github = next(ch for ch in payload["channels"] if ch["name"] == "github")
    for action in github["actions"]:
        action["backends"] = ["gh"]
    backend, runner = backend_factory(payload)
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "auth_required"
    assert result.provenance["route"] == "authenticated"
    assert result.provenance["forced_backend"] is None
    assert runner.action_calls == []
    rows = {(r["channel"], r["action"]): r for r in backend.capabilities()}
    assert rows[("github", "search")]["public"] is False


def test_consented_calls_are_not_route_checked(backend_factory):
    """Without a pinned backend there is nothing to compare against."""
    backend, _ = backend_factory(
        action_response=ok_envelope("xueqiu", "hot_posts", backend="xueqiu-api", items=[]),
        allow_authenticated=True,
    )
    assert backend.execute("xueqiu", "hot_posts", {"limit": 1}).ok is True


# ── process safety ────────────────────────────────────────────────────────


def test_argument_array_has_no_shell_and_minimal_env(backend_factory, monkeypatch, tmp_path):
    backend, runner = backend_factory(env={"PATH": "/usr/bin:/bin", "HOME": "/home/op", "GROQ_API_KEY": "secret", "OPENAI_API_KEY": "secret"})
    backend.execute("github", "search", {"query": "rust"})
    call = runner.action_calls[0]
    assert isinstance(call["argv"], list)
    child_env = call["env"]
    assert "GROQ_API_KEY" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    # Public mode never hands the operator's home to the child.
    assert child_env["HOME"] != "/home/op"
    assert child_env["HOME"].startswith(tempfile.gettempdir())

    stub = tmp_path / "agent-reach"
    stub.write_text("#!/usr/bin/env python3\n")
    stub.chmod(0o755)
    seen = {}

    def spy(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=json.dumps(ok_envelope("github", "search")), stderr="")

    monkeypatch.setattr(reach.subprocess, "run", spy)
    direct = reach.AgentReachBackend(str(stub), env={"PATH": "/usr/bin:/bin"})
    direct.execute("github", "search", {"query": "rust"})
    assert isinstance(seen["argv"], list)
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["stdin"] is reach.subprocess.DEVNULL


@pytest.mark.parametrize(
    "value",
    [
        "--limit",
        "-rf",
        "query\n--backend public-web",
        "query\x00suffix",
        "tab\there",
    ],
)
def test_option_injection_and_control_chars_are_rejected(backend_factory, value):
    backend, runner = backend_factory()
    result = backend.execute("github", "search", {"query": value})
    assert result.ok is False
    assert result.error["code"] in {"unsafe_target", "invalid_params"}
    assert runner.action_calls == []


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
def test_dangerous_url_schemes_are_rejected(backend_factory, value):
    backend, runner = backend_factory()
    result = backend.execute("github", "read", {"target": value})
    assert result.ok is False
    assert result.error["code"] == "unsafe_target"
    assert runner.action_calls == []


def test_url_credentials_are_rejected_for_targets(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("github", "read", {"target": "https://user:pass@github.com/a/b"})
    assert result.error["code"] == "unsafe_target"
    assert runner.action_calls == []


def test_literal_identifiers_are_preserved(backend_factory):
    payload = registry_payload()
    payload["channels"][0]["actions"][1]["params"] = [_param("target", required=True)]
    backend, runner = backend_factory(payload)
    for target in ("owner/repo", "NousResearch/hermes-agent", "https://github.com/owner/repo/issues/42"):
        result = backend.execute("github", "read", {"target": target})
        assert result.ok is True
        assert runner.action_calls[-1]["argv"][-1] == target


def test_missing_unknown_and_out_of_bounds_params(backend_factory):
    backend, runner = backend_factory()
    assert backend.execute("github", "search", {}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "evil": "y"}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": 0}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": 500}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": "abc"}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, timeout=0.5).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, timeout=999).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, max_items="many").error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, max_items=0).error["code"] == "invalid_params"
    assert runner.action_calls == []


def test_build_argv_terminator_and_option_order():
    argv = reach.build_argv(
        "/bin/agent-reach",
        "github",
        "search",
        positionals=["my query"],
        options=[("limit", "2")],
        backend="public-web",
        timeout=12.5,
    )
    assert argv == [
        "/bin/agent-reach",
        "github",
        "search",
        "--limit",
        "2",
        "--backend",
        "public-web",
        "--timeout",
        "12.5",
        "--",
        "my query",
    ]
    no_positionals = reach.build_argv("/bin/agent-reach", "v2ex", "hot", options=[("limit", "1")], timeout=5)
    assert "--" not in no_positionals


# ── upstream failures ─────────────────────────────────────────────────────


def test_timeout_is_reported_without_partial_output(backend_factory):
    backend, runner = backend_factory(raise_timeout=True)
    result = backend.execute("github", "search", {"query": "rust"}, timeout=1)
    assert result.ok is False
    assert result.error["code"] == "timeout"
    assert result.timed_out is True
    assert result.items == ()
    assert result.provenance["engine"] == "agent-reach"


def test_real_executable_timeout_is_killed(tmp_path):
    exe = tmp_path / "agent-reach"
    payload = registry_payload()
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        f"PAYLOAD = {payload!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        "time.sleep(30)\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(
        str(exe),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=1,
    )
    backend.timeout_grace = 0.05
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "timeout"
    assert result.timed_out is True


def test_malformed_json_is_an_error(backend_factory):
    backend, _ = backend_factory(action_response="<html>not json</html>")
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "malformed_output"


def test_empty_stdout_and_non_object_payload(backend_factory):
    backend, _ = backend_factory(action_response="")
    assert backend.execute("github", "search", {"query": "rust"}).error["code"] == "malformed_output"

    backend2, _ = backend_factory(action_response="[]")
    assert backend2.execute("github", "search", {"query": "rust"}).error["code"] == "malformed_output"


def test_payload_without_ok_boolean_is_malformed(backend_factory):
    backend, _ = backend_factory(action_response={"channel": "github", "action": "search", "items": []})
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "malformed_output"


def test_upstream_error_envelope_is_forwarded_verbatim(backend_factory):
    backend, _ = backend_factory(
        action_response=error_envelope(
            "twitter", "search", code="UPSTREAM_BROKEN", message="Public web returned no usable content", hint="try the site tool"
        )
    )
    result = backend.execute("twitter", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "upstream_error"
    assert result.error["upstream_code"] == "UPSTREAM_BROKEN"
    assert "Public web returned no usable content" in result.error["message"]
    assert result.error["hint"] == "try the site tool"
    assert result.items == ()


def test_mismatched_channel_echo_is_malformed(backend_factory):
    backend, _ = backend_factory(action_response=ok_envelope("v2ex", "search"))
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "malformed_output"
    assert "reported channel" in result.error["message"]


def test_spawn_failure_is_a_process_error(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(str(exe), env={"PATH": "/usr/bin:/bin"})
    real_registry = backend.registry

    def registry_then_disable(refresh: bool = False):
        registry = real_registry(refresh=refresh)  # channels succeeds first
        exe.chmod(0o000)  # then the binary becomes unrunnable
        return registry

    backend.registry = registry_then_disable  # type: ignore[assignment]
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "process_error"


def test_uninstalled_backend_returns_not_configured():
    backend = reach.AgentReachBackend("/nonexistent/agent-reach")
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "not_configured"
    assert reach.AGENT_REACH_ENV in result.error["message"]


# ── provenance and item normalisation ─────────────────────────────────────


def test_provenance_pins_upstream_attribution(backend_factory):
    backend, _ = backend_factory()
    result = backend.execute("github", "search", {"query": "rust", "limit": 2})
    payload = result.to_dict()
    assert payload["engine"] == "agent-reach"
    assert payload["provenance"]["engine"] == "agent-reach"
    assert payload["provenance"]["native"] is False
    assert "Agent Reach" in payload["provenance"]["attribution"]
    assert payload["provenance"]["schema_version"] == 1
    assert payload["provenance"]["route"] == "public_api"
    assert payload["provenance"]["reported_backend"] == "github-api"
    assert payload["provenance"]["requested"] == "github search"
    assert payload["backend"] == "github-api"
    assert payload["attempts"][0] == {"backend": "gh", "result": "NEED_SETUP", "message": "no credentials"}
    assert any("third-party Agent Reach" in line for line in payload["limitations"])
    assert any("never installs" in line for line in payload["limitations"])


def test_items_are_normalised_and_bounded(backend_factory):
    long_text = "x" * (reach.MAX_TEXT_CHARS + 500)
    raw_items = [
        {
            "title": "ok",
            "url": "https://example.com/a",
            "author": "a",
            "published_at": "2026-01-01T00:00:00Z",
            "text": long_text,
            "raw": {"big": "y" * 5000},
        },
        {"title": "evil", "url": "javascript:alert(1)", "text": "nope"},
        {"title": "no url"},
        "not a dict",
    ]
    backend, _ = backend_factory(action_response=ok_envelope("github", "search", items=raw_items))
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    assert len(result.items) == 3
    first = result.items[0]
    assert first["text_truncated"] is True
    assert len(first["text"]) == reach.MAX_TEXT_CHARS
    assert first["raw"] is None
    assert result.items[1]["url"] is None
    assert result.items[1]["url_rejected"] is True
    assert any("not http(s)" in line for line in result.limitations)
    assert any("dropped" in line for line in result.limitations)


def test_respects_max_items(backend_factory):
    items = [{"title": str(i), "url": f"https://example.com/{i}"} for i in range(10)]
    backend, _ = backend_factory(action_response=ok_envelope("github", "search", items=items))
    result = backend.execute("github", "search", {"query": "rust"}, max_items=2)
    assert len(result.items) == 2
    assert any("kept the first 2" in line for line in result.limitations)


def test_error_results_still_carry_attribution(backend_factory):
    backend, _ = backend_factory()
    result = backend.execute("xueqiu", "hot_posts", {"limit": 1})
    assert result.error["code"] == "auth_required"
    assert result.provenance["engine"] == "agent-reach"
    assert result.provenance["native"] is False
    assert result.limitations[0] == reach.LIMITATION_FORWARDED


# ── registry caching / capability surface ─────────────────────────────────


def test_registry_is_cached_between_calls(backend_factory):
    backend, runner = backend_factory()
    backend.execute("github", "search", {"query": "one"})
    backend.execute("github", "search", {"query": "two"})
    channels_calls = [c for c in runner.calls if c["argv"][1:2] == ["channels"]]
    assert len(channels_calls) == 1
    assert len(runner.action_calls) == 2


def test_capabilities_mark_public_and_authenticated_routes(backend_factory):
    backend, _ = backend_factory()
    rows = {(r["channel"], r["action"]): r for r in backend.capabilities()}
    assert ("github", "search") in rows
    assert rows[("github", "search")]["mode"] == "public_api"
    assert rows[("github", "search")]["public"] is True
    assert rows[("github", "search")]["forced_backend"] == "github-api"
    assert rows[("v2ex", "hot")]["forced_backend"] == "v2ex-api"
    assert rows[("twitter", "search")]["mode"] == "public_web"
    assert rows[("twitter", "search")]["forced_backend"] == "public-web"
    assert rows[("twitter", "profile")]["mode"] == "authenticated"
    assert rows[("twitter", "profile")]["public"] is False
    # bilibili and xueqiu declare a login, but their public actions stay public.
    assert rows[("bilibili", "hot")]["public"] is True
    assert rows[("bilibili", "hot")]["forced_backend"] == "bilibili-api"
    assert rows[("bilibili", "read")]["forced_backend"] == "bilibili-api"
    assert rows[("bilibili", "subtitle")]["public"] is False
    assert rows[("xueqiu", "quote")]["forced_backend"] == "tencent"
    assert rows[("xueqiu", "search")]["public"] is True
    assert rows[("xueqiu", "hot_posts")]["public"] is False
    assert ("youtube", "transcribe") not in rows
    assert not any(row["channel"] == "xiaoyuzhou" for row in rows.values())


def test_describe_reports_missing_executable_without_raising():
    payload = reach.AgentReachBackend("/nonexistent/agent-reach").describe()
    assert payload["found"] is False
    assert payload["reason"] == "explicit_missing"
    assert payload["error"]["code"] == "not_configured"
    assert payload["capabilities"] == []
    assert payload["public_only"] is True


def test_describe_reports_registry_error(backend_factory):
    backend, runner = backend_factory()
    runner.payload = {"schema_version": 1, "ok": True, "channels": [{"name": "github"}]}
    payload = backend.describe()
    assert payload["found"] is True
    assert payload["error"]["code"] == "registry_invalid"
