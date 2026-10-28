# Maintenance follow-up — declared types, discovery reuse, shared deadline

Scope: the three findings left open by
[`MAINTENANCE-REVIEW.md`](MAINTENANCE-REVIEW.md) — F7 (declared `bool`/`float`
parameters unusable), F9 (one registry subprocess per fallback invocation) and
F10 (fixed 35 s discovery budget) — in
`hermes_trailhead/reach_backend.py` and the fallback builder in
`hermes_trailhead/backends.py`.

Closed 2026-10-28. No commits, no pushes, no credentials, no paid or
authenticated calls, no publication. Every number below was produced locally
with a stub executable plus an injected runner.

## Verified state

```bash
.venv/bin/python -m py_compile hermes_trailhead/*.py      # ok
.venv/bin/python -m pytest -q                             # 865 passed, 0 failed (final run)
.venv/bin/python -m pytest -q tests/test_maintenance_followup.py   # 53 passed
.venv/bin/python -m hermes_trailhead gauntlet             # 100/100, 4 pass, 0 fail
.venv/bin/python -m hermes_trailhead reach --format json  # engine parses, not_installed here
```

The suite is shared with sibling work in the same tree, so the tree-wide count
grows between runs (838 → 865 while this change was being verified); 865 is the
final whole-tree run with this change in place, of which this change adds the 53
cases (22 test functions) in `tests/test_maintenance_followup.py`.
`tests/test_maintenance_followup.py` run on its own: 53 passed.

## Measurement method

The "before" column is the tree at `HEAD` (`git archive HEAD | tar -x -C
/tmp/th-before`, which is byte-identical to the working copy before this
change), imported through `PYTHONPATH` in a **separate process** so the
process-wide cache cannot leak between runs. The "after" column is the working
tree, measured the same way. Both runs use one stub executable, an injected
runner, no network.

Reproduction stub for both probes:

```python
class Runner:                     # records what it was asked to do
    def __call__(self, argv, *, timeout, env):
        kind = "channels" if argv[1:2] == ["channels"] else "action"
        self.calls.append({"kind": kind, "timeout": timeout})
        delay = self.slow_channels if kind == "channels" else self.slow_action
        if delay > timeout:                     # faithful to _default_runner
            time.sleep(timeout); raise subprocess.TimeoutExpired(argv, timeout)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload(kind)), stderr="")
```

## Findings

| ID | Severity | Area | Status |
|---|---|---|---|
| F7 | low | `bool`/`float` parameter values rejected as "must be a string" | **fixed** |
| F8 | low | Literal shell markers / narrowed 801–2000-char band | open (out of scope) |
| F9 | low | One registry subprocess per fallback invocation (per action) | **fixed** |
| F10 | info | `registry()` used a fixed 35 s budget regardless of `timeout` | **fixed** |

### F7 — declared `bool`/`float` parameters are coerced, not rejected (fixed)

`_coerce_params` routed every non-`int` parameter through `_validate_str`, so a
registry that declares `bool`/`float` produced a diagnostic about Trailhead's
own plumbing ("must be a string") for a perfectly usable value. Measured on a
declared `bool`/`float` action:

| input | before | after |
|---|---|---|
| `exact=True` | `invalid_params: parameter 'exact' must be a string` | forwarded `--exact true` |
| `exact="true"` | forwarded `--exact true` | unchanged |
| `weight=3.5` | `invalid_params: parameter 'weight' must be a string` | forwarded `--weight 3.5` |
| `weight=float("inf")` | `must be a string` (wrong reason) | `invalid_params: parameter 'weight' must be finite` |

Rules, all in one place (`_coerce_value` → `_validate_int` / `_validate_float` /
`_validate_bool` / `_validate_str`):

* **bool** — a native `bool` becomes `true`/`false`; the strings
  `true/false/yes/no/1/0` (case- and whitespace-insensitive) are accepted and
  canonicalised. `1`, `0`, `1.0`, `"maybe"`, a list and a mapping are refused —
  a truthy value must not silently switch a flag on.
* **float** — `int`/`float` and decimal strings (`[+-]?digits[.digits][e±n]`)
  are accepted; `3.0` is spelled `3` so an upstream parsing with `int` or
  `float` reads the same value, `3.5` stays `3.5`. `nan`, `±inf`, `1e999`,
  `"1_000"`, `"0x10"`, `True` and `""` are `invalid_params`, and values beyond
  `MAX_FLOAT_PARAM` (`1e12`) are `out of bounds`. Non-finite input is rejected
  *before* it reaches `build_argv`, so it can never be forwarded as a token.
* **str / int unchanged** — a `bool` or an `int` handed to a `str` parameter is
  still `must be a string`; a `float` or a `bool` handed to an `int` parameter
  is still `must be an integer`; the `limit` 1–50 clamp and the
  `leading '-'`/control-character/URL-scheme rules are untouched.

Tests (10 functions, 41 cases): `test_bool_param_accepts_native_booleans`,
`test_bool_param_accepts_documented_string_spellings`,
`test_bool_param_rejects_truthy_non_booleans`,
`test_float_param_accepts_finite_numbers`,
`test_float_param_rejects_non_finite_values`,
`test_float_param_rejects_non_numbers`, `test_float_param_is_bounded`,
`test_str_and_int_policy_is_unchanged`, `test_str_and_int_happy_path_is_unchanged`,
`test_required_bool_and_float_are_forwarded_after_the_terminator`.

Note: a *negative* float is legitimate (it follows `--name`), so the
`leading '-'` rule stays a `_validate_str` rule only.

### F9 — one discovery read per configuration, not per adapter (fixed)

`execute_backend_chain`/`run_reach_search_fallback` build a fresh adapter per
action, and every adapter ran `agent-reach channels` on first use. A five-lane
fallback sweep therefore spent five subprocesses on discovery before any
search. Measured on the five fallback lanes (`web`, `github`, `reddit`, `x`,
`youtube`) with one configured executable:

| measurement | before | after |
|---|---|---|
| `channels` subprocesses for 5 fallback invocations | **5** | **1** |
| action invocations in the same sweep | 5 | 5 |
| lanes that produced an attributed result | 5 | 5 |

Design (deliberately not "share the adapter"):

* The cache lives at module scope as
  `_REGISTRY_CACHE: OrderedDict[tuple, ReachRegistry]`, bounded to
  `REGISTRY_CACHE_ENTRIES = 8` entries with LRU eviction and a `threading.Lock`
  around reads/writes. Discovery itself runs outside the lock; a concurrent
  duplicate read is allowed and simply overwrites.
* Key = `(abspath(executable), public_mode, env_identity, runner)`.
  * `env_identity` is a truncated SHA-256 of the sorted env override — the
    override can carry an upstream credential on the authenticated path and a
    cache key is exactly the sort of value that ends up in a `repr`; the digest
    identifies the configuration without echoing it.
  * **Public and authenticated discovery never share an entry.** The child runs
    with a different `HOME` (throwaway vs operator), so the inventory is
    discovered per mode; a public call cannot read an entry an authenticated
    read produced.
  * `runner` is in the key because it *is* the discovery seam: an injected
    runner (tests, doctor) must never read a registry a different runner
    produced. Production uses one `_default_runner`, so this costs nothing
    there and keeps test isolation honest.
* Only the parsed and validated `ReachRegistry` is shared. Consent flags, HOME
  mode, `max_items` and `timeout` remain per adapter, and the fallback keeps
  building a public-only adapter per call (`build_reach_search_adapter`
  docstring now says why).
* `refresh=True` bypasses the cache and replaces the entry; a failed or
  malformed discovery is never cached (so a broken CLI is retried by the next
  call); `clear_registry_cache()` drops the process cache for a caller that
  knows the upstream channel set changed.

Tests (8): `test_five_lane_fallback_sweep_discovers_channels_once`,
`test_discovery_is_shared_across_adapter_instances`,
`test_public_and_authenticated_discovery_are_not_shared`,
`test_a_different_env_identity_is_a_different_cache_entry`,
`test_refresh_bypasses_the_process_cache`, `test_failed_discovery_is_not_cached`,
`test_registry_cache_is_bounded`,
`test_cache_key_does_not_carry_credential_shaped_config`.

Residual behaviour, stated rather than hidden: within one process the cached
inventory masks an upstream channel-set change until `refresh=True` /
`clear_registry_cache()` (a long-lived server sees the inventory it started
with). That is the same staleness the per-instance cache already had, now
process-wide; the doctor probe and CLI reads still re-read on `refresh=True`.

### F10 — discovery shares the caller's wall clock (fixed)

`registry()` called the runner with `timeout_grace + 30.0` whatever the caller
asked for, and `execute()` then gave the action its own full
`timeout + grace` — so one call could occupy `30 + timeout + grace` while
advertising `timeout`. Measured with `timeout=1`, `timeout_grace=0.2`
(call deadline 1.2 s) and a discovery read that takes 2 s:

| measurement | before | after |
|---|---|---|
| `timeout` requested for `channels` | **30.2** | **1.2** (= remaining budget) |
| `timeout` requested for the action | 1.2 | 1.179 (grace preserved) |
| action started? | yes | **no** — budget already spent |
| wall clock of `execute()` | **2.001 s** | **1.201 s** (deadline 1.2 s) |
| result | `ok` | `timeout` (`timed_out=True`) |
| fast discovery (`0.02 s`), action timeout | 1.2 | 1.179 |

Mechanism:

* `execute()` takes one wall clock: `started = time.monotonic()`,
  `deadline = started + effective_timeout + timeout_grace` (the action's own
  `--timeout` argv value is unchanged, and the runner grace is still available
  in the normal case — 1.179 s of a 1.2 s deadline above).
* Discovery is capped at `min(timeout_grace + REGISTRY_DISCOVERY_BUDGET,
  deadline - now)`; `REGISTRY_DISCOVERY_BUDGET = 30.0` keeps the old ceiling for
  a read with no action to share a budget with (CLI/doctor), and the deadline
  always wins. A deadline already spent raises `RegistryError` *before* a
  process is spawned.
* The action's runner timeout is `deadline - now`, not `timeout + grace`, so a
  slow discovery cannot push the call past its deadline. If that remainder is
  ≤ 0 the action is **not started** and the result is `timeout` with an
  explicit message.
* A discovery read killed by the shared budget reports `timeout` (with
  `timed_out=True`), not `registry_invalid`: the call ran out of wall clock,
  the registry was not malformed. A genuine registry failure with budget left
  still reports `registry_invalid`.
* The deadline reaches `registry()` through `_registry_for_action(deadline)`
  and an instance field, *not* a new `registry()` keyword, so a wrapper that
  overrides `registry(refresh=...)` (the doctor probe, the existing
  `test_spawn_failure_is_a_process_error` double) still gets the bounded read
  and the public signature is unchanged. The field is restored in a `finally`.

Tests (4): `test_discovery_budget_never_exceeds_the_call_deadline`,
`test_action_keeps_the_runner_grace_after_a_fast_discovery`,
`test_registry_read_outside_a_call_keeps_its_own_ceiling`,
`test_discovery_is_not_spawned_after_the_deadline_is_spent`.

## Not changed on purpose

* **F8** (literal shell markers, zero-width spaces, the narrowed 801–2000-char
  single-language band) is untouched: it needs refreshed fixtures from a new
  live sweep, not a wider rule.
* Public-mode isolation, ASR veto ordering, quota gating, route verification,
  the read-only allowlist and the bounded runner are unchanged by this work.
* No new env knob: the cache and the deadline are behaviour, not configuration.

## Hand-offs outside this change's ownership

* `docs/agent-reach-backend.md` says the validated registry "is cached for the
  process lifetime (`refresh=True` re-reads)" — now literally true, but the
  section should also state that discovery shares the action's wall clock and
  that public/authenticated discovery do not share an entry. Two sentences.
* Same file, "Unsafe positionals rejected" — a value starting with `-` is
  refused for `str` target parameters only; a declared `float` may legitimately
  be negative because it follows `--name` rather than `--`. Worth one clause.
* `docs/MAINTENANCE-REVIEW.md` still lists F7/F9/F10 as `open`; its owner should
  flip those three rows to `fixed` and link here.
