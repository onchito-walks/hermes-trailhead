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
    resolve_hermes_agent_repo,
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


def test_agent_repo_sibling_of_hermes_home_when_present(monkeypatch, tmp_path):
    # Canonical layout on the operator host: the checkout is a sibling of the
    # .hermes home, not inside it. Regression: the repo used to be derived as
    # <home>/hermes-agent, which pointed at a nonexistent directory.
    base = tmp_path / "hermes-native"
    home_dir = base / ".hermes"
    repo = base / "hermes-agent"
    home_dir.mkdir(parents=True)
    (home_dir / "config.yaml").write_text("x: 1")
    repo.mkdir()
    monkeypatch.delenv("HERMES_AGENT_REPO", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home_dir))
    assert resolve_hermes_agent_repo() == repo


def test_agent_repo_inline_layout_when_no_sibling(monkeypatch, tmp_path):
    # Legacy layout: checkout lives inside the .hermes home. Still resolved.
    home_dir = tmp_path / ".hermes"
    repo = home_dir / "hermes-agent"
    home_dir.mkdir()
    (home_dir / "config.yaml").write_text("x: 1")
    repo.mkdir()
    monkeypatch.delenv("HERMES_AGENT_REPO", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home_dir))
    assert resolve_hermes_agent_repo() == repo


def test_agent_repo_env_override_wins(monkeypatch, tmp_path):
    # HERMES_AGENT_REPO is the explicit override and must beat any derived path,
    # even one that exists.
    base = tmp_path / "nested"
    home_dir = base / ".hermes"
    home_dir.mkdir(parents=True)
    (home_dir / "config.yaml").write_text("x: 1")
    override = tmp_path / "elsewhere-agent"
    override.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home_dir))
    monkeypatch.setenv("HERMES_AGENT_REPO", str(override))
    assert resolve_hermes_agent_repo() == override


def test_agent_repo_falls_back_to_sibling_when_missing(monkeypatch, tmp_path):
    # Nothing exists: fall back to the canonical sibling path so doctor reports
    # it missing there rather than guessing an inline location.
    base = tmp_path / "bare"
    home_dir = base / ".hermes"
    home_dir.mkdir(parents=True)
    (home_dir / "config.yaml").write_text("x: 1")
    monkeypatch.delenv("HERMES_AGENT_REPO", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home_dir))
    assert resolve_hermes_agent_repo() == base / "hermes-agent"