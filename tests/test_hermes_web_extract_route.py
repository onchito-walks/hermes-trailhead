"""Route pin for the helper ``hermes chat`` web_extract run (``--source tool``).

The weekly social-digest cron exports TRAILHEAD_HERMES_EXTRACT_MODEL /
TRAILHEAD_HERMES_EXTRACT_PROVIDER so its rare Hermes web_extract fallback
runs on deepseek-v4.1-flash @ opencode-go.  Without an explicit pin the
helper's ``--ignore-user-config`` run would inherit ``hermes chat``'s
built-in default route instead.

These tests pin both halves of the contract:

* env unset -> the helper command is exactly the historical command
  (no ``-m`` / no ``--provider``): every non-cron caller keeps built-in
  behavior unchanged;
* env pinned -> the command carries the explicit route while keeping
  ``--source tool``, ``--ignore-user-config``, ``--ignore-rules``, and
  ``--safe-mode``;
* a mocked ``hermes`` binary captures the real argv and the inherited
  environment the child process receives (no network, no inference).
"""
import json
import os

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import _fetch_hermes_web_extract

MODEL_ENV = extract_mod.HERMES_WEB_EXTRACT_MODEL_ENV
PROVIDER_ENV = extract_mod.HERMES_WEB_EXTRACT_PROVIDER_ENV
FLASH_MODEL = "deepseek-v4.1-flash"
GO_PROVIDER = "opencode-go"

URL = "https://example.com"

# Everything after the query prompt: the safety/tool contract that must never
# change (operator session lists stay clean, user config/rules stay ignored).
SAFE_ARGS = [
    "-t", "web",
    "-Q",
    "--ignore-rules",
    "--ignore-user-config",
    "--source", "tool",
    "--safe-mode",
]


def _expected_prompt(url: str) -> str:
    return (
        "Use the native web_extract tool on the URL below and return only the "
        "extracted markdown content, with no explanation, no preamble, and no "
        "code fencing.\n\n"
        f"URL: {json.dumps(url)}"
    )


def _clear_pin(monkeypatch) -> None:
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)


class _FakeProc:
    returncode = 0
    stdout = "Readable markdown content from https://example.com:\n\nBody text."
    stderr = ""


def _capture_run(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(extract_mod.subprocess, "run", fake_run)
    return captured


def test_unset_pin_keeps_historical_command(monkeypatch):
    _clear_pin(monkeypatch)
    captured = _capture_run(monkeypatch)

    assert _fetch_hermes_web_extract(URL) == "Body text."

    assert captured["cmd"] == [
        "hermes", "chat",
        "-q", _expected_prompt(URL),
        *SAFE_ARGS,
    ]
    assert captured["kwargs"].get("capture_output") is True
    assert captured["kwargs"].get("text") is True


def test_pinned_command_is_flash_go_lane(monkeypatch):
    monkeypatch.setenv(MODEL_ENV, FLASH_MODEL)
    monkeypatch.setenv(PROVIDER_ENV, GO_PROVIDER)
    captured = _capture_run(monkeypatch)

    _fetch_hermes_web_extract(URL)

    assert captured["cmd"] == [
        "hermes", "chat",
        "-m", FLASH_MODEL,
        "--provider", GO_PROVIDER,
        "-q", _expected_prompt(URL),
        *SAFE_ARGS,
    ]


def test_route_args_helper_reads_env_per_invocation(monkeypatch):
    _clear_pin(monkeypatch)
    assert extract_mod._hermes_web_extract_route_args() == []

    monkeypatch.setenv(MODEL_ENV, FLASH_MODEL)
    assert extract_mod._hermes_web_extract_route_args() == ["-m", FLASH_MODEL]

    monkeypatch.setenv(PROVIDER_ENV, GO_PROVIDER)
    assert extract_mod._hermes_web_extract_route_args() == [
        "-m", FLASH_MODEL, "--provider", GO_PROVIDER,
    ]


def _write_mock_hermes(tmp_path):
    """A fake ``hermes`` executable that records argv + route env to files."""
    argv_file = tmp_path / "argv.txt"
    env_file = tmp_path / "env.txt"
    mock = tmp_path / "hermes"
    mock.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" > "$MOCK_ARGV_FILE"\n'
        "env | grep -E "
        " '^(TRAILHEAD_HERMES_EXTRACT_MODEL|TRAILHEAD_HERMES_EXTRACT_PROVIDER)=' "
        '| sort > "$MOCK_ENV_FILE" || true\n'
        "printf 'Readable markdown content from https://example.com:\\n\\n"
        "Mocked body.\\n'\n"
    )
    mock.chmod(0o755)
    return argv_file, env_file


def test_mock_hermes_binary_captures_pinned_route(tmp_path, monkeypatch):
    argv_file, env_file = _write_mock_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MOCK_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("MOCK_ENV_FILE", str(env_file))
    monkeypatch.setenv(MODEL_ENV, FLASH_MODEL)
    monkeypatch.setenv(PROVIDER_ENV, GO_PROVIDER)

    content = _fetch_hermes_web_extract(URL, timeout=5)

    assert "Mocked body." in content
    argv = argv_file.read_text().splitlines()
    assert argv[0] == "chat"
    assert argv[1:5] == ["-m", FLASH_MODEL, "--provider", GO_PROVIDER]
    source_idx = argv.index("--source")
    assert argv[source_idx + 1] == "tool"
    assert "--safe-mode" in argv
    assert "--ignore-user-config" in argv
    env_lines = env_file.read_text().splitlines()
    assert f"{MODEL_ENV}={FLASH_MODEL}" in env_lines
    assert f"{PROVIDER_ENV}={GO_PROVIDER}" in env_lines


def test_mock_hermes_binary_unset_pin_has_no_route_flags(tmp_path, monkeypatch):
    argv_file, env_file = _write_mock_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MOCK_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("MOCK_ENV_FILE", str(env_file))
    _clear_pin(monkeypatch)

    _fetch_hermes_web_extract(URL, timeout=5)

    argv = argv_file.read_text().splitlines()
    assert argv[0] == "chat"
    assert "-m" not in argv
    assert "--provider" not in argv
    source_idx = argv.index("--source")
    assert argv[source_idx + 1] == "tool"
    assert env_file.read_text().strip() == ""
