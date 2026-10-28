# Maintenance & correctness review — reach adapter, fallback, extraction

Scope: the uncommitted work in `hermes_trailhead/reach_backend.py`,
`hermes_trailhead/backends.py` (optional Agent Reach search fallback) and
`hermes_trailhead/extract.py` (`classify_page_shell` and its call sites).
Reviewed 2026-10-28; no commits, no credentials, no paid calls, no publication.

Method: read the full diffs, replay the 40-action live ledger
(`trailhead-40-action-live.json`, 20 `returned_items` rows) through the current
normaliser, and probe each safety claim with a local stub executable + injected
runner. Every defect below was reproduced before it was fixed, and each fix is
pinned by `tests/test_review_regressions.py`.

## Status update — 2026-10-28 (follow-up landed)

F7, F9 and F10 were fixed after this review by
[`MAINTENANCE-FOLLOWUP.md`](MAINTENANCE-FOLLOWUP.md) (commit `b20d4e3`).
That document owns the measurements, the exact coercion rules, the cache key
and the shared-deadline design; this review keeps its original pre-fix
observations, dated as the review record, and does not restate them as new
evidence.

Current whole-tree state for this update: `928 passed`, `py_compile` clean,
gauntlet 100/100 (parent-verified 2026-10-28). Run the suite with
`TRAILHEAD_DISABLE_ASR` unset — with it exported, 15 ASR/transcription tests
fail because the veto short-circuits them.

## Verified state

```bash
.venv/bin/python -m py_compile hermes_trailhead/*.py      # ok
.venv/bin/python -m pytest -q                             # 721 passed, 0 xfailed, 0 failed  (review-time run; current tree: 928)
.venv/bin/python -m hermes_trailhead gauntlet             # 100/100 (4 lanes, 0 fail)
.venv/bin/python -m hermes_trailhead reach --format json  # 40 actions / 14 channels, 5 live
```

The suite is shared with sibling work in the same tree, so the collected count
grows as those land; the pass/fail split above is from the run that closed F5
and F6.

40-action ledger replay (from the first pass): only the three known false
positives are withheld (`reddit read` → `blocked`, `xiaohongshu read` →
`missing_page`, `linkedin read` → `missing_page`); no other row loses an item
and no field is clipped. The previously-claimed result — 20 `returned_items`,
3 false positives — became **17 rows that returned items** plus 3
`content_unusable`. An earlier revision of this paragraph called those 17 rows
"usable"; that was an overclaim. A returned item means the row survived
normalisation with at least one item — it is not a usability, relevance or
completeness verdict, and the replay artifact records `completeness:
not_assessed` / `freshness: not_assessed` on every row
([`evidence/action-sweep-replay.json`](evidence/action-sweep-replay.json)).
The ledger file itself is not in the tree, so F6 was not replayed against it: the
empty-body rule can only lower that returned-item count (a `read` row with no text now
counts as unusable), never raise it.

## Findings

| ID | Severity | Area | Status |
|---|---|---|---|
| F1 | high | Untrusted item fields unbounded after normalisation | **fixed** |
| F2 | medium | `max_items=inf` raised `OverflowError` through `execute()` | **fixed** |
| F3 | medium | Search fallback forwarded a raw `limit`, failing above 50 | **fixed** |
| F4 | medium | Long body with two same-language 404 phrases condemned as a shell | **fixed** |
| F5 | medium-high | Output cap applied after full capture; timeout orphans grandchildren | **fixed** |
| F6 | low | Body read with empty text still reports `ok: true` | **fixed** |
| F7 | low | `bool`/`float` parameter values rejected as "must be a string" | **fixed** — [follow-up](MAINTENANCE-FOLLOWUP.md) |
| F8 | low | Shell markers are literal substrings; 801–2000-char single-language bodies narrowed | open |
| F9 | low | One registry subprocess per fallback invocation (per action) | **fixed** — [follow-up](MAINTENANCE-FOLLOWUP.md) |
| F10 | info | `registry()` uses a fixed 35 s budget regardless of `timeout` | **fixed** — [follow-up](MAINTENANCE-FOLLOWUP.md) |

### F1 — untrusted item fields were forwarded unbounded (fixed)

`_normalize_items` bounded `text` (4000 chars) and `raw` (2000), but `title`,
`author`, `published_at`, `url` and the upstream `backend` label passed straight
through. A single item with 200 KB fields produced a **701 567-byte** payload
from a payload inside the 4 MB input cap, i.e. the documented output bound was
not an output bound at all — and that text is echoed into provenance, error
messages and the CLI.

Fix: `MAX_URL_CHARS = 2048`, `MAX_BACKEND_CHARS = 128`; `_clip()` bounds every
forwarded string at `MAX_VALUE_CHARS`; the `backend` label is clipped **and**
redacted before it reaches `provenance`. Clipping is counted and reported
(`N item field(s) were truncated at Trailhead's output bound`) instead of
silently shortening evidence. Same hostile payload now yields **6 962 bytes**.

Tests: `test_oversized_item_fields_are_clipped_and_reported`,
`test_short_item_fields_are_untouched_and_not_flagged`,
`test_oversized_reported_backend_is_clipped_and_redacted`.

### F2 — non-finite `max_items` escaped as an exception (fixed)

`execute()` documents "never raises for user input", but `_bounded_items` only
caught `TypeError`/`ValueError`; `int(float("inf"))` raises `OverflowError`, so
`execute(..., max_items=float("inf"))` raised. The constructor had the same
hole. Fix: `OverflowError` is caught → `invalid_params` result; constructor
clamps to `MAX_ITEMS` via `_bounded_items` (one clamp path instead of two).

Tests: `test_non_finite_max_items_is_an_error_result_not_an_exception`,
`test_non_finite_constructor_budget_falls_back_to_the_default`.

### F3 — the fallback could not honour its own bound (fixed)

`run_reach_search_fallback` sent `{"query": q, "limit": limit}` untouched while
`AgentReachBackend` rejects `limit > MAX_LIMIT (50)`. A normal `--limit 200`
search therefore turned into `invalid_params: limit must be between 1 and 50`
once the native chain came back empty — a diagnostic about Trailhead's own
budget, not about the source. Fix: `_reach_item_budget()` clamps once and is
used by both `build_reach_search_adapter` and the fallback.

Tests: `test_search_fallback_clamps_an_oversized_limit`,
`test_search_fallback_survives_a_non_numeric_limit`.

### F4 — the classifier contradicted its own documented contract (fixed)

`docs/agent-reach-backend.md` promises "a long article that merely *discusses*
404 pages is kept". The code condemned any body over 800 chars containing two
distinct marker phrases, so a real docs page saying "a page not found response
that returns 200" and "says this page doesn't exist in the copy" was classified
`missing_page`: extraction reported failure and scoring marked it
`PLATFORM_SHELL`, discarding legitimate evidence.

Fix: markers are now grouped by language
(`_MISSING_PAGE_MARKERS_BY_LANG`, flat `_MISSING_PAGE_MARKERS` kept). A short
body still needs one marker; a long body needs corroboration — **two languages**
(LinkedIn's multilingual 404: 12 languages at 3 961 chars) or **three distinct
phrases** (a plain English 404 template). One shared classifier, so forwarding,
extraction and scoring cannot drift apart.

Tests: `test_long_docs_page_quoting_two_english_markers_is_not_a_shell`,
`test_english_only_404_template_with_several_markers_is_still_a_shell`, plus the
existing recorded-shell fixtures, which still classify `blocked` /
`missing_page`.

### F5 — output bounds and process lifetime are enforced during the call (fixed)

Two measured defects in the default runner:

* `subprocess.run(capture_output=True)` buffered first and was checked later: an
  8 MB stdout call returned `8 388 608` bytes for a `4 000 000`-byte cap. A
  looping or hostile upstream was a memory problem before it was a rejected
  result.
* `subprocess.run(timeout=...)` killed only the direct child. Probe: a stub that
  spawned `sleep` and recorded its pid left the grandchild **alive** after the
  timeout — a leaked browser/downloader per timed-out call.

Fix: `_default_runner` is now a `Popen`-based bounded runner, reusing the
pattern already proven in `comparative.run_killable` /
`comparative._kill_process_group` rather than inventing a new daemon:

* **Capture is capped while draining.** Both pipes are drained by this process
  and the keep-buffers stop at `MAX_OUTPUT_BYTES` (stdout) and
  `MAX_STDERR_BYTES = 65 536` (stderr); past that the stream is read and
  discarded, so at most one cap of each stream is ever held. Crossing the stdout
  cap kills the producer immediately and sets `overflow=True` on the returned
  `BoundedCompletedProcess`; `_interpret` and `registry()` report that as
  `malformed_output: ... oversized` instead of trying to parse the prefix.
* **POSIX: the whole group dies.** `start_new_session=True` makes the child's pid
  its process-group id, so `os.killpg(pid, SIGKILL)` reaches descendants. The
  group is killed on timeout, on stdout overflow, and when the direct child
  exits while something it spawned still holds an inherited pipe (1 s grace,
  then kill) — that last case used to hang the drain for the full timeout and
  then leak the helper.
* **Drain strategy.** `selectors` over both pipes on POSIX; reader threads where
  `selectors` cannot watch pipes (Windows). Same caps, same kill decisions.
* **The wall clock still owns the call.** On expiry the group is killed and
  `subprocess.TimeoutExpired` is raised, so `execute()`'s existing `timeout`
  result contract is unchanged; an overflow is deliberately *not* a timeout.

Measured after the fix (local children, no network):

| probe | before | after |
|---|---|---|
| child writes 12 MB stdout | 8 388 608 B buffered, then rejected | 4 000 000 B kept, producer killed, `oversized` |
| child writes stdout forever | buffered until the 60 s timeout | cap reached, producer killed in well under a second |
| `channels` read writes 5 MB | buffered, then parsed/failed on size | 4 000 000 B kept, `registry_invalid: oversized` |
| child writes 200 KB stderr | buffered in full | 65 536 B kept, valid stdout still parsed |
| `sleep 60`, timeout 1.0 s | ~1 s, grandchild alive | ~1.0 s, group gone |
| child exits, grandchild holds pipe, timeout 30 s | ~30 s, grandchild alive | ~1.3 s, answer returned, grandchild gone |

Windows limits (stated in the runner docstring, not silently assumed): there is
no process group to signal, so only the direct child is killed and a helper it
spawned can outlive the call. The byte caps and the wall-clock budget still
apply.

Tests, all strict (the two `xfail`s are gone):
`test_runner_stops_capturing_at_the_output_cap`,
`test_runner_stops_a_looping_writer_instead_of_hanging`,
`test_runner_bounds_stderr_without_failing_a_chatty_cli`,
`test_thread_drain_fallback_enforces_the_same_caps` (forces the Windows drain on
POSIX so the fallback cannot rot),
`test_runner_raises_timeout_at_the_wall_clock_budget`,
`test_oversized_upstream_output_is_rejected_not_buffered`,
`test_oversized_registry_output_is_rejected_before_parsing`,
`test_timeout_kills_the_child_process_group`,
`test_child_that_exits_while_a_descendant_holds_the_pipe_is_killed`.

`tests/test_reach_backend.py::test_argument_array_has_no_shell_and_minimal_env`
was updated to pin the behavioural contract — argv list, `shell=False`, no
inherited stdin, both pipes owned by the drain, minimal credential-free env,
`start_new_session` on POSIX — through a real `Popen` instead of asserting one
`subprocess.run` call. Which `subprocess` entry point is used was an
implementation detail; the envelope is the contract.

### F6 — a body read with no body text is no longer a successful read (fixed)

`BODY_READ_ACTIONS` items were withheld only when their text *was* a shell. An
item with `text: ""` (and no `raw`) was forwarded, so a `read` could return
`ok: true` with an empty body — a successful read of nothing.

Product decision: an empty body is a **missing artifact**, not a neutral result,
so it is reported as `content_unusable` rather than forwarded or silently
dropped. Implementation: for `read`/`thread`/`comments`, a row with no text
(missing key, `""`, or whitespace only) is withheld with reason `empty_body`.
`raw` is a structured side payload, not a page body, so it cannot make an empty
read usable. When nothing usable remains the result is `content_unusable`
(`reasons: ["empty_body"]`, `withheld_items`, attribution and attempts kept),
and the limitation line names the count (`empty_body=N`). A row that does carry
a body is unaffected, and one empty row cannot hide a usable body behind it.

Untouched by design: search/discovery rows (leads, snippets) and metadata-only
actions (`v2ex user`, `bilibili hot`, `xueqiu search`) keep their empty-text
items — that is their shape, not a failed read.

Tests: `test_body_read_with_empty_text_is_content_unusable`,
`test_body_read_with_missing_text_field_is_content_unusable`,
`test_body_read_with_raw_metadata_but_no_text_is_content_unusable`,
`test_one_empty_row_does_not_hide_a_usable_body`,
`test_search_metadata_items_survive_the_empty_body_rule`; the existing
`test_metadata_actions_keep_empty_text_items` and
`test_read_action_with_metadata_only_items_is_not_flagged` in
`tests/test_reach_content_quality.py` still pass unchanged.

Doc drift to hand off (file outside this change's ownership):
`docs/agent-reach-backend.md` still lists `error.reasons` as only `"blocked"` /
`"missing_page"` and describes the rejection case as "if every row was a
shell". Both now include `empty_body`. That file needs the same two-line update
by its owner; the code and `reach_backend`'s docstring are already accurate.

*Resolved after this review: the current `agent-reach-backend.md` lists
`empty_body` and describes the all-rows-empty case; the sentence above is the
2026-10-28 review record.*

### F7 — `bool`/`float` parameters are unusable as native types (fixed 2026-10-28)

**Closed after this review** — see [F7 in the follow-up](MAINTENANCE-FOLLOWUP.md#f7--declared-boolfloat-parameters-are-coerced-not-rejected-fixed)
for the coercion rules and bounds. The observation below is the pre-fix record.

`_coerce_params` routes every non-`int` parameter through `_validate_str`, so a
declared `bool`/`float` parameter rejects `True`/`3.5` with "must be a string".
Practical impact is nil today (the pinned registry declares only `str`/`int`),
but a future registry declaring `float` would produce a misleading error. Either
document string-only coercion in the registry section or coerce explicitly.

### F8 — literal matching, and the narrowed middle band (open)

Markers are matched as literal substrings after whitespace collapse. Zero-width
spaces or full-width punctuation inside a shell defeat the match; the `blocked`
rule also only applies up to 2000 chars of (already 4000-char-truncated) text.
Separately, F4 intentionally narrowed detection for 801–2000-char
single-language bodies holding exactly two phrases — the trade-off that keeps
real documentation. Suggested follow-up: strip `\u200b-\u200d\ufeff` before
matching and refresh the fixture set from a new live sweep instead of widening
the rules.

### F9 — one registry read per fallback invocation (fixed 2026-10-28)

**Closed after this review** — see [F9 in the follow-up](MAINTENANCE-FOLLOWUP.md#f9--one-discovery-read-per-configuration-not-per-adapter-fixed)
for the per-process cache, its key, and the stale-until-refresh caveat. The text
below is the pre-fix record.

`execute_backend_chain` builds a fresh adapter per action, and each adapter runs
`agent-reach channels` on first use. A five-lane sweep can therefore spend five
subprocess reads on discovery before any search. A per-process adapter cache
keyed by `(executable, limit)` would remove that without changing semantics.

### F10 — `registry()` used a fixed 35 s budget (fixed 2026-10-28)

**Closed after this review** — discovery now shares the caller's deadline; see
[F10 in the follow-up](MAINTENANCE-FOLLOWUP.md#f10--discovery-shares-the-callers-wall-clock-fixed).
The observation below is the pre-fix record.

`registry()` calls the runner with `timeout_grace + 30.0` regardless of the
backend's `timeout`. Defensible (discovery is not a paid call), but undocumented
and unlike the action path. Either document it or derive it from `timeout`.

## Maintainability notes

* **`reach_backend.py` is now ~2.2 k lines** covering policy tables, registry
  parsing, parameter validation, execution, redaction, payload normalisation and
  the pinned parity inventory. Splitting it (`reach_policy.py`,
  `reach_registry.py`, `reach_execute.py`) would help, but "more files" is not
  itself an improvement; do it the next time a subsystem changes materially, not
  as drive-by churn.
* **One classifier, three call sites** is the right shape: `classify_page_shell`
  owns the vocabulary and `extract`, `scoring` and `reach_backend` all defer to
  it. The remaining duplication is in `scoring.py`, which repeats
  `_looks_like_extraction_error(...) or _is_html_shell(...) or
  classify_page_shell(...)` in `assess_evidence` and `score_hit`. Exporting one
  `page_text_is_usable()` predicate from `extract.py` would collapse it; not done
  here because `scoring.py` is outside this task's ownership.
* **Clamping:** `_bounded_items` is now the single item-budget clamp;
  `_constructor_items` and `backends._reach_item_budget` delegate instead of
  re-deriving the arithmetic in three places.
* **Process-kill logic now exists twice, deliberately.**
  `comparative._kill_process_group` and `reach_backend._kill_process_group` are
  behaviourally identical (`os.killpg` on POSIX, `Popen.kill` otherwise); the
  runner could not import the first without editing `comparative.py`, which was
  outside this change. The next change that touches both modules should export a
  single `kill_process_group(popen)` helper instead of a third copy.
* **Docs/code drift** was the root cause of F4: the docstring and
  `docs/agent-reach-backend.md` described a more conservative classifier than
  the code implemented. Behaviour claims about shell detection should be
  asserted in tests, not only prose. F6 closed the same gap from the other side:
  an empty body was neither classified nor reported.
* **Test map:** F1–F4 and F6 are pinned by `tests/test_review_regressions.py`;
  F5 by nine runner tests there (two of them converted from `xfail` to strict
  regressions, no `xfail` left in the file); existing coverage of public-mode
  isolation, ASR veto, quota gating and argv construction lives in
  `tests/test_reach_backend.py`. The subprocess contract test there now asserts
  the *invocation* (argv list, no shell, minimal env, `start_new_session`) rather
  than which `subprocess` entry point is used, so the runner can change again
  without turning a behavioural test red.

## Not changed on purpose

* Public-mode credential isolation (`HOME`/`XDG_*`/`APPDATA` redirected to a
  throwaway directory, no key/token variable in `_ENV_PASSTHROUGH`, no operator
  `HOME` or `TRAILHEAD_AGENT_REACH_HOME` in public mode) — re-read line by line,
  no hole found. The "not a sandbox" caveat is accurate and repeated where it
  matters.
* ASR veto semantics (`asr_disabled` is an OR over the process env and any
  caller mapping, checked before discovery so a refused quota call spawns
  nothing) — correct and already well covered; left untouched.
* The 3-way gate for transcription (quota consent + auth consent + no veto) and
  the route-violation check — correct; no change.
