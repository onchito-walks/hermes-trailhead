# Test isolation from the operator's live Hermes home

Status: **fixed and verified 2026-10-28** (local commit; no push).

## The defect (found by running the suite, not by reading it)

`pytest -q` was green only in a shell whose Hermes home was configured and
healthy. Measured on this host, same commit:

| Environment | Result |
|---|---|
| `HOME=<home>` (no config, stale circuits) | **20 failed**, 1125 passed |
| `HERMES_HOME=<hermes-home>` (live .env + live circuits) | **1 failed**, 1144 passed |
| `HERMES_HOME=<empty temp dir>` | 1145 passed |
| `HERMES_HOME=<hostile temp dir>` (open circuits for 24 backends, paid `TAVILY_API_KEY`, `GITHUB_TOKEN`, `config.yaml`) | 1145 passed, 1 order-dependent failure (see residuals) |

Root cause: every backend resolves real host state — the circuit-breaker file
`<hermes home>/state/trailhead-circuits.json`, paid/search keys in
`<hermes home>/.env`, and the operator's `config.yaml`. The old `conftest.py`
patched two attributes per test, so a *live* circuit file still decided whether
a backend was skipped, and a configured key still made the paid Tavily path
reachable from a test.

Consequences beyond flaky tests:

- A test run **wrote** failures into the operator's live circuit file, which
  could suppress a real lane for the next 5 minutes on that host.
- With `TAVILY_API_KEY` configured, tests could reach a paid API.

## Fix

`tests/conftest.py` now points the whole session at a throwaway `HERMES_HOME`
before any `hermes_trailhead` import, so module-level paths (circuit file,
config, `.env`) are per-run. `TRAILHEAD_TEST_HERMES_HOME=<path>` opts into an
explicit home instead. `tests/test_suite_isolation.py` asserts the invariant:
resolved home is not the operator's, and the circuit path follows it.

## Verification

- Hostile-home run: 1145 passed; hostile home gained no state files.
- `<hermes-home>/state/trailhead-circuits.json` SHA256
  identical before and after a full suite run (`13e15ee7…a94bd0`): the suite no
  longer writes live operator state.
- No paid call is reachable from the suite: the throwaway home has no `.env`.

## Residuals (not waived)

- `tests/test_search.py::test_execute_gap_lane_keeps_discovery_only_caveat`
  failed once under the hostile home (passes alone and in an empty home). It is
  still sensitive to ambient configuration via the TikTok chain; not yet root
  caused.
- Isolation is environment-level, not a filesystem/process sandbox.
