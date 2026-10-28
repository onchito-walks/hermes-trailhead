"""Keep the suite independent of the operator's live host state.

Backends consult two pieces of real host state: the circuit-breaker file in
``~/.hermes/state`` and a Tavily key read from the Hermes ``.env``.  Left alone,
a machine that has been running live sweeps (open circuits) or that has a paid
key configured fails search tests for reasons unrelated to the code under test.
"""
from __future__ import annotations

import pytest

from hermes_trailhead import backends


@pytest.fixture(autouse=True)
def _isolated_backend_state(monkeypatch, tmp_path):
    # Fresh circuit state: no backend is skipped because of earlier live runs.
    monkeypatch.setattr(backends, "_DEFAULT_CIRCUIT_PATH", tmp_path / "circuits.json")
    # No paid search call can be made from a test, whatever the host has configured.
    monkeypatch.setattr(backends, "_tavily_api_key", lambda: "")
