# Clean Linux run 283 — committed HEAD `db6adc1` (Hermes Trailhead 1.1.0)

**Verdict: 11/11 acceptance gates pass.** The committed source installs and runs
in a clean Ubuntu 24.04 arm64 userspace, and the missing-page defect recorded in
[clean-linux-final](CLEAN-LINUX-FINAL.md) now **fails closed**: an anonymous
GitHub nonexistent issue returns rc 1, `error.code:"extraction_error"`, zero
content characters and `evidence.usable:false` instead of GitHub navigation
chrome.

- **Source:** commit `db6adc1a68f0792ef4270576c8ecd171c03cca3a`
  (`fix: preserve bounded full bodies from maintained read backends`)
- **Archive:** `git archive --format=tar db6adc1`, SHA-256
  `48ffdc2de6cc879cabf53f7788a0e0257f4008b1f76810dbc78adc94ce8bc58d`
  (169 entries, 156 files, no `.git`, no untracked `o.txt`)
- **Acceptance:** 11/11 pass, rc 0, failed checks: none
- **Environment:** clean Ubuntu 24.04.4 LTS userspace, `aarch64`, on the shared
  host kernel `7.0.0-1013-oracle` — Linux arm64, **not** macOS or Windows
- **Evidence:** [evidence/clean-linux-run283.json](evidence/clean-linux-run283.json)
  (SHA-256 `642d7508395dd49303783d6d329bd84839b173cd225adee351b59d5ba6dc495a`)

This run reused the existing `harness3.sh` unmodified. The harness contains its
own report generator (`accept.py` + `facts.py`); no extra wrapper was written.

## Artifact, container and installed CLI

The archive was built from the commit, not the working tree, so the untracked
`o.txt` was excluded by construction and verified absent from the tar listing
(`project_has_otxt=no`). The container received **only** the source tar and the
harness as read-only file mounts, plus a results directory. No host home,
config, credentials, binaries or project checkout were mounted.

| Item | Value |
|---|---|
| Docker server | 29.1.3 |
| Image | `ubuntu:24.04`, image ID `sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90` |
| Image OS / arch | Ubuntu 24.04.4 LTS / `arm64` |
| Container | `76b867caa9b9` (`trailhead-clean-run283`), removed on exit |
| Limits | `--cpus 2 --memory 2g --memory-swap 2g --pids-limit 256` |
| Capabilities | `cap-drop ALL` + `SETUID,SETGID,CHOWN,DAC_OVERRIDE,FOWNER`; `no-new-privileges` |
| Mounts | `/src/source.tar:ro`, `/src/harness3.sh:ro`, `/work/results:rw` |
| Env | `env -i`, empty `HOME=/work/home`, `TRAILHEAD_DISABLE_ASR=1`; `PYTHONPATH`, `VIRTUAL_ENV`, `GITHUB_TOKEN`, `GH_TOKEN` unset |
| Python | image ships none; Ubuntu `python3 3.12.3` + `python3-venv`/`pip` installed **inside** the container |
| Runtime | 27 s wall clock, 20 s from start to working CLI |

- Fresh venv; `pip install /work/project` exited 0.
- `dependencies = []`: **zero third-party runtime dependencies**. Runtime venv
  has 2 distributions (`hermes-trailhead 1.1.0`, `pip 24.0`); `pip freeze` shows
  only `hermes-trailhead @ file:///work/project`.
- Wheel: `hermes_trailhead-1.1.0-py3-none-any.whl`, 212,132 bytes,
  SHA-256 `12aca965948fd8f89d18a7738f5d22e21d7fe142f464b825fcc20590817c4867`.
- **Real installed CLI:** `/work/venv/bin/hermes-trailhead` exists and executed;
  `--version` → `hermes-trailhead 1.1.0` (rc 0), `--help` rc 0 with all
  documented surfaces.
- Integrity: installed `cli.py` is byte-identical to the archived file, both
  SHA-256 `267fa25f3bbae3544bb6802ffbb62e45f0d323d7da4f4bbc7fcbd9d2dacab4b7`.

## Acceptance matrix

| # | Criterion | Result |
|---|---|---|
| A1 | Fresh-venv install; 0 runtime deps; installed bytes == archive | **PASS** |
| A2 | `--version` → `hermes-trailhead 1.1.0`, rc 0 | **PASS** |
| A3 | `--help` exposes read/reach/reach-call/doctor/search/routes/score/compare | **PASS** |
| A4 | Public `read` usable, ASR disabled, Agent Reach/model fallback not used, digest == content | **PASS** |
| A5 | Successive windows contiguous and reconstruct the full document digest | **PASS** |
| A6 | `read` text mode reports `Status: ok`, `Evidence: usable=yes` | **PASS** |
| A7 | Anonymous GitHub missing issue → honest coded failure, no chrome substitution | **PASS** |
| A8 | Missing optional Agent Reach → 40-action inventory + `not_configured`, no install | **PASS** |
| A9 | `reach` text mode states the missing dependency actionably | **PASS** |
| A10 | `reach-call` without Agent Reach → rc 1, `not_configured`, `items: []` | **PASS** |
| A11 | No Agent Reach installed; runtime venv only project + pip | **PASS** |

Counts were read back from `acceptance.json` (11 checks, 11 pass, `all_pass:true`)
and independently from the raw run log (11 `PASS` lines, 0 `FAIL`, banner
`acceptance: 11/11 pass`), not from a single stdout line.

### A7 — missing page now fails closed

URL: `https://github.com/pallets/flask/issues/999999999` (anonymous, no token;
the one missing-page read the existing harness performs — no extra GitHub calls).

Observed in this run:

| Field | Value |
|---|---|
| Exit code | `1` |
| `ok` | `false` |
| `error.code` | `extraction_error` |
| `error.message` | could not extract via Hermes web_extract, direct fetch or Jina fetch |
| Content | **0 chars** |
| `evidence.usable` / `transport_ok` | `false` / `false` |
| `source_quality` | `dead` (0/100) |
| Substituted repo metadata / nav chrome | absent |

An unreachable URL (`http://127.0.0.1:9/`) also fails closed with rc 1 and
`extraction_error`, 0 chars. The 404 wrapper page that the earlier committed
HEAD accepted as usable evidence is now rejected; a missing artifact is reported
as a missing artifact.

### A4/A5 — public read and complete pagination reconstruction

URL: `https://docs.python.org/zh-cn/3/library/typing.html`

- Full window (`--max-chars 200000`): rc 0, `ok:true`,
  `extraction_status:"ok"`, 78,047 chars, `evidence.usable:true`,
  quality `canonical` 80/100, markers `typing`, `泛型`, `PEP 673`.
- Policy in the payload: `asr:"disabled"`, `agent_reach:"not_used"`,
  `hermes_web_extract:"disabled"`; `asr.enabled:false`.
- Document digest: `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea`,
  equal to the SHA-256 of the returned content.

Four 20,000-char windows were fetched, concatenated and hashed:

| Window | Span | Chars | Window content SHA-256 (16) |
|---|---|---|---|
| 1 | 0–20000 | 20000 | `5c764991dab17784` |
| 2 | 20000–40000 | 20000 | `63222002bc6a2408` |
| 3 | 40000–60000 | 20000 | `9f5d1a1f6e793d14` |
| 4 | 60000–78047 | 18047 | `b04da5ac09911b62` |

- Spans are contiguous: every `start` equals the previous `end`; `next_offset`
  links the windows; the last has `more:false`.
- Concatenation is 78,047 chars. Its SHA-256, recomputed on the host from
  `pagination_concat.txt`, is
  `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea` — the same
  as every window's `pagination.document_sha256` and the single large-window
  read's content hash. Sum of window chars equals `total_available_chars`
  (78,047), so the reconstruction is complete for this run.
- `completeness.extracted_document_complete:true`,
  `raw_page_complete:false`, `extractor_truncated:false`,
  `retrieval_capped:false`, `transport_capped:false`.
- Caveat: `read` refetches on every call. Equal digests prove the windows came
  from the same extraction; they say nothing about upstream immutability.

## Optional backend: missing Agent Reach

`reach --format json`: rc 0, `found:false`, `reason:"not_installed"`,
`error.code:"not_configured"`, `asr_disabled:true`, `asr_vetoed:true`.

Parity inventory: **40 actions across 14 channels** (`surfaced:40`,
`native:8`, `native_partial:4`, `upstream_only:28`, `public:26`,
`gated_auth:12`, `gated_quota:2`), reference `Panniantong/Agent-Reach` 1.6.0
commit `14c213405669414492bda0f8d52cc6531d062c45`. Text mode states the missing
dependency actionably. `reach-call` fails closed: rc 1, `not_configured`,
`items:[]`. Agent Reach was not installed or invoked.

## Policy and scope

- No credentials, auth setup, purchases, paid calls, ASR calls, model calls or
  `hermes_web_extract` fallback for `read`.
- No Agent Reach install/invocation; no host package installs, host home/config
  mounts or host tool use. The only installs were apt Python + the project wheel
  inside the disposable container.
- No source edits, commits, pushes or publication. `git status` is unchanged
  (`?? o.txt` only); `o.txt` SHA-256 is still
  `1d3e2496f6911856b8abce624935e7c7c045b0ec54b4d3f3f4734f09abf26595`.
- The container is gone: `docker inspect trailhead-clean-run283` reports no such
  object after the run.
- Claim is a **clean userspace on the host kernel**: Linux arm64, Ubuntu 24.04,
  kernel `7.0.0-1013-oracle` shared with the host. It is not a native macOS,
  Windows or independent-hardware run.
- Not claimed: stable A7 behavior across every upstream/CDN variant (verified
  for this run's single read), raw HTML byte-identical completeness, upstream
  page immutability, complete GitHub PR conversation, or host-wide installation.

## Evidence handles

| Artifact | SHA-256 |
|---|---|
| `source.tar` (scratch, mode 0444) | `48ffdc2de6cc879cabf53f7788a0e0257f4008b1f76810dbc78adc94ce8bc58d` |
| `harness3.sh` (scratch, mode 0444, unmodified) | `3b633540a664f0cb159fe150d67c74bb3b23270e5d82e07f30a24d309f4a85e2` |
| `run283-raw.log` (raw, primary) | `7dfa686864638b002839f69307ed471c33ca9f9d575a96680ea43e6b32e9f463` |
| `acceptance.json` | `3a537f930225fcaff7485880c079e3f34221a2c841978bdd2cef169f38f7a089` |
| `final_facts.json` | `99e2e394a17a016a5782c918795eacc92ddb5c648cd661302805f2d581567539` |
| `pagination_concat.txt` | `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea` |
| `docs/evidence/clean-linux-run283.json` | `642d7508395dd49303783d6d329bd84839b173cd225adee351b59d5ba6dc495a` |

Raw scratch directory:
`<scratch>/`

Raw run log:
`.../trailhead-clean-run283-20261028/results/run283-raw.log`
(sanitized report: `.../results/final_facts.json`, acceptance: `.../results/acceptance.json`)

Reproduce (same bounded container approach; `S` is the scratch directory above):

```bash
cd <repo>
S=<scratch>
git archive --format=tar db6adc1a68f0792ef4270576c8ecd171c03cca3a > "$S/source.tar"
docker run --rm --name trailhead-clean-run283 \
  --cpus 2 --memory 2g --memory-swap 2g --pids-limit 256 \
  --cap-drop ALL --cap-add SETUID --cap-add SETGID --cap-add CHOWN \
  --cap-add DAC_OVERRIDE --cap-add FOWNER --security-opt no-new-privileges \
  -e GIT_HEAD=db6adc1a68f0792ef4270576c8ecd171c03cca3a \
  -e IMAGE_REF=ubuntu:24.04 \
  -e IMAGE_DIGEST="$(docker image inspect ubuntu:24.04 --format '{{.Id}}')" \
  -e DOCKER_SERVER="$(docker version --format '{{.Server.Version}}')" \
  -v "$S/source.tar:/src/source.tar:ro" \
  -v "$S/harness3.sh:/src/harness3.sh:ro" \
  -v "$S/results:/work/results" \
  ubuntu:24.04 /bin/bash /src/harness3.sh
```

## Bottom line

Committed `db6adc1` installs from a single archive into a fresh userspace with
zero runtime dependencies, exposes a real working `hermes-trailhead` CLI, and
passes all 11 acceptance gates. The gap that blocked the earlier claim — a
missing GitHub issue reported as usable evidence — is closed in this run: the
missing page now fails closed with a coded error, no content, and
`usable:false`.
