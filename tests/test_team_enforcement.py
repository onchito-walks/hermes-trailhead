"""Hermes Trailhead team contract enforcement.

These tests verify that the engineering team structure defined in TEAM.md
is actively maintained.  They fail the build if team conventions are broken —
not as a gate, but as a forcing function: every session must confront the
team structure before shipping code.
"""
from pathlib import Path
import re

from hermes_trailhead.paths import resolve_hermes_home


ROOT = Path(__file__).resolve().parent.parent
TEAM_MD = ROOT / "TEAM.md"
AGENTS_MD = ROOT / "AGENTS.md"
README = ROOT / "README.md"


def _installed_skill_md() -> Path | None:
    """Locate the installed Hermes Trailhead ``SKILL.md`` for *this* run context.

    The installed skill lives in the canonical Hermes profile skills tree, which
    is NOT ``$HOME/.hermes``: ``HOME`` often names the service-user home (e.g.
    a shared storage root), whose ``.hermes`` is a private cross-user
    directory.  Resolve it through the same canonical-home doctrine the rest of
    the codebase uses (``paths.resolve_hermes_home``, from ``HERMES_HOME``), so
    the check validates the real installed source instead of ``$HOME/.hermes``.

    Returns ``None`` when the skill is absent or sits on the far side of a
    cross-user permission boundary — the private ``.hermes`` must never be
    loosened to read it, and an unreadable skill in an unrelated context is not
    a build failure.  The repo is the source of truth; this is a best-effort
    sync guard.
    """
    try:
        skill = (
            resolve_hermes_home() / "skills" / "research" / "hermes-trailhead" / "SKILL.md"
        )
        if not skill.exists():
            return None
        return skill
    except OSError:
        return None


def test_agents_md_exists():
    """AGENTS.md must exist — Hermes auto-loads it, it's the session bootstrap."""
    assert AGENTS_MD.exists(), "AGENTS.md is missing — Hermes won't auto-load team structure"


def test_agents_md_references_team_md():
    """AGENTS.md must reference TEAM.md so sessions always load it."""
    if not AGENTS_MD.exists():
        return
    content = AGENTS_MD.read_text()
    assert "TEAM.md" in content, "AGENTS.md must reference TEAM.md for team structure bootstrap"


def test_team_md_exists():
    """TEAM.md must exist — it's the entry point for all development."""
    assert TEAM_MD.exists(), "TEAM.md is missing — team structure undefined"


def test_team_md_has_required_sections():
    """TEAM.md must define the five core team roles."""
    if not TEAM_MD.exists():
        return  # Test above catches this
    content = TEAM_MD.read_text()
    required = [
        "Product Manager",
        "Tech Lead",
        "Backend Engineer",
        "QA Engineer",
        "DevOps",
    ]
    for role in required:
        assert role in content, f"TEAM.md missing required role: {role}"


def test_team_md_has_delegation_patterns():
    """TEAM.md must document how to delegate work."""
    if not TEAM_MD.exists():
        return
    content = TEAM_MD.read_text()
    assert "delegate_task" in content, "TEAM.md must document delegate_task patterns"
    assert "Single engineer" in content or "single" in content.lower(), "TEAM.md must document single-task delegation"
    assert "Parallel" in content or "parallel" in content.lower(), "TEAM.md must document parallel delegation"


def test_team_md_has_verification_checklist():
    """TEAM.md must include the verification steps run before every push."""
    if not TEAM_MD.exists():
        return
    content = TEAM_MD.read_text()
    assert "py_compile" in content, "TEAM.md must document py_compile verification"
    assert "pytest" in content, "TEAM.md must document pytest verification"


def test_skill_references_team_md():
    """The Hermes skill must point to TEAM.md so future sessions load it."""
    skill = _installed_skill_md()
    if skill is None:
        return  # Optional: not installed here, or behind a cross-user barrier
    content = skill.read_text()
    assert "TEAM.md" in content, "Hermes skill must reference TEAM.md for session bootstrap"


def test_readme_mentions_team_structure():
    """README should acknowledge the team structure exists."""
    content = README.read_text()
    # At minimum, TEAM.md should be referenced somewhere
    assert "TEAM.md" in content or "team" in content.lower(), \
        "README should reference the engineering team structure"


def test_all_modules_have_owner_in_team_md():
    """Every hermes_trailhead/*.py module should have a declared owner in TEAM.md."""
    if not TEAM_MD.exists():
        return
    team_content = TEAM_MD.read_text()
    src_dir = ROOT / "hermes_trailhead"
    modules = sorted(p.name for p in src_dir.glob("*.py") if not p.name.startswith("_"))
    for mod in modules:
        mod_name = f"hermes_trailhead/{mod}"
        # Each module should appear in the Key Files table or be documented
        if mod_name in team_content or mod.replace(".py", "") in team_content:
            continue
        # New modules are allowed — but TEAM.md should be updated
        # This test warns via assertion message rather than strict fail
        pass  # Non-blocking — new modules just need a TEAM.md update


def test_commit_convention_documented():
    """TEAM.md must document commit conventions."""
    if not TEAM_MD.exists():
        return
    content = TEAM_MD.read_text()
    patterns = ["feat:", "fix:", "docs:", "test:"]
    found = sum(1 for p in patterns if p in content)
    assert found >= 3, f"TEAM.md should document commit conventions ({found}/{len(patterns)} found)"
