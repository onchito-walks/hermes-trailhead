"""Canonical Hermes/Trailhead paths.

Every module must resolve the canonical Hermes home and state directory the
same way, so doctor, reliability tracker, circuit breaker, and the Guardian
cron all agree on where state lives — even when a chroot/container/profile
sets ``$HOME`` to a path nested inside ``.hermes`` (e.g. ``.../.hermes/home``).
Centralizing here prevents duplicate live-vs-canonical state paths.
"""
from __future__ import annotations

from pathlib import Path


def resolve_hermes_home(home: Path | None = None) -> Path:
    """Resolve the canonical Hermes home directory.

    Normally ``$HOME/.hermes``. In chroot/container deployments ``$HOME`` may
    itself point inside a ``.hermes`` dir (e.g. ``.../.hermes/home``), in which
    case the enclosing ``.hermes`` holding ``config.yaml`` is the real home —
    resolving to ``$HOME/.hermes`` there would miss the actual config.
    """
    home = home or Path.home()
    nested = home / ".hermes"
    if (nested / "config.yaml").exists():
        return nested
    parent = home.parent
    if parent.name == ".hermes" and (parent / "config.yaml").exists():
        return parent
    return nested


def hermes_state_dir(home: Path | None = None) -> Path:
    """Canonical state directory under the resolved Hermes home."""
    return resolve_hermes_home(home) / "state"