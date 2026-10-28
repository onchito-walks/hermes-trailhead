# Maintained fallback in normal research — 2026-10-28

**Follow-up:** [hardening sweep](HARDENING-ACCEPTANCE-SWEEP.md) tightens the
historical count-only rule below: upstream must return more **distinct** URLs
and retain **every native URL** before whole-result replacement. The original
live observation below is historical, not a rerun of that stricter policy.

Scope: `t_1738a820`. The stale brief's disconnected-backend assertion is already
superseded by the existing public fallback in `backends.py` and its default-runtime
regression. This increment closes the remaining **thin native result** case in
`search.execute_action`; no new connector, wrapper, dependency or configuration.

## Routing contract

- Native/free discovery remains first. Full requested budgets do not invoke Reach.
- Zero-hit lanes retain their existing single maintained fallback attempt.
- A nonempty native result below the requested `limit` now gets one public
  maintained fallback attempt. Replace the **whole** result only if the upstream
  returns strictly more valid, lane-filtered URLs. Otherwise keep the native hits,
  engine and attribution; retain the fallback attempt diagnostics.
- No mixing native hits under upstream attribution. Existing text/JSON/report
  attribution continues to apply to the homogeneous selected result.
- Only explicit `TRAILHEAD_AGENT_REACH_BIN` config enables automatic forwarding;
  PATH presence alone does not. Fixture fetches remain closed. Existing public
  routes, isolated temporary homes, no-auth/no-quota gates and per-call item caps
  are unchanged. Instagram/TikTok are not mapped to unsupported/auth-only routes.
- This is a count-based coverage decision, **not** a relevance score. A configured
  thin lane can now incur one extra bounded upstream call (20 s adapter timeout
  plus existing runner grace). It does not impose an aggregate search deadline.
  No additional retries, registry discovery loops or settings were added.

## Independent verification

After reviewing the delegated two-file patch, the parent ran:

```text
env -u TRAILHEAD_DISABLE_ASR .venv/bin/python -m pytest -q
1130 passed in 85.20s
.venv/bin/python -m py_compile hermes_trailhead/*.py  # passed
git diff --check                                    # passed
```

1130 includes concurrent quota-inventory tests, not 1130 tests authored by this
increment. The fallback module itself has 35 passing cases (8 added), covering
replacement, equal/empty/failing upstream preservation, full budgets, exactly-once
zero-hit fallback (including partial upstream returns), and fixture isolation.
ASR veto was unset only for the contract test process, not live calls or config.

## Real public thin-path smoke

Executed using the actual default HTTP fetcher and installed pinned Agent Reach
1.6.0. Credential-shaped environment variables were removed and HOME/HERMES_HOME/
XDG config/cache paths were fresh; ASR was vetoed. This is environment isolation,
**not a filesystem sandbox**.

Controlled fault: native search for `Python typing Protocol` actually returned
three `jina_duckduckgo` leads; the chain result was deliberately restricted to its
first real hit. No response payload or upstream result was fabricated. Normal
`execute_search(..., limit=3)` then invoked the real public maintained adapter:

- selected `agent_reach_web_search`, reported upstream `exa`, three actual leads;
- URLs: `https://typing.python.org/en/latest/spec/protocol.html`,
  `https://docs.python.org/3/library/typing.html`, `https://peps.python.org/pep-0544/`;
- attribution: `Agent Reach (third-party CLI), forwarded by Hermes Trailhead`;
- 3299 ms in-process / 3400 ms outer process, exit 0, no stderr;
- attempts retain native engines followed by the single attributed upstream call.

This verifies real upstream recovery under an explicitly injected thin-result
condition, **not** a naturally occurring source outage, ranking quality or full
artifact completeness. Raw run: Jr scratch `t_1738a820-thin-live.json`.

## Comparable cold V2EX canary (separate workload)

Used existing `compare --case forum-v2ex-topic --timeout 20` with fresh separate
homes, stripped credential/session/proxy environment and killable equal 20-second
per-side deadlines. Generated `2026-10-28T17:17:32Z`:

| Tool | Status | Wall latency | Cleaned chars | Backend |
|---|---|---:|---:|---|
| Trailhead | ok | 325 ms | 13680 | forum |
| Agent Reach 1.6.0 | ok | 1649 ms | 15093 | v2ex-api |

Both returned text. This URL canary does **not** enter thin search routing and
therefore cannot measure its incremental overhead. Its timing reverses the earlier
single sample where upstream was faster; neither sample establishes speed parity
or superiority. Resource accounting beyond wall latency was not measured here.
Raw run: Jr scratch `t_1738a820-compare.json`.

No account access, credential/security changes, paid calls, pushes or publication.
`o.txt` remains outside this change. Whole-product acceptance, genuine multi-day
reliability, human-reviewed relevance and authenticated/quota parity remain open.
