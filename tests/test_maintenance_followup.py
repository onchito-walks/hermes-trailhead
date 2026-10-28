"""Maintenance follow-up regressions: parameter types, discovery reuse, budget.

Each test pins one item from ``docs/MAINTENANCE-REVIEW.md`` that was left open
when the first review closed F1–F6:

* **F7** — a declared ``bool``/``float`` parameter was routed through the
  string validator, so ``True``/``3.5`` came back as "must be a string".  The
  declared type is now coerced explicitly, non-finite numbers are rejected, and
  the ``str``/``int`` policy is unchanged.
* **F9** — every fallback invocation built a fresh adapter, and every adapter
  ran ``agent-reach channels`` on first use, so a five-lane sweep spent five
  discovery subprocesses before any search.  The parsed inventory is now cached
  process-wide by configuration identity; adapters (and therefore consent
  flags, HOME mode and item budgets) stay per instance.
* **F10** — ``registry()`` used a fixed ``timeout_grace + 30`` budget no matter
  what ``timeout`` the caller asked for, so a slow discovery read could outlive
  the whole action.  Discovery now shares the action's wall clock, and the
  action gets what discovery left (with the runner grace preserved).

Everything is local: a stub executable and an injected runner.  No network, no
credentials, no paid calls.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import time
from types import SimpleNamespace

import pytest

from hermes_trailhead import backends
from hermes_trailhead import reach_backend as reach


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_registry_cache():
    """Every test starts and ends with an empty process-wide cache."""
    reach.clear_registry_cache()
    yield
    reach.clear_registry_cache()


def typed_registry_payload() -> dict:
    """``web search`` with one optional param of each declared type."""
    return {
        "schema_version": 1,
        "ok": True,
        "channels": [
            {
                "name": "web",
                "description": "web",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "search",
                        "params": [
                            {"name": "query", "help": "", "required": True, "type": "str"},
                            {"name": "limit", "help": "", "required": False, "type": "int"},
                            {"name": "exact", "help": "", "required": False, "type": "bool"},
                            {"name": "weight", "help": "", "required": False, "type": "float"},
                        ],
                        "backends": ["jina"],
                        "public_web": ["example.com/"],
                    },
                ],
            }
        ],
    }


def sweep_registry_payload() -> dict:
    """The five channels the search fallback routes to."""
    channels = []
    for name in ("web", "github", "reddit", "twitter", "youtube"):
        channels.append(
            {
                "name": name,
                "description": name,
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "search",
                        "params": [
                            {"name": "query", "help": "", "required": True, "type": "str"},
                            {"name": "limit", "help": "", "required": False, "type": "int"},
                        ],
                        "backends": ["jina"],
                        "public_web": ["example.com/"],
                    }
                ],
            }
        )
    return {"schema_version": 1, "ok": True, "channels": channels}


def ok_envelope(channel: str = "web", action: str = "search") -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": "public-web",
        "items": [{"title": "lead", "url": "https://example.com/lead", "text": "snippet"}],
        "meta": {"elapsed_ms": 5},
        "error": None,
    }


def stub_executable(directory: pathlib.Path, name: str = "agent-reach") -> str:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return str(path)


class RecordingRunner:
    """Replays registry/action payloads, records argv + requested timeouts.

    ``slow_channels``/``slow_action`` emulate ``_default_runner`` faithfully: a
    delay longer than the requested ``timeout`` raises ``TimeoutExpired`` after
    waiting exactly that timeout, instead of finishing and pretending.
    """

    def __init__(
        self,
        registry: dict | None = None,
        response: dict | None = None,
        *,
        slow_channels: float = 0.0,
        slow_action: float = 0.0,
        channels_stdout: list[str] | None = None,
    ) -> None:
        self.registry = typed_registry_payload() if registry is None else registry
        self.response = ok_envelope() if response is None else response
        self.slow_channels = slow_channels
        self.slow_action = slow_action
        self.channels_stdout = list(channels_stdout or [])
        self.calls: list[dict] = []

    def __call__(self, argv, *, timeout, env):
        argv = list(argv)
        kind = "channels" if argv[1:2] == ["channels"] else "action"
        self.calls.append({"kind": kind, "argv": argv, "timeout": timeout})
        delay = self.slow_channels if kind == "channels" else self.slow_action
        if delay > timeout:
            time.sleep(max(timeout, 0.0))
            raise subprocess.TimeoutExpired(argv, timeout)
        if delay:
            time.sleep(delay)
        if kind == "channels":
            body = (
                self.channels_stdout.pop(0)
                if self.channels_stdout
                else json.dumps(self.registry)
            )
        else:
            body = json.dumps(self.response)
        return SimpleNamespace(returncode=0, stdout=body, stderr="")

    @property
    def channels_calls(self) -> list[dict]:
        return [call for call in self.calls if call["kind"] == "channels"]

    @property
    def action_calls(self) -> list[dict]:
        return [call for call in self.calls if call["kind"] == "action"]

    def option(self, name: str) -> str | None:
        """The value forwarded for ``--name`` on the last action call."""
        argv = self.action_calls[-1]["argv"]
        return argv[argv.index(f"--{name}") + 1] if f"--{name}" in argv else None


@pytest.fixture()
def make_backend(tmp_path):
    stub = stub_executable(tmp_path)

    def make(runner=None, *, registry=None, response=None, executable=None, **kwargs):
        runner = runner or RecordingRunner(registry, response)
        backend = reach.AgentReachBackend(
            executable or stub, runner=runner, env={}, **kwargs
        )
        return backend, runner

    return make


# ── F7: declared bool / float parameters ──────────────────────────────────


@pytest.mark.parametrize(("value", "forwarded"), [(True, "true"), (False, "false")])
def test_bool_param_accepts_native_booleans(make_backend, value, forwarded):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "exact": value})

    assert result.ok is True
    assert runner.option("exact") == forwarded


@pytest.mark.parametrize(
    ("value", "forwarded"),
    [("TRUE", "true"), ("false", "false"), ("1", "true"), ("0", "false"), (" no ", "false")],
)
def test_bool_param_accepts_documented_string_spellings(make_backend, value, forwarded):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "exact": value})

    assert result.ok is True
    assert runner.option("exact") == forwarded


@pytest.mark.parametrize("value", [1, 0, 1.0, "maybe", [], {"a": 1}])
def test_bool_param_rejects_truthy_non_booleans(make_backend, value):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "exact": value})

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert "must be a boolean" in result.error["message"]
    assert runner.action_calls == []


@pytest.mark.parametrize(
    ("value", "forwarded"),
    [(3.5, "3.5"), (3, "3"), ("0.25", "0.25"), ("-1.5", "-1.5"), (1e-7, "1e-07")],
)
def test_float_param_accepts_finite_numbers(make_backend, value, forwarded):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "weight": value})

    assert result.ok is True
    assert runner.option("weight") == forwarded


@pytest.mark.parametrize(
    "value",
    [float("inf"), float("-inf"), float("nan"), "inf", "-Infinity", "nan", "1e999"],
)
def test_float_param_rejects_non_finite_values(make_backend, value):
    """Non-finite input is an ``invalid_params`` result, never a forwarded token."""
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "weight": value})

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert "finite" in result.error["message"]
    assert runner.action_calls == []


@pytest.mark.parametrize("value", [True, False, "abc", "1_000", "0x10", "", "  ", None.__class__])
def test_float_param_rejects_non_numbers(make_backend, value):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "weight": value})

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert runner.action_calls == []


def test_float_param_is_bounded(make_backend):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "q", "weight": 1e13})

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert "out of bounds" in result.error["message"]


@pytest.mark.parametrize(
    ("params", "needle"),
    [
        ({"query": True}, "must be a string"),
        ({"query": 12}, "must be a string"),
        ({"query": "q", "limit": 3.5}, "must be an integer"),
        ({"query": "q", "limit": True}, "must be an integer"),
        ({"query": "q", "limit": "many"}, "must be an integer"),
    ],
)
def test_str_and_int_policy_is_unchanged(make_backend, params, needle):
    """Explicit coercion for bool/float must not loosen str/int."""
    backend, runner = make_backend()

    result = backend.execute("web", "search", params)

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert needle in result.error["message"]
    assert runner.action_calls == []


def test_str_and_int_happy_path_is_unchanged(make_backend):
    backend, runner = make_backend()

    result = backend.execute("web", "search", {"query": "  rust  ", "limit": "7"})

    assert result.ok is True
    assert runner.action_calls[-1]["argv"][-1] == "  rust  "
    assert runner.option("limit") == "7"


def test_required_bool_and_float_are_forwarded_after_the_terminator(make_backend):
    """A required param is positional; a negative float is still safe after ``--``."""
    registry = typed_registry_payload()
    registry["channels"][0]["actions"][0]["params"] = [
        {"name": "query", "help": "", "required": True, "type": "str"},
        {"name": "exact", "help": "", "required": True, "type": "bool"},
        {"name": "weight", "help": "", "required": True, "type": "float"},
    ]
    backend, runner = make_backend(registry=registry)

    result = backend.execute("web", "search", {"query": "q", "exact": True, "weight": -2.5})

    assert result.ok is True
    argv = runner.action_calls[-1]["argv"]
    assert argv[argv.index("--") + 1:] == ["q", "true", "-2.5"]


# ── F9: one discovery read per configuration, not per adapter ─────────────


def test_five_lane_fallback_sweep_discovers_channels_once(monkeypatch, tmp_path):
    """The measured defect: 5 lanes → 5 ``channels`` subprocesses. Now 1."""
    monkeypatch.setenv(reach.AGENT_REACH_ENV, stub_executable(tmp_path))
    runner = RecordingRunner(sweep_registry_payload())
    monkeypatch.setattr(reach, "_default_runner", runner)

    lanes = ["web", "github", "reddit", "x", "youtube"]
    results = [backends.run_reach_search_fallback(lane, "q", limit=3) for lane in lanes]

    assert all(result is not None for result in results)
    assert len(runner.channels_calls) == 1
    assert len(runner.action_calls) == len(lanes)


def test_discovery_is_shared_across_adapter_instances(make_backend):
    first, runner = make_backend()
    second = reach.AgentReachBackend(
        first.availability().path, runner=runner, env={}
    )

    assert first.registry() is second.registry()
    assert len(runner.channels_calls) == 1


def test_public_and_authenticated_discovery_are_not_shared(make_backend):
    """A public call must never read the inventory an authenticated read built."""
    public, runner = make_backend()
    authenticated = reach.AgentReachBackend(
        public.availability().path, runner=runner, env={}, allow_authenticated=True
    )

    public.registry()
    authenticated.registry()

    assert len(runner.channels_calls) == 2


def test_a_different_env_identity_is_a_different_cache_entry(make_backend, tmp_path):
    first, runner = make_backend()
    same_env = reach.AgentReachBackend(first.availability().path, runner=runner, env={})
    other_env = reach.AgentReachBackend(
        first.availability().path, runner=runner, env={"HOME": str(tmp_path)}
    )

    first.registry()
    same_env.registry()
    assert len(runner.channels_calls) == 1

    other_env.registry()
    assert len(runner.channels_calls) == 2


def test_refresh_bypasses_the_process_cache(make_backend):
    backend, runner = make_backend()

    backend.registry()
    backend.registry()
    assert len(runner.channels_calls) == 1

    backend.registry(refresh=True)
    assert len(runner.channels_calls) == 2


def test_failed_discovery_is_not_cached(make_backend):
    runner = RecordingRunner(channels_stdout=["not json", json.dumps(typed_registry_payload())])
    backend, _ = make_backend(runner)

    with pytest.raises(reach.RegistryError):
        backend.registry()
    registry = backend.registry()

    assert registry.schema_version == 1
    assert len(runner.channels_calls) == 2


def test_registry_cache_is_bounded(tmp_path, make_backend):
    """A long-lived process cannot accumulate one entry per executable seen."""
    runners = []
    for index in range(reach.REGISTRY_CACHE_ENTRIES + 3):
        runner = RecordingRunner()
        backend = reach.AgentReachBackend(
            stub_executable(tmp_path, f"agent-reach-{index}"), runner=runner, env={}
        )
        backend.registry()
        runners.append(runner)

    assert len(reach._REGISTRY_CACHE) == reach.REGISTRY_CACHE_ENTRIES
    assert all(len(runner.channels_calls) == 1 for runner in runners)


def test_cache_key_does_not_carry_credential_shaped_config():
    key = reach.registry_cache_key(
        "/usr/local/bin/agent-reach",
        public=False,
        env={"GITHUB_TOKEN": "ghp_secret_value"},
        runner=None,
    )

    assert "ghp_secret_value" not in repr(key)
    assert "GITHUB_TOKEN" not in repr(key)


# ── F10: discovery shares the action's wall clock ─────────────────────────


def test_discovery_budget_never_exceeds_the_call_deadline(make_backend):
    """Measured before: a 2 s discovery read finished inside a 1.2 s deadline."""
    runner = RecordingRunner(slow_channels=2.0)
    backend, _ = make_backend(runner, timeout=1)
    backend.timeout_grace = 0.2
    deadline = 1.0 + backend.timeout_grace

    started = time.monotonic()
    result = backend.execute("web", "search", {"query": "q"})
    elapsed = time.monotonic() - started

    assert result.error["code"] == "timeout"
    assert result.timed_out is True
    assert runner.channels_calls[0]["timeout"] <= deadline
    assert runner.action_calls == []
    assert elapsed <= deadline + 0.35, f"the call outlived its deadline by {elapsed - deadline:.2f}s"


def test_action_keeps_the_runner_grace_after_a_fast_discovery(make_backend):
    runner = RecordingRunner(slow_channels=0.01)
    backend, _ = make_backend(runner, timeout=1)
    backend.timeout_grace = 0.2

    assert backend.execute("web", "search", {"query": "q"}).ok is True

    action_timeout = runner.action_calls[0]["timeout"]
    assert 1.0 <= action_timeout <= 1.0 + backend.timeout_grace


def test_registry_read_outside_a_call_keeps_its_own_ceiling(make_backend):
    backend, runner = make_backend()

    backend.registry()

    assert runner.channels_calls[0]["timeout"] == pytest.approx(
        backend.timeout_grace + reach.REGISTRY_DISCOVERY_BUDGET
    )


def test_discovery_is_not_spawned_after_the_deadline_is_spent(make_backend):
    backend, runner = make_backend()

    with pytest.raises(reach.RegistryError) as excinfo:
        backend._registry_for_action(time.monotonic() - 1.0)

    assert "wall-clock budget" in str(excinfo.value)
    assert runner.calls == []
    assert backend._call_deadline is None
