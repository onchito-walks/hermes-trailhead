"""Contract tests for the optional Agent Reach *search* fallback.

The fallback is the normal research path, not a demo: when every native/free
backend for a lane produces nothing, an explicitly configured Agent Reach CLI
may supply public read-only search leads — attributed, bounded, and never
allowed to affect the lanes that already worked.

Everything here is deterministic: fixtures stand in for HTTP, and a fake
adapter stands in for the upstream CLI.  No test reads a real credential, no
test spawns ``agent-reach``, and no test contacts the network.
"""
from __future__ import annotations

import urllib.request

import pytest

from hermes_trailhead import backends
from hermes_trailhead import search as search_mod
from hermes_trailhead.backends import (
    REACH_SEARCH_ROUTES,
    REACH_SNIPPET_CHARS,
    build_reach_search_adapter,
    configured_reach_executable,
    execute_backend_chain,
    run_reach_search_fallback,
)
from hermes_trailhead.reach_backend import AGENT_REACH_ENV, AgentReachBackend, ReachResult
from hermes_trailhead.search import execute_search

ATTRIBUTION = "Agent Reach (third-party CLI), forwarded by Hermes Trailhead"
QUERY = "url shortener"


# ── fixtures / fakes ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """No operator env, no circuit-breaker disk state, no PATH surprises."""
    monkeypatch.delenv(AGENT_REACH_ENV, raising=False)
    monkeypatch.setattr(backends, "_circuit_open", lambda name, path=None: False)
    monkeypatch.setattr(backends, "_record_circuit_failure", lambda name, path=None: None)
    monkeypatch.setattr(backends, "_reset_circuit", lambda name, path=None: None)
    monkeypatch.setattr(backends.shutil, "which", lambda command: None)


class _FakeAdapter:
    """Duck-typed stand-in for ``AgentReachBackend``."""

    def __init__(self, result=None, *, raises: Exception | None = None):
        self.result = result
        self.raises = raises
        self.calls: list[dict] = []

    def execute(self, channel, action, params=None, **_ignored):
        self.calls.append({"channel": channel, "action": action, "params": dict(params or {})})
        if self.raises is not None:
            raise self.raises
        return self.result


def _reach_result(
    items=(),
    *,
    ok: bool = True,
    error=None,
    backend: str | None = "public-web",
    route: str | None = "public_web",
    public_only: bool = True,
    attribution: str = ATTRIBUTION,
    attempts=(),
) -> ReachResult:
    return ReachResult(
        ok=ok,
        channel="web",
        action="search",
        backend=backend,
        items=tuple(items),
        error=error,
        provenance={
            "engine": "agent-reach",
            "native": False,
            "attribution": attribution,
            "public_only": public_only,
            "route": route,
        },
        attempts=tuple(attempts),
    )


def _item(url, title="A result", text=""):
    return {"title": title, "url": url, "text": text, "author": None, "published_at": None}


def _empty_fetch(url, timeout):
    return ""


def _html_fetch(url, timeout):
    return '<a href="https://example.com/native-lead">Native lead</a>'


class _EmptyResponse:
    """Minimal ``urlopen`` result: a successful, empty HTTP response."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return b""


# ── 1. native success wins, fallback never spawns ─────────────────────────


def test_native_chain_success_never_consults_the_reach_adapter():
    adapter = _FakeAdapter(_reach_result([_item("https://example.com/from-reach")]))

    result = execute_backend_chain(
        "web", QUERY, limit=2, fetch=_html_fetch, reach_adapter=adapter
    )

    assert adapter.calls == []
    assert [hit.url for hit in result.hits] == ["https://example.com/native-lead"]
    assert not result.engine.startswith("agent_reach")
    assert result.attribution == ""
    assert not any(name.startswith("agent_reach") for name in result.attempts)


# ── 2. unconfigured / PATH-only means no fallback ─────────────────────────


def test_unconfigured_fallback_is_skipped_entirely():
    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch)

    assert result.hits == ()
    assert not any(name.startswith("agent_reach") for name in result.attempts)
    assert result.engine in {backend.name for backend in backends.BACKENDS["web"]}
    assert "agent-reach" not in result.error.lower()


def test_agent_reach_on_path_is_not_configuration(monkeypatch, tmp_path):
    binary = tmp_path / "agent-reach"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert configured_reach_executable() is None

    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch)
    assert not any(name.startswith("agent_reach") for name in result.attempts)


def test_configured_executable_is_read_only_from_the_explicit_variable(monkeypatch):
    monkeypatch.setenv(AGENT_REACH_ENV, "  /opt/agent-reach/bin/agent-reach  ")
    assert configured_reach_executable() == "/opt/agent-reach/bin/agent-reach"

    monkeypatch.delenv(AGENT_REACH_ENV)
    assert configured_reach_executable({}) is None
    assert configured_reach_executable({"PATH": "/usr/bin"}) is None


# ── 3. configured fallback runs, attributed ──────────────────────────────


def test_configured_fallback_is_used_after_the_free_chain_is_exhausted(monkeypatch):
    adapter = _FakeAdapter(
        _reach_result(
            [_item("https://example.com/reach-lead", text="short lead")],
            backend="exa",
            route="public_api",
            attempts=[{"backend": "exa", "result": "ok", "message": None}],
        )
    )
    built: list[tuple[str, int]] = []

    def factory(executable, *, limit=5):
        built.append((executable, limit))
        return adapter

    monkeypatch.setenv(AGENT_REACH_ENV, "/opt/agent-reach/bin/agent-reach")
    monkeypatch.setattr(backends, "build_reach_search_adapter", factory)
    # No injected fetch: the chain uses the patched HTTP layer, which is empty.
    monkeypatch.setattr(backends, "_fetch", _empty_fetch)

    result = execute_backend_chain("web", QUERY, limit=3)

    assert built == [("/opt/agent-reach/bin/agent-reach", 3)]
    assert adapter.calls == [{"channel": "web", "action": "search", "params": {"query": QUERY, "limit": 3}}]
    assert [hit.url for hit in result.hits] == ["https://example.com/reach-lead"]
    assert result.engine == "agent_reach_web_search"
    assert result.attempts[-1] == "agent_reach_web_search:exa/ok"
    assert "agent_reach_web_search" in result.attempts
    assert result.attribution == ATTRIBUTION
    assert result.error == ""


def test_adapter_is_built_public_only_and_bounded(tmp_path):
    binary = tmp_path / "agent-reach"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    adapter = build_reach_search_adapter(str(binary), limit=3)

    assert isinstance(adapter, AgentReachBackend)
    # Public read-only only: no consent path exists from a search run.
    assert adapter._allow_authenticated is False
    assert adapter._timeout == backends.REACH_SEARCH_TIMEOUT
    assert adapter._max_items == 3
    assert adapter._explicit == str(binary)


def test_x_lane_maps_to_twitter_search_and_keeps_only_lane_urls():
    adapter = _FakeAdapter(
        _reach_result(
            [
                _item("https://x.com/nousresearch/status/123", title="Hermes post", text="t" * 1000),
                _item("https://x.com/search?q=hermes"),
                _item("https://example.com/off-lane"),
                _item("javascript:alert(1)"),
                _item("https://x.com/nousresearch"),
            ],
            backend="public-web",
        )
    )

    result = execute_backend_chain("x", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)

    assert adapter.calls[0]["channel"] == "twitter"
    assert adapter.calls[0]["action"] == "search"
    assert [hit.url for hit in result.hits] == [
        "https://x.com/nousresearch/status/123",
        "https://x.com/nousresearch",
    ]
    assert result.engine == "agent_reach_twitter_search"
    # A forwarded snippet is a lead, never an extraction.
    assert len(result.hits[0].snippet) == REACH_SNIPPET_CHARS
    assert not hasattr(result.hits[0], "content")
    assert result.attribution == ATTRIBUTION


@pytest.mark.parametrize(
    "platform,channel,action",
    [
        ("web", "web", "search"),
        ("github", "github", "search"),
        ("reddit", "reddit", "search"),
        ("x", "twitter", "search"),
        ("youtube", "youtube", "search"),
    ],
)
def test_supported_lanes_map_to_public_upstream_search(platform, channel, action):
    assert REACH_SEARCH_ROUTES[platform] == (channel, action)

    adapter = _FakeAdapter(_reach_result([]))
    run_reach_search_fallback(platform, QUERY, limit=2, adapter=adapter)

    assert (adapter.calls[0]["channel"], adapter.calls[0]["action"]) == (channel, action)
    assert adapter.calls[0]["params"]["query"] == QUERY


def test_lanes_without_a_public_upstream_search_route_are_not_mapped():
    spy = _FakeAdapter(_reach_result([_item("https://www.instagram.com/p/abc/")]))

    for platform in ("tiktok", "instagram", "unknown"):
        assert run_reach_search_fallback(platform, QUERY, adapter=spy) is None

    result = execute_backend_chain(
        "instagram", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=spy
    )
    assert spy.calls == []
    assert not any(name.startswith("agent_reach") for name in result.attempts)


# ── 4. public/no-auth/no-quota gate ──────────────────────────────────────


def test_result_without_a_public_route_is_refused():
    adapter = _FakeAdapter(
        _reach_result(
            [_item("https://example.com/leak")],
            route="authenticated",
            public_only=False,
        )
    )

    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)

    assert result.hits == ()
    assert "auth_gate" in result.error
    assert "authenticated forwarding is never enabled" in result.error
    assert any(name.endswith("_auth_gate") for name in result.attempts)


def test_missing_public_only_flag_is_refused_as_well():
    payload = ReachResult(
        ok=True,
        channel="web",
        action="search",
        backend="exa",
        items=(_item("https://example.com/leak"),),
        provenance={"engine": "agent-reach"},
    )

    result = run_reach_search_fallback("web", QUERY, adapter=_FakeAdapter(payload))

    assert result is not None
    assert result.hits == ()
    assert "auth_gate" in result.error


def test_only_read_only_search_actions_are_reachable():
    # Mapping is search-only by construction; transcription and management
    # verbs cannot be named from a search run.
    actions = {action for _channel, action in REACH_SEARCH_ROUTES.values()}
    assert actions == {"search"}
    channels = {channel for channel, _action in REACH_SEARCH_ROUTES.values()}

    from hermes_trailhead.reach_backend import READ_ONLY_ACTION_ALLOWLIST

    for channel in channels:
        assert "search" in READ_ONLY_ACTION_ALLOWLIST[channel]
        assert "transcribe" not in READ_ONLY_ACTION_ALLOWLIST.get(channel, frozenset())


# ── 5. errors are recorded, actionable, and non-fatal ────────────────────


def test_malformed_upstream_payload_is_recorded_not_raised():
    adapter = _FakeAdapter(
        _reach_result(
            ok=False,
            error={"code": "malformed_output", "message": "agent-reach returned malformed JSON"},
        )
    )

    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)

    assert result.hits == ()
    assert "malformed_output" in result.error
    assert "malformed JSON" in result.error
    assert "agent_reach_web_search_malformed_output" in result.attempts
    # The empty result is diagnosed, not credited to the upstream tool.
    assert not result.engine.startswith("agent_reach")
    assert not result.error.startswith("optional agent-reach fallback")
    assert result.attribution == ""


def test_blocked_upstream_error_keeps_code_and_hint():
    adapter = _FakeAdapter(
        _reach_result(
            ok=False,
            error={
                "code": "upstream_error",
                "upstream_code": "UPSTREAM_BROKEN",
                "message": "Public web returned no usable content",
                "hint": "retry later or use a different backend",
            },
        )
    )

    fallback = run_reach_search_fallback("web", QUERY, adapter=adapter)

    assert fallback is not None
    assert fallback.hits == ()
    assert "upstream_error" in fallback.error
    assert "Public web returned no usable content" in fallback.error
    assert "UPSTREAM_BROKEN" in fallback.error
    assert "retry later or use a different backend" in fallback.error


def test_missing_executable_error_names_the_variable(monkeypatch, tmp_path):
    monkeypatch.setenv(AGENT_REACH_ENV, str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(backends, "_fetch", _empty_fetch)

    result = execute_backend_chain("web", QUERY, limit=2)

    assert result.hits == ()
    assert "not_configured" in result.error
    assert AGENT_REACH_ENV in result.error
    assert any(name.endswith("_not_configured") for name in result.attempts)


def test_broken_adapter_cannot_crater_the_lane():
    adapter = _FakeAdapter(raises=RuntimeError("boom"))

    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)

    assert result.hits == ()
    assert "adapter_error" in result.error
    assert "RuntimeError" in result.error
    assert "boom" in result.error


def test_ok_payload_with_no_usable_urls_reports_honestly():
    adapter = _FakeAdapter(
        _reach_result(
            [
                _item("https://example.com/off-lane"),
                {"title": "no url", "url": None, "text": "x"},
            ]
        )
    )

    result = execute_backend_chain("github", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)

    assert result.hits == ()
    assert result.saw_response is True
    assert "none matched" in result.error
    assert not result.engine.startswith("agent_reach")
    assert any(name.endswith("_no_matching_urls") for name in result.attempts)


# ── 6. determinism: injected fixtures never reach it by accident ──────────


def test_injected_fetch_does_not_trigger_the_fallback(monkeypatch):
    spy = _FakeAdapter(_reach_result([_item("https://example.com/reach")]))
    monkeypatch.setenv(AGENT_REACH_ENV, "/opt/agent-reach/bin/agent-reach")

    result = execute_backend_chain("web", QUERY, limit=2, fetch=_empty_fetch)

    assert spy.calls == []
    assert not any(name.startswith("agent_reach") for name in result.attempts)

    # Even an explicit native opt-in does not open the fallback while a fixture
    # is standing in for the network.
    result = execute_backend_chain(
        "web", QUERY, limit=2, fetch=_empty_fetch, allow_native=True
    )
    assert not any(name.startswith("agent_reach") for name in result.attempts)

    # Explicitly injecting an adapter is the only way a fixture-driven run
    # exercises the fallback, and then it does.
    result = execute_backend_chain(
        "web", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=spy
    )
    assert spy.calls and result.engine == "agent_reach_web_search"


def test_allow_reach_is_the_explicit_signal_for_a_real_fetcher(monkeypatch):
    """The production call shape: non-None fetch plus explicit allow_reach.

    ``execute_action`` always hands the chain a fetcher, so the chain cannot
    infer "real runtime" from ``fetch is None``.  The trusted signal is passed
    in explicitly; the fixture-fetch default stays closed.
    """
    adapter = _FakeAdapter(_reach_result([_item("https://example.com/reach")]))
    monkeypatch.setenv(AGENT_REACH_ENV, "/opt/agent-reach/bin/agent-reach")
    monkeypatch.setattr(backends, "build_reach_search_adapter", lambda executable, *, limit=5: adapter)

    result = execute_backend_chain(
        "web", QUERY, limit=2, fetch=_empty_fetch, allow_native=True, allow_reach=True
    )

    assert result.engine == "agent_reach_web_search"
    assert [hit.url for hit in result.hits] == ["https://example.com/reach"]


# ── 7. search execution surface ──────────────────────────────────────────


def test_execute_search_surfaces_engine_attempts_and_attribution():
    adapter = _FakeAdapter(
        _reach_result([_item("https://example.com/reach-lead", title="Reach lead", text="lead text")])
    )

    executed = execute_search("web", QUERY, limit=2, fetch=_empty_fetch, reach_adapter=adapter)
    execution = executed.executions[0]
    payload = execution.to_dict()

    assert execution.status == "ok"
    assert execution.result_count == 1
    assert execution.engine == "agent_reach_web_search"
    assert execution.attempts
    assert "agent_reach_web_search" in execution.attempts
    assert execution.attempts[-1].startswith("agent_reach_web_search")
    assert execution.attribution == ATTRIBUTION
    assert execution.hits[0].query == QUERY
    assert payload["attempts"] == list(execution.attempts)
    assert payload["attribution"] == ATTRIBUTION
    assert payload["hits"][0]["snippet"] == "lead text"


def test_execute_search_without_configuration_is_unchanged():
    executed = execute_search("web", QUERY, limit=2, fetch=_empty_fetch)
    execution = executed.executions[0]

    assert execution.engine != "agent_reach_web_search"
    assert execution.attribution == ""
    assert execution.attempts
    assert not any(name.startswith("agent_reach") for name in execution.attempts)


def test_execute_search_default_runtime_reaches_a_configured_fallback(monkeypatch):
    """Regression: the CLI-shaped call passes a fetcher, not ``fetch=None``.

    ``execute_action`` always builds the fetcher and hands it to the chain, so
    a fallback gate keyed only on ``fetch is None`` could never fire in
    production.  The adapter is not injected here: the operator env plus the
    mocked factory are the only knobs, and HTTP is an empty success.
    """
    adapter = _FakeAdapter(
        _reach_result(
            [_item("https://example.com/reach-lead", title="Reach lead", text="lead text")]
        )
    )
    built: list[tuple[str, int]] = []

    def factory(executable, *, limit=5):
        built.append((executable, limit))
        return adapter

    monkeypatch.setenv(AGENT_REACH_ENV, "/opt/agent-reach/bin/agent-reach")
    monkeypatch.setattr(backends, "build_reach_search_adapter", factory)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: _EmptyResponse())

    executed = execute_search("web", QUERY, limit=2)
    execution = executed.executions[0]

    assert built == [("/opt/agent-reach/bin/agent-reach", 2)]
    assert execution.status == "ok"
    assert execution.engine == "agent_reach_web_search"
    assert execution.result_count == 1
    assert execution.hits[0].url == "https://example.com/reach-lead"
    assert execution.hits[0].query == QUERY
    assert execution.attribution == ATTRIBUTION
    assert execution.to_dict()["attribution"] == ATTRIBUTION
    assert "agent_reach_web_search" in execution.attempts


def test_execute_search_patched_default_fetcher_keeps_the_fallback_closed(monkeypatch):
    """A patched module fetcher is a fixture: no native path, no fallback.

    This is the fixture-surprise guard behind ``trusted_runtime``: replacing
    ``search._fetch_text`` must never silently open the third-party CLI.
    """
    built: list[tuple[str, int]] = []

    def factory(executable, *, limit=5):
        built.append((executable, limit))
        return _FakeAdapter(_reach_result([_item("https://example.com/reach-lead")]))

    monkeypatch.setenv(AGENT_REACH_ENV, "/opt/agent-reach/bin/agent-reach")
    monkeypatch.setattr(backends, "build_reach_search_adapter", factory)
    monkeypatch.setattr(search_mod, "_fetch_text", _empty_fetch)

    executed = execute_search("web", QUERY, limit=2)
    execution = executed.executions[0]

    assert built == []
    assert execution.engine != "agent_reach_web_search"
    assert execution.attribution == ""
    assert not any(name.startswith("agent_reach") for name in execution.attempts)
