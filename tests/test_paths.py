"""Canonical Hermes home resolution — regression tests.

The normal host shell has ``HOME=<user-home>`` (a plain login home whose
``~/.hermes`` holds no config or secrets) while the canonical Hermes home is
exported via ``HERMES_HOME`` (e.g. ``<HERMES_ROOT>/.hermes``).
Raw ``~/.hermes`` expansion used to lose the canonical secrets/proxy files,
breaking YouTube transcript extraction from the shell.
"""
from hermes_trailhead.paths import (
    hermes_secrets_dir,
    hermes_state_dir,
    resolve_hermes_home,
)


def test_hermes_home_env_wins_over_unrelated_shell_home(monkeypatch, tmp_path):
    # HOME points at a plain shell home with no Hermes config; HERMES_HOME
    # names the canonical Hermes home. Regression: the resolver used to
    # return $HOME/.hermes, losing canonical secrets/state.
    shell_home = tmp_path / "shell-home"
    shell_home.mkdir()
    canonical = tmp_path / "canonical-hermes-home"
    canonical.mkdir()
    monkeypatch.setenv("HOME", str(shell_home))
    monkeypatch.setenv("HERMES_HOME", str(canonical))
    assert resolve_hermes_home() == canonical


def test_hermes_home_home_derived_when_env_unset(monkeypatch, tmp_path):
    # No HERMES_HOME: standard $HOME/.hermes layout still resolves.
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "config.yaml").write_text("x: 1")
    assert resolve_hermes_home() == tmp_path / ".hermes"


def test_explicit_home_param_still_wins_over_env(monkeypatch, tmp_path):
    # Callers passing an explicit home (doctor/config checks, tests) keep
    # deterministic behavior regardless of the ambient HERMES_HOME.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "elsewhere"))
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "config.yaml").write_text("x: 1")
    assert resolve_hermes_home(tmp_path) == tmp_path / ".hermes"


def test_hermes_secrets_and_state_dirs_under_canonical_home(monkeypatch, tmp_path):
    canonical = tmp_path / "hermes"
    canonical.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(canonical))
    assert hermes_secrets_dir() == canonical / "secrets"
    assert hermes_state_dir() == canonical / "state"