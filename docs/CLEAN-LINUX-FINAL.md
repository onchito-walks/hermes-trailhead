# Clean Linux final — committed HEAD `d40c784` (Hermes Trailhead 1.1.0)

**Verdict: the committed source installs and runs cleanly, but CLI acceptance is
10/11 — one real failure.** Native GitHub 404 failure honesty is not stable:
`read` returns `ok:true` with generic GitHub navigation chrome for a missing
issue when the Jina tier wraps the upstream 404 in HTTP 200.

- **Source:** commit `d40c784f4761d96eb7df9d686b9e043aceb6790d`
  (`test: repeat matched resource campaign on committed implementation`)
- **Archive:** `git archive --format=tar HEAD`, SHA-256
  `079b41bfad61e292228404377f290e4479e071eb52837242449f8cd8a6f98c36`
  (160 entries, 147 files, no `.git`, no untracked `o.txt`)
- **Acceptance:** 10/11 pass; failed gate `A7-github-honest-failure`
- **Environment:** clean Ubuntu 24.04.4 userspace, `aarch64`, on the shared
  host kernel `7.0.0-1013-oracle` — Linux arm64, **not** macOS or Windows
- **Evidence:** [evidence/clean-linux-final.json](evidence/clean-linux-final.json)
  (SHA-256 `ebe63522886a3ec210e7e3784bb3e6129f331a1e9cd0645726bb374fd46b2862`)

## Artifact and install

The archive was built from the commit, not the working tree, so the untracked
`o.txt` was excluded by construction and verified absent from the tar listing.
The container received **only** that tar as a read-only mount; no host home,
config, credentials, binaries or project checkout were mounted.

| Item | Value |
|---|---|
| Docker server | 29.1.3 |
| Image | `ubuntu:24.04`, image ID `sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90` |
| Image OS / arch | Ubuntu 24.04.4 LTS / `arm64` |
| Container | `8c41ca052760` (`trailhead-clean-final-20261028`), removed on exit |
| Limits | `--cpus 2 --memory 2g --memory-swap 2g --pids-limit 256` |
| Capabilities | `cap-drop ALL` + `SETUID,SETGID,CHOWN,DAC_OVERRIDE,FOWNER`; `no-new-privileges` |
| Mount | one read-only file: `source.tar:/src/source.tar:ro` |
| Env | `env -i`, empty `HOME=/work/home`, `TRAILHEAD_DISABLE_ASR=1`; `PYTHONPATH`, `VIRTUAL_ENV`, `GITHUB_TOKEN`, `GH_TOKEN` unset |
| Python | image ships none; Ubuntu `python3 3.12.3` + `python3-venv`/`pip` installed **inside** the container |
| Setup | 21 s from start to working CLI |

- Fresh venv; `pip install /work/project` exited 0.
- `dependencies = []`: **zero third-party runtime dependencies**. Runtime venv
  has 2 distributions (`hermes-trailhead 1.1.0`, `pip 24.0`); `pip freeze` shows
  only `hermes-trailhead @ file:///work/project`.
- Wheel: `hermes_trailhead-1.1.0-py3-none-any.whl`, 208,127 bytes,
  SHA-256 `e9f74836b50e625ab47a022f5decb707531318ff5fc82a429b0c0bc95b58e197`.
- Integrity: installed `cli.py` is byte-identical to the archived file, both
  SHA-256 `5bd66478fec93990fa107449f29cabff70a77fc89b30b0c906680ef20b4f9fa9`.
- Entry point `#!/work/venv/bin/python`; version `hermes-trailhead 1.1.0`.

## Acceptance matrix

| # | Criterion | Result |
|---|---|---|
| A1 | Fresh-venv install; 0 runtime deps; installed bytes == archive | **PASS** |
| A2 | `--version` → `hermes-trailhead 1.1.0`, rc 0 | **PASS** |
| A3 | `--help` exposes read/reach/reach-call/doctor/search/routes/score/compare | **PASS** |
| A4 | Public `read` usable, ASR disabled, Agent Reach/model fallback not used, digest == content | **PASS** |
| A5 | Successive windows contiguous and reconstruct the full document digest | **PASS** |
| A6 | `read` text mode reports `Status: ok`, `Evidence: usable=yes` | **PASS** |
| A7 | Anonymous GitHub missing issue → honest coded failure, no chrome substitution | **FAIL** |
| A8 | Missing optional Agent Reach → 40-action inventory + `not_configured`, no install | **PASS** |
| A9 | `reach` text mode states the missing dependency actionably | **PASS** |
| A10 | `reach-call` without Agent Reach → rc 1, `not_configured`, `items: []` | **PASS** |
| A11 | No Agent Reach installed; runtime venv only project + pip | **PASS** |

### A4/A5 — public read and complete pagination reconstruction

URL: `https://docs.python.org/zh-cn/3/library/typing.html`

- Full window (`--max-chars 200000`): rc 0, `ok:true`,
  `extraction_status:"ok"`, 78,047 chars, `evidence.usable:true`,
  quality `canonical` 80/100, markers `typing`, `泛型`, `PEP 673`.
- Policy in the payload: `asr:"disabled"`, `agent_reach:"not_used"`,
  `hermes_web_extract:"disabled"`; `asr.enabled:false`.
- Document digest: `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea`.

Four default-size windows were fetched, concatenated and hashed:

| Window | Span | Chars | Window content SHA-256 (16) |
|---|---|---|---|
| 1 | 0–20000 | 20000 | `5c764991dab17784` |
| 2 | 20000–40000 | 20000 | `63222002bc6a2408` |
| 3 | 40000–60000 | 20000 | `9f5d1a1f6e793d14` |
| 4 | 60000–78047 | 18047 | `b04da5ac09911b62` |

- Spans are contiguous: every `start` equals the previous `end`; `next_offset`
  links the windows; the last has `more:false`.
- Concatenation is 78,047 chars. Its SHA-256 and every window's
  `pagination.document_sha256` are **the same**
  `eb8e809440b16bbd9346d5121e238514afe21a777ff8855f2136459a1e9216ea`, which also
  equals the single large-window read's content hash. Complete reconstruction
  of the available extracted document is proven for this run.
- `completeness.extracted_document_complete:true`,
  `raw_page_complete:false`, `extractor_truncated:false`,
  `retrieval_capped:false`, `transport_capped:false`.
- Caveat: `read` refetches on every call. Equal digests prove the windows came
  from the same extraction; they say nothing about upstream immutability. If the
  digest changes between calls, the sequence must be discarded.

### A7 — GitHub failure honesty (the failed gate)

URL: `https://github.com/pallets/flask/issues/999999999` (anonymous, no token).

Final run: **rc 0, `ok:true`, `error:null`, 6,041 chars, `evidence.usable:true`**,
`source_type:"github"`, quality `technical` 90/100. The content is not the
requested issue; it starts:

```text
Title: Build software better, together
URL Source: https://github.com/pallets/flask/issues/999999999
Warning: Target URL returned error 404: Not Found
Markdown Content:
[Skip to content] ... [Sign in] ... AI CODE CREATION ... GitHub Copilot
```

A separate clean container (`trailhead-clean-probe-20261028`) repeated the read
**3 times; all 3 were identical** (`rc 0`, `ok:true`, 6,041 chars). Independent
status checks from the same network namespace:

| Endpoint | Status |
|---|---|
| `api.github.com/repos/pallets/flask/issues/999999999` | **404** |
| `github.com/pallets/flask/issues/999999999` | **404** |
| `r.jina.ai/https://github.com/pallets/flask/issues/999999999` | **200** (404 wrapper page) |

The Jina tier returns HTTP 200 for the upstream 404 page, and `read` accepts the
generic GitHub navigation chrome as usable evidence instead of returning an
`extraction_error`. That contradicts the documented number-shaped issue/PR
contract ("a failed primary endpoint must raise rather than present repository
metadata"). Nothing was fabricated — the returned text is the upstream 404
wrapper itself — but `ok:true` / `usable:true` mislabels a missing artifact.

An earlier run of the same harness minutes before failed closed: rc 1,
`error.code:"extraction_error"`, 0 chars, `usable:false`, when the Jina tier
failed. So the defect is **tier-dependent**, not a stable honest failure. The
recorded artifact run is the one with the full harvest; the earlier run is kept
as raw evidence and is not used as the acceptance result.

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
- No source edits, commits, pushes or publication in the shared repository.
- Claim is a **clean userspace on the host kernel**: Linux arm64, Ubuntu 24.04,
  kernel `7.0.0-1013-oracle` shared with the host. It is not a native macOS,
  Windows or independent-hardware run.
- Not claimed: raw HTML byte-identical completeness, upstream page immutability,
  complete GitHub PR conversation, or host-wide installation.

## Evidence handles

| Artifact | SHA-256 |
|---|---|
| `source.tar` (scratch) | `079b41bfad61e292228404377f290e4479e071eb52837242449f8cd8a6f98c36` |
| `run-final.log` (raw, primary) | `1fac39ae84487b1041ac7050f44d616ed2193c13fe53984d026d67ce527f4e0e` |
| `run-attempt1-harvest-missing.log` | `3a794fdf6d7b5094d65d2fc017f360b125ae5bf1d5f5ff243ae5e365223043a6` |
| `probe-github.log` (3/3 reproduction) | `59eeafbcede9bb869b35231e8e84b0e738e2ccc27ade92aa4be3479e7cbef57d` |
| `harness3.sh` | `3b633540a664f0cb159fe150d67c74bb3b23270e5d82e07f30a24d309f4a85e2` |
| `probe-github.sh` | `4cc8a9b6464cc32a91c533c4dd7b311ca345beffc75e0f41e2e74817e4e844ec` |
| `docs/evidence/clean-linux-final.json` | `ebe63522886a3ec210e7e3784bb3e6129f331a1e9cd0645726bb374fd46b2862` |

Raw scratch directory:
`<scratch>/`

Reproduce (same bounded container approach):

```bash
cd <repo>
git archive --format=tar HEAD > /tmp/source.tar
cd <scratch>
docker run --rm --name trailhead-clean-final-20261028 \
  --cpus 2 --memory 2g --pids-limit 256 \
  --cap-drop ALL --cap-add SETUID --cap-add SETGID --cap-add CHOWN \
  --cap-add DAC_OVERRIDE --cap-add FOWNER --security-opt no-new-privileges \
  -e GIT_HEAD="$(git -C <repo> rev-parse HEAD)" \
  -e IMAGE_REF=ubuntu:24.04 \
  -e IMAGE_DIGEST="$(docker image inspect ubuntu:24.04 --format '{{.Id}}')" \
  -v "$PWD/source.tar:/src/source.tar:ro" \
  ubuntu:24.04 /bin/bash -c "$(cat harness3.sh)"
```

## Bottom line

The committed HEAD installs from a single archive into a fresh userspace with
zero runtime dependencies, and the public read/pagination/optional-backend
surfaces work as documented. The one failing gate is substantive: a missing
GitHub issue can be reported as usable evidence because the Jina 404 wrapper is
accepted as page chrome. Fixing that failure classification is required before
claiming clean-slate GitHub read honesty.
