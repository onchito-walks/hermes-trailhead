"""Adversarial QA regressions for read pagination, shell detection and discovery.

Each case is a defect reproduced in this tree before the fix; nothing here is a
style preference:

* A **suffix window that reaches EOF** reported
  ``completeness.extracted_document_complete: true``.  A window starting at
  offset 20,000 of a 30,000-character document is a window, never a complete
  read, and the documented contract says completeness requires the window to
  cover *all* available extracted characters.
* A **5,000-digit ``--offset``** reached ``int()`` and raised Python's
  int-string digit ceiling (``ValueError: Exceeds the limit (4300 digits)``)
  out of ``cmd_read`` instead of the documented ``invalid_offset`` result.
  Formatting such an integer back into JSON would fail the same way.
* A body made of Han-range code points that ``str.isalnum`` rejects (unassigned
  code points, symbols) satisfied the CJK prose veto but produced zero
  whitespace tokens, so shell classification divided by zero.
* The process-wide registry cache could not tell ``env=None`` (inherit this
  environment) from ``env={}`` (empty child environment): both digests were
  empty, so a discovery read under one configuration served the other, and a
  changed inherited ``HOME``/``TRAILHEAD_AGENT_REACH_HOME`` reused the old
  inventory.  A ``@dataclass`` runner (unhashable by default) escaped
  ``registry()`` as ``TypeError`` because it was used as part of a dict key.
* The in-flight action deadline lived on the instance, so a thread sharing an
  adapter saw another thread's remaining budget — including the
  "budget already spent" ``RegistryError`` — while the docstring promised a
  read outside a call is never bounded by a stale deadline.
* A **float parameter wider than a double** (``10**309``, ``10**10000``)
  raised ``OverflowError: int too large to convert to float`` out of
  ``_validate_float`` instead of the documented ``invalid_params`` result, so
  an unusable number escaped as a crash two layers below the caller.
* Paged windows carried **no document identity**: two responses at different
  offsets could not be shown to describe the same text, and nothing said that
  each ``read`` refetches the URL.  ``pagination.document_sha256`` now hashes
  the full available extracted text; the tests pin equal digests for windows
  of one document, a changed digest for edited content, and ``""`` when no
  document was read.

Everything is local: stub executables and injected runners.  No network, no
credentials, no paid calls.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from hermes_trailhead import cli
from hermes_trailhead import extract as extract_mod
from hermes_trailhead import reach_backend as reach
from hermes_trailhead.cli import main
from hermes_trailhead.extract import ExtractedHit, ExtractionResult, _is_html_shell

URL = "https://example.com/qa-document"


# ── read pagination helpers ───────────────────────────────────────────────


def _fake_extract(monkeypatch, content: str, measured: int | None = None):
    """One-hit extraction stub; records calls so "not attempted" is provable."""
    calls: list[dict] = []

    def fake(hits, *, limit=5, extract=None, fetch=None, timeout=15):
        calls.append({"limit": limit, "timeout": timeout})
        return (
            ExtractedHit(
                title="",
                url=hits[0].url,
                extraction=ExtractionResult(
                    status="ok",
                    content=content,
                    content_length=len(content) if measured is None else measured,
                ),
            ),
        )

    monkeypatch.setattr(cli, "extract_hits", fake)
    return calls


def _run_json(capsys, argv: list[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured.err


#: 60,000 characters: three 20k windows, so a 20k tail window ends exactly at
#: EOF with `more: false` while starting at offset > 0.
DOC = "".join(f"paragraph {n:04d} carries readable prose for paging. " for n in range(1200))
assert len(DOC) > 2 * cli.READ_DEFAULT_MAX_CHARS


def test_suffix_window_at_eof_never_claims_completeness(monkeypatch, capsys):
    """The parent defect: offset>0, end==total, no bounds hit → falsely true."""
    _fake_extract(monkeypatch, DOC)
    tail_offset = len(DOC) - 1000

    rc, payload, err = _run_json(
        capsys,
        ["read", URL, "--format", "json", "--offset", str(tail_offset)],
    )

    assert rc == 0 and err == ""
    page = payload["pagination"]
    assert page["start"] == tail_offset
    assert page["end"] == len(DOC)
    assert page["more"] is False
    assert payload["truncated"] is False
    # The window is truthful (it is not cut), but it is not the document.
    assert payload["content"] == DOC[tail_offset:]
    assert payload["completeness"]["extracted_document_complete"] is False


def test_only_a_zero_offset_full_window_claims_completeness(monkeypatch, capsys):
    _fake_extract(monkeypatch, DOC)

    rc, payload, _ = _run_json(
        capsys,
        ["read", URL, "--format", "json", "--max-chars", str(len(DOC))],
    )

    assert rc == 0
    page = payload["pagination"]
    assert page["start"] == 0 and page["end"] == len(DOC)
    assert page["more"] is False
    assert payload["content"] == DOC
    assert payload["completeness"]["extracted_document_complete"] is True
    # Completeness is still only a claim about the extracted text.
    assert payload["completeness"]["raw_page_complete"] is False


def test_a_lost_document_never_claims_completeness(monkeypatch, capsys):
    """A zero-offset window with an extractor/retrieval loss stays false."""
    kept, measured = DOC[:5000], len(DOC)
    _fake_extract(monkeypatch, kept, measured=measured)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 0
    assert payload["pagination"]["start"] == 0
    assert payload["pagination"]["end"] == len(kept)
    assert payload["pagination"]["extractor_truncated"] is True
    assert payload["truncated"] is True
    assert payload["completeness"]["extracted_document_complete"] is False


def test_empty_document_is_not_complete(monkeypatch, capsys):
    _fake_extract(monkeypatch, "", measured=0)

    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["error"]["code"] == "unusable_evidence"
    assert payload["pagination"]["window_empty"] is True
    assert payload["completeness"]["extracted_document_complete"] is False


# ── hostile paging arguments stay a stable JSON error ─────────────────────


@pytest.mark.parametrize(
    ("flag", "value", "code"),
    [
        ("--offset", "1" * 5000, "invalid_offset"),
        ("--offset", "0" * 5000 + "5", "invalid_offset"),
        ("--offset", "9" * 19, "invalid_offset"),
        ("--max-chars", "1" * 5000, "invalid_max_chars"),
        ("--max-chars", "9" * 19, "invalid_max_chars"),
    ],
)
def test_huge_digit_paging_arguments_are_stable_errors(
    monkeypatch, capsys, flag, value, code
):
    calls = _fake_extract(monkeypatch, DOC)

    rc, payload, err = _run_json(
        capsys, ["read", URL, "--format", "json", flag, value]
    )

    assert rc == 2
    assert err == ""
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert payload["extraction_status"] == "not_attempted"
    assert payload["content"] == ""
    assert "non-negative integer" in payload["error"]["message"]
    assert calls == []


def test_huge_integer_instance_is_rejected_without_formatting_it():
    """An API caller can pass an int, not just argv text: same stable result."""
    huge = 10**4000

    offset, _, _, code, _ = cli._read_pagination_args(huge, None)

    assert offset == 0
    assert code == "invalid_offset"


def test_eighteen_digit_offset_is_still_a_beyond_end_window(monkeypatch, capsys):
    """The guard must not reject a large-but-usable offset."""
    _fake_extract(monkeypatch, DOC)
    far = 10**18 - 1

    rc, payload, _ = _run_json(
        capsys, ["read", URL, "--format", "json", "--offset", str(far)]
    )

    assert rc == 0
    assert payload["pagination"]["offset"] == far
    assert payload["content"] == ""
    assert payload["pagination"]["window_empty"] is True
    assert "beyond the" in payload["pagination"]["note"]


# ── a float parameter wider than a double is a stable error ──────────────


@pytest.mark.parametrize(
    "value",
    [10**309, 10**400, 10**10000, -(10**10000)],
    ids=["double-overflow", "float-binding-overflow", "ten-thousand-digits", "negative"],
)
def test_huge_integer_float_parameter_is_a_stable_error(value):
    """Reproduced: ``OverflowError`` escaped ``_validate_float``."""
    with pytest.raises(reach.InvalidRequest) as excinfo:
        reach._validate_float(value, "weight")

    assert excinfo.value.code == "invalid_params"
    assert "out of bounds" in excinfo.value.message


def test_huge_integer_float_parameter_is_rejected_through_coercion():
    """The crash also escaped the public parameter path, not just the helper."""
    action = reach.ReachAction(
        name="search",
        help="",
        params=(reach.ReachParam(name="weight", required=True, type="float"),),
    )

    with pytest.raises(reach.InvalidRequest) as excinfo:
        reach._coerce_params(action, {"weight": 10**10000})

    assert excinfo.value.code == "invalid_params"


def test_usable_float_parameters_keep_their_spelling():
    """The overflow guard must not reject a representable, in-bounds number."""
    assert reach._validate_float(10**12, "weight") == "1000000000000"
    assert reach._validate_float(2, "weight") == "2"
    assert reach._validate_float("0.5", "weight") == "0.5"


def test_finite_but_huge_float_string_is_still_out_of_bounds():
    """A spelled value past the bound keeps the pre-existing result."""
    with pytest.raises(reach.InvalidRequest) as excinfo:
        reach._validate_float("1e400", "weight")

    assert excinfo.value.code == "invalid_params"
    assert "finite" in excinfo.value.message


# ── document identity across windows ─────────────────────────────────────


def _document_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_every_window_of_one_document_reports_the_same_identity(monkeypatch, capsys):
    _fake_extract(monkeypatch, DOC)
    digests: list[str] = []
    windows: list[str] = []

    for offset in (0, 20000, len(DOC) - 1000):
        rc, payload, err = _run_json(
            capsys, ["read", URL, "--format", "json", "--offset", str(offset)]
        )
        assert rc == 0 and err == ""
        digests.append(payload["pagination"]["document_sha256"])
        windows.append(payload["content"])

    # One document, one identity — and it is the digest of the *whole*
    # available extracted text, not of the returned window.
    assert digests == [_document_digest(DOC)] * 3
    assert windows[1] == DOC[20000:40000]
    assert windows[2] != DOC


def test_changed_document_content_changes_the_identity(monkeypatch, capsys):
    """Same URL, same length, one edited character: the digest must differ."""
    _fake_extract(monkeypatch, DOC)
    _, first, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    edited = DOC[:-1] + ("X" if DOC[-1] != "X" else "Y")
    assert len(edited) == len(DOC)
    _fake_extract(monkeypatch, edited)
    _, second, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert first["pagination"]["document_sha256"] == _document_digest(DOC)
    assert second["pagination"]["document_sha256"] == _document_digest(edited)
    assert (
        first["pagination"]["document_sha256"]
        != second["pagination"]["document_sha256"]
    )
    assert (
        first["pagination"]["total_available_chars"]
        == second["pagination"]["total_available_chars"]
        == len(DOC)
    )


def test_no_document_read_means_no_identity(monkeypatch, capsys):
    """Every path that never extracted keeps the empty default."""
    calls = _fake_extract(monkeypatch, DOC)

    rc, rejected, _ = _run_json(
        capsys, ["read", URL, "--format", "json", "--offset", "1" * 5000]
    )

    assert rc == 2
    assert rejected["pagination"]["document_sha256"] == ""
    assert calls == []


def test_empty_and_unusable_documents_claim_no_identity(monkeypatch, capsys):
    _fake_extract(monkeypatch, "", measured=0)
    rc, payload, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    assert rc == 1
    assert payload["pagination"]["window_empty"] is True
    assert payload["pagination"]["document_sha256"] == ""

    _fake_extract(monkeypatch, "short")
    rc, small, _ = _run_json(capsys, ["read", URL, "--format", "json"])

    # "short" is a real (if unusable) document: it has an identity even though
    # the read is not usable evidence.
    assert rc == 1
    assert small["pagination"]["document_sha256"] == _document_digest("short")


# ── shell classification: no division by zero, no widened verdicts ───────


def test_cjk_range_body_without_whitespace_tokens_does_not_divide_by_zero():
    """Reproduced: ZeroDivisionError from ``unique / len(words)``."""
    # U+3040 is inside the counted Han/Kana range but is not alphanumeric, so
    # the CJK prose veto passes while the token list stays empty.
    body = "\u3040" * 80 + "。！"
    cleaned = extract_mod._clean_html_text(body)
    assert extract_mod._cjk_char_count(cleaned) >= 80
    assert [w for w in cleaned.split() if any(c.isalnum() for c in w)] == []
    assert extract_mod._looks_like_cjk_prose(cleaned) is True

    html = f"<html><body><div>{body}</div></body></html>"
    assert _is_html_shell(html) is True


@pytest.mark.parametrize(
    "body",
    ["", "   \n\t  ", "<p>   </p>", "\u3040" * 200],
)
def test_whitespace_and_tokenless_bodies_never_raise(body):
    html = f"<html><body>{body}</body></html>"

    verdict = _is_html_shell(html)

    assert verdict in (True, False)


def test_cjk_fixes_do_not_widen_shell_verdicts():
    """A short CJK document stays a document; a CJK label pane stays a shell."""
    document = (
        "<!DOCTYPE html><html lang='zh-CN'><body><h1>快速开始</h1>"
        + "".join(
            "<p>安装依赖之后运行命令创建索引，索引会为每一行生成条目，"
            "条目写入之后即可查询第{n}节。</p>".format(n=n)
            for n in range(8)
        )
        + "</body></html>"
    )
    shell = (
        "<!DOCTYPE html><html lang='zh-CN'><body><div class='app'>"
        "<button>登录</button><button>注册</button><div>加载中</div>"
        "<div>查询结果</div><div>暂无数据</div></div></body></html>"
    )

    assert _is_html_shell(document) is False
    assert _is_html_shell(shell) is True


# ── registry cache boundaries and the shared deadline ────────────────────


REGISTRY_TEMPLATE = {
    "schema_version": 1,
    "ok": True,
    "channels": [],
}


def _registry_with(names: list[str]) -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "channels": [
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
                            {"name": "query", "help": "", "required": True, "type": "str"}
                        ],
                        "backends": ["jina"],
                        "public_web": ["example.com/"],
                    }
                ],
            }
            for name in names
        ],
    }


OK_ENVELOPE = {
    "schema_version": 1,
    "ok": True,
    "channel": "web",
    "action": "search",
    "backend": "public-web",
    "items": [{"title": "lead", "url": "https://example.com/lead", "text": "snippet"}],
    "meta": {"elapsed_ms": 5},
    "error": None,
}


def _stub(tmp_path: pathlib.Path, name: str = "agent-reach") -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return str(path)


class EnvSensitiveRunner:
    """Inventory depends on the child environment the discovery read ran in."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, argv, *, timeout, env):
        argv = list(argv)
        self.calls.append(
            {"argv": argv, "env": dict(env or {}), "timeout": timeout}
        )
        if argv[1:2] == ["channels"]:
            # TMPDIR travels through ``_ENV_PASSTHROUGH`` unchanged: present
            # when the child inherits this process, absent for ``env={}``.
            names = ["web", "github"] if env.get("TMPDIR") else ["web"]
            body = json.dumps(_registry_with(names))
        else:
            body = json.dumps(OK_ENVELOPE)
        return SimpleNamespace(returncode=0, stdout=body, stderr="")


class BlockingRunner:
    """``channels`` blocks until released, so a call can be observed in flight."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[dict] = []

    def __call__(self, argv, *, timeout, env):
        argv = list(argv)
        self.calls.append({"argv": argv, "timeout": timeout})
        if argv[1:2] == ["channels"]:
            self.entered.set()
            assert self.release.wait(5.0), "test did not release the runner"
            body = json.dumps(_registry_with(["web"]))
        else:
            body = json.dumps(OK_ENVELOPE)
        return SimpleNamespace(returncode=0, stdout=body, stderr="")


@pytest.fixture(autouse=True)
def isolated_registry_cache():
    reach.clear_registry_cache()
    yield
    reach.clear_registry_cache()


@pytest.fixture()
def stub(tmp_path):
    return _stub(tmp_path)


def test_inherited_and_empty_child_environments_are_different_entries(
    stub, monkeypatch, tmp_path
):
    """``env=None`` inherits TMPDIR; ``env={}`` does not.  They must not share."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner = EnvSensitiveRunner()
    inherited = reach.AgentReachBackend(stub, runner=runner, env=None)
    empty = reach.AgentReachBackend(stub, runner=runner, env={})

    assert sorted(inherited.registry().channels) == ["github", "web"]
    assert sorted(empty.registry().channels) == ["web"]
    assert len(runner.calls) == 2


def test_changing_the_inherited_config_home_re_runs_discovery(
    stub, monkeypatch, tmp_path
):
    """``HOME`` decides which upstream config is read, so it is part of the key."""
    runner = EnvSensitiveRunner()
    monkeypatch.setenv("HOME", str(tmp_path / "home-a"))
    reach.AgentReachBackend(stub, runner=runner, env=None).registry()
    monkeypatch.setenv("HOME", str(tmp_path / "home-b"))
    reach.AgentReachBackend(stub, runner=runner, env=None).registry()

    assert len(runner.calls) == 2


def test_same_inherited_configuration_still_shares_one_read(
    stub, monkeypatch, tmp_path
):
    """The distinction must not disable the sharing it fixes."""
    runner = EnvSensitiveRunner()
    monkeypatch.setenv("HOME", str(tmp_path))

    first = reach.AgentReachBackend(stub, runner=runner, env=None)
    second = reach.AgentReachBackend(stub, runner=runner, env=None)

    assert first.registry() is second.registry()
    assert len(runner.calls) == 1


def test_registry_cache_key_still_hides_config_values(stub):
    key = reach.registry_cache_key(
        stub, public=False, env={"GITHUB_TOKEN": "ghp_secret_value"}, runner=None
    )

    assert "ghp_secret_value" not in repr(key)
    assert "GITHUB_TOKEN" not in repr(key)
    assert reach.registry_cache_key(
        stub, public=False, env=None, runner=None
    ) != reach.registry_cache_key(stub, public=False, env={}, runner=None)


@dataclass
class DataclassRunner:
    """Unhashable callable: ``@dataclass`` defines ``__eq__``, so no ``__hash__``."""

    calls: list = field(default_factory=list)

    def __call__(self, argv, *, timeout, env):
        argv = list(argv)
        self.calls.append(argv)
        body = json.dumps(
            _registry_with(["web"])
            if argv[1:2] == ["channels"]
            else OK_ENVELOPE
        )
        return SimpleNamespace(returncode=0, stdout=body, stderr="")


def test_unhashable_runner_is_uncacheable_but_never_raises(stub):
    runner = DataclassRunner()
    backend = reach.AgentReachBackend(stub, runner=runner, env={})

    registry = backend.registry()
    assert registry.schema_version == 1
    # Not shareable process-wide, but the per-instance cache still works.
    assert len(reach._REGISTRY_CACHE) == 0
    assert backend.registry() is registry
    assert len(runner.calls) == 1

    result = backend.execute("web", "search", {"query": "q"})

    assert result.ok is True


def test_action_deadline_is_per_thread(stub):
    """A discovery read in one thread must not bound another thread's read."""
    runner = BlockingRunner()
    backend = reach.AgentReachBackend(stub, runner=runner, env={})
    outcome: list[str] = []

    def hold_call() -> None:
        try:
            backend._registry_for_action(time.monotonic() + 30.0)
            outcome.append("ok")
        except Exception as exc:  # pragma: no cover - a failure is the assertion
            outcome.append(f"{type(exc).__name__}: {exc}")
        finally:
            backend._call_state.deadline = None

    worker = threading.Thread(target=hold_call)
    worker.start()
    try:
        assert runner.entered.wait(5.0)
        # This thread has entered no call: it must keep the full ceiling.
        assert backend._call_deadline is None
        assert backend._discovery_budget(backend._call_deadline) == pytest.approx(
            backend.timeout_grace + reach.REGISTRY_DISCOVERY_BUDGET
        )
    finally:
        runner.release.set()
        worker.join(5.0)

    assert outcome == ["ok"]
    assert backend._call_deadline is None


def test_deadline_is_still_restored_after_a_call(stub):
    runner = EnvSensitiveRunner()
    backend = reach.AgentReachBackend(stub, runner=runner, env={})

    assert backend.execute("web", "search", {"query": "q"}).ok is True
    assert backend._call_deadline is None
    channels_timeout = [
        call for call in runner.calls if call["argv"][1:2] == ["channels"]
    ][0]
    assert channels_timeout["timeout"] <= (
        reach.AgentReachBackend.timeout_grace + reach.REGISTRY_DISCOVERY_BUDGET
    )
