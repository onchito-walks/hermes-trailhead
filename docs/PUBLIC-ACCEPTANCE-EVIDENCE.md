# Public acceptance evidence (bounded, repeatable)

Status: **observations only. Superiority is NOT established by this document.**
Machine-readable record: [`evidence/public-acceptance.json`](evidence/public-acceptance.json).
Pre-fix snapshot of the previous run: [`evidence/public-acceptance-before.json`](evidence/public-acceptance-before.json).
Harness: [`scripts/evaluate_public_acceptance.py`](../scripts/evaluate_public_acceptance.py).

This run exists to replace self-grades with something a reviewer can re-execute:
a frozen multilingual outcome manifest, explicit artifact checks on the text each
tool actually returns, repeated *matched* public workloads, and externally
measured wall clock / peak RSS. The manifest was **not** edited between the two
runs; only the code under test changed, and both JSON records carry the same
`manifest` block.

## What was measured

| Item | Value |
| --- | --- |
| Trailhead side | existing `python -m hermes_trailhead compare` (no new comparator) |
| Agent Reach side | pinned 1.6.0, `direct_url` = `github.com/Panniantong/Agent-Reach/archive/14c213405669414492bda0f8d52cc6531d062c45.zip` (GitHub archive at the pinned commit, **not** a PyPI wheel), 14 channels reported |
| Cases | 3 public, no credentials: `docs-python-typing` (en), `github-requests-readme` (en), `forum-v2ex-node` (zh-Hans) |
| Repetitions | 3 × cold + 3 × warm = 6 matched runs, 18 paired case executions |
| Budget | equal 25 s killable wall limit per side per case; `TRAILHEAD_DISABLE_ASR=1`; zero auth/paid/login calls |
| Isolation | `comparative.build_sandbox` env tree for both sides; environment isolation only, **not** a filesystem sandbox |
| Measurement | `/usr/bin/time -v` around the whole compare process (external wall + process-level peak RSS); per-case durations from the compare report |
| Host | single Linux aarch64 host, 4 CPUs, 24 GB RAM; one network moment on 2026-10-28 |
| Record | `generated_at` 2026-10-28T13:23:15Z, working tree at `2fb3847` + uncommitted changes |

Reproduce:

```bash
.venv/bin/python scripts/evaluate_public_acceptance.py \
  --agent-reach /path/to/agent-reach \
  --scratch /tmp/public-acceptance --repeats 3 \
  --out docs/evidence/public-acceptance.json
```

## Outcome parity (matched outcomes, per case)

All 18 paired executions returned `parity_verdict = both_evidence`. That is parity
on *whether each side returned usable evidence*, not parity on the requested
outcome and not a completeness result.

| Case | Trailhead | Agent Reach | Median ms (TH / AR) |
| --- | --- | --- | --- |
| docs-python-typing | ok / evidence | ok / evidence | 683.5 / 663.0 |
| github-requests-readme | ok / evidence | ok / evidence | 139.0 / 304.0 |
| forum-v2ex-node (zh) | ok / evidence | ok / evidence | 502.0 / 286.5 |

Medians are over the 6 matched runs. No aggregate winner is computed or implied:
the cases differ in scope and access path.

## Artifact markers (presence checks, not completeness proof)

Each case freezes a handful of markers for the requested outcome — install
command, class entries, topic links. A marker is present or absent; there is no
length threshold and no partial credit. **Passing markers do not prove the tool
returned the complete page or the complete README** — they prove the sampled
strings were found. Per-marker offsets, regions and contexts are in the JSON
(`completeness[*].sides[*].checks`, `marker_provenance`).

| Case | Side | Markers present | Missing | Distinct topic URLs |
| --- | --- | --- | --- | --- |
| docs-python-typing | Trailhead | 5/5 | — | — |
| docs-python-typing | Agent Reach | 5/5 | — | — |
| github-requests-readme | Trailhead | 5/5 | — | — |
| github-requests-readme | Agent Reach | 3/5 | `readme_intro`, `readme_license` | — |
| forum-v2ex-node | Trailhead | 3/3 | — | 20 |
| forum-v2ex-node | Agent Reach | 3/3 | — | 10 |

Where to be precise about what that means:

- **GitHub README, Trailhead:** the repo-root read now fetches the README whole
  from GitHub's public README endpoint (`Accept: application/vnd.github.raw`,
  3,118 characters returned; previously a 1,405-character excerpt). Install and
  usage markers match README body text. But two of the five markers are satisfied
  by **repository metadata, not README prose**: `readme_license` matches
  `License: Apache License 2.0` emitted from the repo API's `license.name`
  field, and `readme_intro` matches the repository description. The README body
  returned here does not contain the word `Apache`. So the license artifact is
  provenance-reported metadata, and this case is **not** evidence that the README
  states its license.
- **GitHub README, Agent Reach:** 2,939 characters with install and usage, no
  license and no intro line; 3/5 markers.
- **V2EX node listing, Trailhead:** titles, Chinese prose and 20 distinct topic
  URLs. The earlier run returned zero topic URLs; that gap is closed on this
  host/day.
- **V2EX node listing, Agent Reach:** 3/3 markers with 10 distinct topic URLs.
- **docs-python-typing:** 5/5 markers on both sides. This is a sampled-set result
  only — no claim is made that either side returned the exact complete page, and
  the marker set does not cover the whole reference.

## Shipped `read` CLI outcomes

The harness also runs the public command a user invokes,
`python -m hermes_trailhead read <url> --format json`, per case (same sandbox env,
25 s timeout). Trailhead's native read path and the CLI agree on all three cases:

| Case | ok | exit | returned chars | truncated | markers | error |
| --- | --- | --- | --- | --- | --- | --- |
| docs-python-typing | true | 0 | 126,310 | false | 5/5 | — |
| github-requests-readme | true | 0 | 3,118 | false | 5/5 | — |
| forum-v2ex-node | true | 0 | 5,709 | false | 3/3 | — |

`read` is native-only (`policy.agent_reach = not_used`) and reports
`evidence.usable = true` for all three. The Agent Reach side has no separate
wrapper here: its probe already *is* the upstream CLI (`agent-reach read`,
`agent-reach github read`, `agent-reach v2ex node`).

## Speed and process resources

Per matched 3-case run, `/usr/bin/time -v` around one compare process that runs
**both** sides:

| Run kind | wall s (3 repeats) | peak RSS kB |
| --- | --- | --- |
| cold | 3.381, 3.122, 3.845 | 36,360 / 36,608 / 36,592 |
| warm | 3.430, 2.771, 2.989 | 38,416 / 36,932 / 36,808 |

Median cold wall 3.38 s, warm 2.99 s. The RSS figure is the peak of the **entire
compare process**, which contains Trailhead extraction plus the Agent Reach
child process. It cannot be attributed to either tool, so **no per-tool memory
comparison is made or implied** and no per-tool RSS parity is claimed. These are
single-host numbers over three pages and do not predict a large sweep.

## Dependencies / on-disk setup

| Side | venv size | distributions | interpreter |
| --- | --- | --- | --- |
| Trailhead `.venv` | 118.7 MB | 27 | CPython 3.11.15 (uv-managed) |
| Agent Reach eval venv | 37.6 MB | 14 | CPython 3.14.7 (uv-managed) |

The Trailhead figure includes the project's test/dev extras, so it is **not** a
like-for-like runtime footprint, and install *time* was not re-measured (both tools
were already installed). Treated as context, not as a competitive result.

## What changed since the pre-fix run

Same manifest, same three cases, same host:

| Case / side | Before | Now |
| --- | --- | --- |
| github README / Trailhead | 3/5 (`readme_install`, `readme_license` missing), README excerpt 1,405 chars | 5/5 markers, full README 3,118 chars, license marker from repo metadata |
| github README / Agent Reach | 3/5 | 3/5 (unchanged) |
| V2EX node / Trailhead | 2/3, 0 topic URLs | 3/3, 20 topic URLs |
| V2EX node / Agent Reach | 3/3, 10 URLs | 3/3, 10 URLs |
| docs / both | 5/5 | 5/5 (unchanged) |

The only remaining recorded gap is Agent Reach on the GitHub README
(`readme_intro`, `readme_license`).

## Gaps this run does not close

- 3 of **40** reference actions ([product inventory: `parity_inventory()["counts"]["actions"]` = 40, recorded in the JSON](evidence/public-acceptance.json)), public only. No authenticated workloads, no account lifecycle, no transcription/podcast (ASR deliberately off), no paid paths.
- Artifact markers are presence checks: they do not establish that any page or
  README was returned complete, and the docs-case marker set is a sample, not a
  full-page comparison.
- The GitHub license marker is satisfied by repository metadata, not README
  text; README licensing behaviour is not measured here.
- No per-tool memory attribution: GNU time measures the combined compare process.
- No clean-machine (macOS/Windows) onboarding; no install-time measurement.
- One host, one day, one network moment. Warm runs reuse only the sandbox tree;
  origin/CDN and backend caches were not controlled.
- Environment isolation is not a filesystem sandbox and no credential was supplied
  to either side.

Conclusion: with the frozen manifest unchanged, Trailhead now passes all sampled
markers on all three public cases (5/5, 5/5, 3/3), and the previous V2EX
missing-links deficit is not reproducible on this run. Agent Reach passes 2 of 3
cases on markers. These are presence observations on three public pages, not
completeness proof and not a claim of superiority in any dimension.
