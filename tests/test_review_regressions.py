"""Independent review regressions: bounds, killability, and honest limits.

Each test here pins a defect found by reviewing the uncommitted forwarding and
extraction work, not a behaviour the original change intended:

* ``max_items=float("inf")`` escaped ``execute()`` as an ``OverflowError``
  instead of the documented machine-readable error result.
* Item ``title``/``author``/``published_at``/``url`` and the upstream
  ``backend`` label were forwarded with no length bound, so a single response
  could blow far past ``MAX_OUTPUT_BYTES`` after normalisation.
* Output was captured with ``subprocess.run(capture_output=True)`` and only then
  measured against ``MAX_OUTPUT_BYTES``: the whole stream was in memory first.
* ``subprocess.run(timeout=...)`` killed the direct child only, so a grandchild
  (the CLI's own browser/tool process) survived every timeout.
* A ``read``/``thread``/``comments`` row with no body text was forwarded, so a
  body read could report ``ok: true`` with an empty body.
* The optional search fallback forwarded ``limit`` raw, so a ``--limit 200``
  search turned into ``invalid_params`` at the adapter instead of a clamp.

Everything is local: a stub executable, an injected runner, or a real local
child process stand in for the upstream CLI.  No network, no credentials, no
paid calls.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from hermes_trailhead import backends
from hermes_trailhead import reach_backend as reach

LIMIT = reach.MAX_LIMIT


# ── fixtures ──────────────────────────────────────────────────────────────


def registry_payload() -> dict:
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
                        ],
                        "backends": ["jina"],
                        "public_web": ["example.com/"],
                    },
                    {
                        "name": "read",
                        "help": "read",
                        "params": [
                            {"name": "target", "help": "", "required": True, "type": "str"},
                        ],
                        "backends": ["jina"],
                        "public_web": ["example.com/"],
                    },
                ],
            }
        ],
    }


def envelope(channel: str, action: str, items, *, backend: str = "public-web") -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": backend,
        "items": items,
        "meta": {"elapsed_ms": 10},
        "error": None,
    }


def ok_envelope(items, *, backend: str = "public-web") -> dict:
    return envelope("web", "search", items, backend=backend)


def item(**overrides) -> dict:
    base = {
        "title": "A lead",
        "url": "https://example.com/lead",
        "author": None,
        "published_at": None,
        "text": "usable snippet",
        "raw": None,
    }
    base.update(overrides)
    return base


def stub_executable(tmp_path: pathlib.Path) -> str:
    path = tmp_path / "agent-reach"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return str(path)


def payload_runner(registry: dict, response: dict, *, seen: list | None = None):
    def run(argv, *, timeout, env):
        if seen is not None:
            seen.append(list(argv))
        body = registry if list(argv)[1:2] == ["channels"] else response
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")

    return run


def backend_for(tmp_path, response, *, registry=None, seen=None, **kwargs):
    return reach.AgentReachBackend(
        stub_executable(tmp_path),
        runner=payload_runner(registry or registry_payload(), response, seen=seen),
        env={},
        **kwargs,
    )


# ── 1. a non-finite item budget must not raise ────────────────────────────


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_non_finite_max_items_is_an_error_result_not_an_exception(tmp_path, value):
    backend = backend_for(tmp_path, ok_envelope([item()]))

    result = backend.execute("web", "search", {"query": "q"}, max_items=value)

    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert "max_items" in result.error["message"]


def test_non_finite_constructor_budget_falls_back_to_the_default(tmp_path):
    backend = reach.AgentReachBackend(
        stub_executable(tmp_path),
        runner=payload_runner(registry_payload(), ok_envelope([item()])),
        env={},
        max_items=float("inf"),
    )

    assert 1 <= backend._max_items <= reach.MAX_ITEMS
    assert backend.execute("web", "search", {"query": "q"}).ok is True


# ── 2. untrusted response fields are bounded before forwarding ────────────


def test_oversized_item_fields_are_clipped_and_reported(tmp_path):
    huge = "T" * 200_000
    response = ok_envelope(
        [
            item(
                title=huge,
                author=huge,
                published_at=huge,
                url="https://example.com/lead?q=" + ("u" * 100_000),
            )
        ]
    )
    result = backend_for(tmp_path, response).execute("web", "search", {"query": "q"}).to_dict()

    assert result["ok"] is True
    forwarded = result["items"][0]
    assert len(forwarded["title"]) <= reach.MAX_VALUE_CHARS
    assert len(forwarded["author"]) <= reach.MAX_VALUE_CHARS
    assert len(forwarded["published_at"]) <= reach.MAX_VALUE_CHARS
    assert len(forwarded["url"]) <= reach.MAX_URL_CHARS
    assert forwarded["url"].startswith("https://example.com/lead?q=")
    # A clipped field is stated, never silently shortened.
    assert any("truncated" in note for note in result["limitations"])
    # Normalisation must stay well inside the advertised output envelope.
    assert len(json.dumps(result)) < reach.MAX_OUTPUT_BYTES


def test_short_item_fields_are_untouched_and_not_flagged(tmp_path):
    response = ok_envelope([item(title="Short title", author="A")])
    result = backend_for(tmp_path, response).execute("web", "search", {"query": "q"}).to_dict()

    forwarded = result["items"][0]
    assert forwarded["title"] == "Short title"
    assert forwarded["author"] == "A"
    assert not any("truncated" in note for note in result["limitations"])


def test_oversized_reported_backend_is_clipped_and_redacted(tmp_path):
    response = ok_envelope([item()], backend="public-web/" + ("B" * 100_000))
    result = backend_for(tmp_path, response).execute("web", "search", {"query": "q"}).to_dict()

    assert len(result["backend"]) <= reach.MAX_BACKEND_CHARS
    assert len(result["provenance"]["reported_backend"]) <= reach.MAX_BACKEND_CHARS
    assert result["ok"] is True

    leaky = ok_envelope([item()], backend="public-web/sk-" + ("a" * 40))
    leaked = backend_for(tmp_path, leaky).execute("web", "search", {"query": "q"}).to_dict()
    assert "sk-" + "a" * 40 not in json.dumps(leaked)


# ── 3. the runner bounds capture before anything is parsed ───────────────


def test_runner_stops_capturing_at_the_output_cap():
    script = f"import sys; sys.stdout.write('x' * (3 * {reach.MAX_OUTPUT_BYTES}))"
    completed = reach._default_runner(
        [sys.executable, "-c", script],
        timeout=60,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )

    # The child tried to write 12 MB; the drain kept exactly one cap, killed the
    # producer, and says so instead of quietly returning a short answer.
    assert len(completed.stdout.encode("utf-8")) <= reach.MAX_OUTPUT_BYTES
    assert completed.overflow is True
    assert completed.killed is True


def test_runner_bounds_stderr_without_failing_a_chatty_cli():
    """stderr has its own, smaller cap: drained and discarded, not buffered."""
    script = (
        "import sys\n"
        "sys.stderr.write('w' * (3 * 65536))\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write('{\"ok\": true}')\n"
    )
    completed = reach._default_runner(
        [sys.executable, "-c", script],
        timeout=30,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )

    assert len(completed.stderr.encode("utf-8")) == reach.MAX_STDERR_BYTES
    assert completed.stderr_truncated is True
    assert completed.overflow is False
    assert completed.stdout.strip() == '{"ok": true}'
    assert completed.returncode == 0


def test_runner_stops_a_looping_writer_instead_of_hanging():
    """The child never finishes on its own: the cap, not the end of output, decides."""
    script = "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n"
    started = time.monotonic()
    completed = reach._default_runner(
        [sys.executable, "-c", script],
        timeout=60,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    elapsed = time.monotonic() - started

    assert completed.overflow is True
    assert len(completed.stdout.encode("utf-8")) <= reach.MAX_OUTPUT_BYTES
    assert elapsed < 15.0, f"a looping writer held the caller for {elapsed:.1f}s"


def test_thread_drain_fallback_enforces_the_same_caps(monkeypatch):
    """Windows cannot select on pipes; the reader-thread drain must bound too."""
    monkeypatch.setattr(
        reach,
        "_drain",
        lambda proc, capture, deadline: reach._drain_threads(proc, capture, deadline),
    )
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    small = reach._default_runner([sys.executable, "-c", "print('threaded ok')"], timeout=30, env=env)
    assert small.stdout.strip() == "threaded ok"
    assert small.overflow is False

    script = f"import sys; sys.stdout.write('x' * (3 * {reach.MAX_OUTPUT_BYTES}))"
    flooded = reach._default_runner([sys.executable, "-c", script], timeout=60, env=env)
    assert len(flooded.stdout.encode("utf-8")) <= reach.MAX_OUTPUT_BYTES
    assert flooded.overflow is True


def test_runner_raises_timeout_at_the_wall_clock_budget():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        reach._default_runner(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=1.0,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
    elapsed = time.monotonic() - started

    assert excinfo.value.timeout == 1.0
    assert elapsed < 10.0, f"the drain held the caller for {elapsed:.1f}s"


def test_oversized_upstream_output_is_rejected_not_buffered(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        f"sys.stdout.write('x' * {reach.MAX_OUTPUT_BYTES + 1024})\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(
        str(exe), env={"PATH": "/usr/bin:/bin"}, timeout=30
    )

    result = backend.execute("web", "search", {"query": "q"})

    assert result.ok is False
    assert result.error["code"] == "malformed_output"
    assert "oversized" in result.error["message"]


def test_oversized_registry_output_is_rejected_before_parsing(tmp_path):
    """The same cap governs the ``channels`` read, not just the action call."""
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write('x' * {reach.MAX_OUTPUT_BYTES + 1_000_000})\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(
        str(exe), env={"PATH": "/usr/bin:/bin"}, timeout=20
    )

    result = backend.execute("web", "search", {"query": "q"})

    assert result.ok is False
    error = result.error or {}
    assert error.get("code") == "registry_invalid"
    assert "oversized" in (error.get("message") or "")


# ── 4. a timeout kills what the child spawned, not only the child ────────


def _wait_until_gone(pid: int, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pathlib.Path(f"/proc/{pid}").exists():
            return True
        # A reparented zombie still has a /proc entry; treat it as gone.
        try:
            state = pathlib.Path(f"/proc/{pid}/stat").read_text().split()[2]
        except OSError:
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_timeout_kills_the_child_process_group(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys, time\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(
        str(exe), env={"PATH": "/usr/bin:/bin"}, timeout=1
    )
    backend.timeout_grace = 0.05

    try:
        result = backend.execute("web", "search", {"query": "q"})
        assert result.ok is False
        assert result.error["code"] == "timeout"
        assert pidfile.exists(), "the child never recorded its grandchild"
        pid = int(pidfile.read_text())
        assert _wait_until_gone(pid), f"grandchild {pid} survived the timeout"
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_child_that_exits_while_a_descendant_holds_the_pipe_is_killed(tmp_path):
    """The direct child returns; the helper it spawned keeps stdout open.

    Without a process group the drain would sit on the inherited pipe until the
    full timeout, and the helper would survive anyway: the answer is already in,
    so the group is killed after a short grace instead of waiting it out.
    """
    pidfile = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "print('answer', flush=True)\n"
    )
    started = time.monotonic()
    completed = reach._default_runner(
        [sys.executable, "-c", script],
        timeout=30,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    elapsed = time.monotonic() - started

    try:
        # The child's own answer survives; only the leaked pipe-holder is killed.
        assert completed.returncode == 0
        assert completed.stdout.strip() == "answer"
        assert completed.killed is True
        assert elapsed < 10.0, f"the drain waited {elapsed:.1f}s on a leaked pipe"
        assert pidfile.exists(), "the child never recorded its grandchild"
        pid = int(pidfile.read_text())
        assert _wait_until_gone(pid), f"grandchild {pid} kept the pipe open"
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass


# ── 5. the search fallback clamps its own budget ─────────────────────────


def test_search_fallback_clamps_an_oversized_limit(tmp_path, monkeypatch):
    seen: list[list[str]] = []
    adapter = backend_for(
        tmp_path,
        ok_envelope([item()]),
        seen=seen,
    )

    result = backends.run_reach_search_fallback("web", "q", limit=LIMIT + 150, adapter=adapter)

    assert result is not None
    action_argv = [argv for argv in seen if argv[1:2] != ["channels"]][0]
    sent_limit = int(action_argv[action_argv.index("--limit") + 1])
    assert 1 <= sent_limit <= LIMIT
    assert result.error == ""
    assert [hit.url for hit in result.hits] == ["https://example.com/lead"]


def test_search_fallback_survives_a_non_numeric_limit(tmp_path):
    adapter = backend_for(tmp_path, ok_envelope([item()]))

    result = backends.run_reach_search_fallback("web", "q", limit=float("inf"), adapter=adapter)

    assert result is not None
    assert result.error == ""
    assert [hit.url for hit in result.hits] == ["https://example.com/lead"]


# ── 6. extraction keeps real long pages that quote a 404 phrase ──────────


def test_long_docs_page_quoting_two_english_markers_is_not_a_shell():
    """A page *about* 404s quotes several phrasings; it is still a page."""
    from hermes_trailhead.extract import classify_page_shell

    body = (
        "## HTTP status codes in practice\n\n"
        "When an origin has no document for a path, the CDN should serve a real "
        "404 rather than a soft error. A page not found response that returns 200 "
        "confuses crawlers and monitoring alike, so the edge needs an explicit "
        "rewrite rule that keeps the status code intact while still rendering a "
        "friendly template for people who mistype a URL.\n\n"
        "Two common mistakes make this worse. First, teams template the body of a "
        "missing route with the home page, so the response says this page doesn't "
        "exist in the copy but reports success to every cache and client. Second, "
        "they add a retry loop that turns one bad link into a request storm, which "
        "the origin then reports as a rate-limit incident instead of a routing bug.\n\n"
        "The fix is boring: one rewrite table, one template, one status code, and "
        "an alert keyed on the ratio of 404s to total requests per path prefix. "
        "That single ratio catches broken deploys, stale sitemaps, and renamed "
        "sections long before a customer files a ticket about the wrong page.\n\n"
    )
    assert len(body) > 900
    assert "page not found" in body.lower() and "page doesn't exist" in body.lower()

    assert classify_page_shell(body) is None


def test_english_only_404_template_with_several_markers_is_still_a_shell():
    """The corroboration rule must not open a hole for a plain 404 page."""
    from hermes_trailhead.extract import classify_page_shell

    template = (
        "Page not found\n\n"
        "Sorry, we can't seem to find the page you're looking for. This page "
        "doesn't exist any more, or the address was mistyped. Try the search box, "
        "head back to the homepage, or browse the most popular sections below. "
        "If you followed a link from another site, the author may have moved or "
        "removed the document, and the old address is no longer valid.\n\n"
        "Popular sections: news, product, pricing, support, careers, blog.\n"
    ) * 2
    assert len(template) > 800

    assert classify_page_shell(template) == "missing_page"


# ── 7. a body read with no body text is not a successful read ────────────


def test_body_read_with_empty_text_is_content_unusable(tmp_path):
    response = envelope("web", "read", [item(text="", raw=None)])
    result = backend_for(tmp_path, response).execute(
        "web", "read", {"target": "https://example.com/page"}
    ).to_dict()

    assert result["ok"] is False
    assert result["items"] == []
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["empty_body"]
    assert result["error"]["withheld_items"] == 1
    # The reason is stated where a caller reads limitations, not only as a code.
    assert any("empty_body=1" in note for note in result["limitations"])
    # Attribution and provenance survive the rejection.
    assert result["provenance"]["engine"] == "agent-reach"
    assert result["provenance"]["attribution"]


def test_body_read_with_missing_text_field_is_content_unusable(tmp_path):
    """No ``text`` key at all is the same missing artifact as ``text: ""``."""
    response = envelope(
        "web", "read", [{"title": "Page", "url": "https://example.com/page"}]
    )
    result = backend_for(tmp_path, response).execute(
        "web", "read", {"target": "https://example.com/page"}
    ).to_dict()

    assert result["ok"] is False
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["empty_body"]


def test_body_read_with_raw_metadata_but_no_text_is_content_unusable(tmp_path):
    """``raw`` is a side payload, not a page body: it cannot rescue an empty read."""
    response = envelope("web", "read", [item(text="   ", raw={"status": "found"})])
    result = backend_for(tmp_path, response).execute(
        "web", "read", {"target": "https://example.com/page"}
    ).to_dict()

    assert result["ok"] is False
    assert result["error"]["code"] == "content_unusable"
    assert result["error"]["reasons"] == ["empty_body"]


def test_one_empty_row_does_not_hide_a_usable_body(tmp_path):
    response = envelope(
        "web",
        "read",
        [
            item(text="", raw=None),
            item(text="the actual page body", url="https://example.com/page"),
        ],
    )
    result = backend_for(tmp_path, response).execute(
        "web", "read", {"target": "https://example.com/page"}
    ).to_dict()

    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["text"] == "the actual page body"
    assert any("empty_body=1" in note for note in result["limitations"])


def test_search_metadata_items_survive_the_empty_body_rule(tmp_path):
    """Search rows are leads: empty text (with or without raw) is never withheld."""
    response = ok_envelope([item(text="", raw={"score": 0.4}), item(text="")])
    result = backend_for(tmp_path, response).execute("web", "search", {"query": "q"}).to_dict()

    assert result["ok"] is True
    assert len(result["items"]) == 2
    assert not any("withheld" in note for note in result["limitations"])
