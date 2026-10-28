"""Keep the suite independent of the operator's live host state.

Backends consult real host state: the circuit-breaker file under the resolved
Hermes home, a Tavily key (and other secrets) in its ``.env``, and whatever
``config.yaml`` the operator runs with.  Left alone, one host can make tests
fail while another passes: an open circuit made 20 search tests report
``blocked``, and a configured Tavily key lets a test reach a paid API.

Every Hermes path resolves through ``HERMES_HOME``, so the whole session runs
against a throwaway home instead of per-test attribute patching.  Set
``TRAILHEAD_TEST_HERMES_HOME=<path>`` when you deliberately need a specific one.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# Set before any test module imports hermes_trailhead: module-level paths such
# as the circuit-breaker file are resolved at import time.
os.environ["HERMES_HOME"] = os.environ.get("TRAILHEAD_TEST_HERMES_HOME") or tempfile.mkdtemp(
    prefix="trailhead-test-home-"
)
atexit.register(shutil.rmtree, os.environ["HERMES_HOME"], True)
