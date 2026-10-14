"""Canonical Hermes/Trailhead paths.

Every module must resolve the canonical Hermes home and state directory the
same way, so doctor, reliability tracker, circuit breaker, the Guardian cron,
and the proxy-backed extractors all agree on where secrets and state live.
Centralizing here prevents duplicate live-vs-canonical paths.

The canonical Hermes home is NOT always derived from ``$HOME``: a login shell
may carry a plain home with an empty ``~/.hermes`` (no config, no secrets)
while the real Hermes home lives elsewhere on the host. That location is
exported as ``HERMES_HOME`` by the operator's profile for login shells and by
the Hermes runtime for agent/cron sessions — so ``HERMES_HOME`` is the
durable, explicit source of truth, with ``$HOME``-derived heuristics as
fallback for chroot/container deployments.
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


def resolve_hermes_agent_repo(home: Path | None = None) -> Path:
    """Resolve the canonical live Hermes agent checkout.

    Deployments commonly keep the Hermes source checkout *beside* the
    ``.hermes`` home rather than inside it (siblings on disk). Resolution
    order:

    1. ``HERMES_AGENT_REPO`` env var (explicit override, wins).
    2. The canonical sibling layout ``<hermes_home>/.parent/hermes-agent`` when
       it exists — the layout used on this host.
    3. ``<hermes_home>/hermes-agent`` — legacy inline layout.
    4. Fall back to the canonical sibling path so doctor reports it missing
       rather than guessing a wrong location.
    """
    explicit = os.environ.get("HERMES_AGENT_REPO")
    if explicit:
        return Path(explicit)
    hermes_home = resolve_hermes_home(home)
    sibling = hermes_home.parent / "hermes-agent"
    if sibling.exists():
        return sibling
    inline = hermes_home / "hermes-agent"
    if inline.exists():
        return inline
    return sibling