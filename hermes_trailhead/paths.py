"""Canonical Hermes/Trailhead paths.

Every module must resolve the canonical Hermes home and state directory the
same way, so doctor, reliability tracker, circuit breaker, the Guardian cron,
and the proxy-backed extractors all agree on where secrets and state live.
Centralizing here prevents duplicate live-vs-canonical paths.

The canonical Hermes home is NOT always derived from ``$HOME``: the operator's
login shell has ``HOME=<user-home>`` (an empty dev ``~/.hermes`` without
config or secrets) while the real Hermes home is
``<HERMES_ROOT>/.hermes``.  That home is exported as ``HERMES_HOME``
by ``~/.profile`` for login shells and by the Hermes runtime for
agent/cron sessions — so ``HERMES_HOME`` is the durable, explicit source of
truth, with ``$HOME``-derived heuristics as fallback for chroot/container
deployments.
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_hermes_home(home: Path | None = None) -> Path:
    """Resolve the canonical Hermes home directory.

    Resolution order:
    1. ``HERMES_HOME`` env var (when no explicit ``home`` is passed) — the
       operator's durable declaration of the canonical Hermes home, set by
       ``~/.profile`` and by the Hermes runtime.
    2. ``$HOME/.hermes`` when it holds ``config.yaml`` (standard layout).
    3. ``$HOME`` itself when it is nested inside a ``.hermes`` dir that holds
       ``config.yaml`` — chroot/container deployments where ``$HOME`` may
       itself point inside ``.hermes`` (e.g. ``.../.hermes/home``).
    4. ``$HOME/.hermes`` as fallback, so doctor can report it missing rather
       than guess another location.
    """
    if home is None:
        explicit = os.environ.get("HERMES_HOME")
        if explicit:
            return Path(explicit)
        home = Path.home()
    nested = home / ".hermes"
    if (nested / "config.yaml").exists():
        return nested
    parent = home.parent
    if parent.name == ".hermes" and (parent / "config.yaml").exists():
        return parent
    return nested


def hermes_secrets_dir(home: Path | None = None) -> Path:
    """Canonical secrets directory under the resolved Hermes home."""
    return resolve_hermes_home(home) / "secrets"


def hermes_state_dir(home: Path | None = None) -> Path:
    """Canonical state directory under the resolved Hermes home."""
    return resolve_hermes_home(home) / "state"