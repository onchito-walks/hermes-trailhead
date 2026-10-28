"""The suite must never read or write the operator's live Hermes home."""
from __future__ import annotations

import os
from pathlib import Path

from hermes_trailhead import backends
from hermes_trailhead.paths import hermes_state_dir, resolve_hermes_home


def test_hermes_paths_are_isolated_from_the_operator_home():
    home = resolve_hermes_home()
    assert home != Path.home() / ".hermes"
    assert home.name.startswith("trailhead-test-home-") or os.environ.get(
        "TRAILHEAD_TEST_HERMES_HOME"
    )
    # Live circuit state (import-time resolved) follows the throwaway home too.
    assert backends._DEFAULT_CIRCUIT_PATH == hermes_state_dir() / "trailhead-circuits.json"
