# Final verification gate — 2026-10-28, run 289

**Verification phase complete; whole-product acceptance remains OPEN.** Product source tested: `4eb2ba8e4e270b7a09088c67d71a89aaba56316a`. No product code changed in this phase. See [sanitized measurements](evidence/final-verification-run289.json).

## Independent execution

- `env -u TRAILHEAD_DISABLE_ASR .venv/bin/python -m pytest -q`: **1134 passed in 60.60s**. The veto is unset only in the hermetic contract suite; production behavior is not changed. Compilation of `hermes_trailhead/*.py` and `git diff --check` passed.
- Actual `compare` CLI: three matched public cases, both sides killable subprocesses with equal **20-second wall deadlines**; fresh homes, credentials/session/proxy environment withheld, ASR veto enabled. Environment isolation is **not** an OS/filesystem security sandbox. Agent Reach installed distribution metadata identifies **1.6.0**, from the archive for `14c213405669414492bda0f8d52cc6531d062c45`. Its unsupported `--version` returned BAD_INPUT; metadata and the harness version discovery established identity instead.

| Cold case | Trailhead | Agent Reach | Observation |
|---|---|---|---|
| GitHub requests README | ok, 457 ms, 3098 cleaned chars | ok, 282 ms, 2874 chars | both_evidence |
| V2EX topic | ok, 308 ms, 13718 chars | ok, 1042 ms, 15093 chars | both_evidence |
| YouTube aircAruvnKk subtitles | blocked, 2443 ms, 0 chars | blocked, 1586 ms, 0 chars | neither_evidence |

One observation is not a latency distribution, relevance judgment, full-artifact equality, or winner. No warm comparison was run here. Prior configured sweeps and parent cold/warm samples remain historical and separate.

## Surface, gates and routing

Actual `reach` discovery returned 40 unique pairs / 14 channels, exactly equal to both the pinned static inventory and discoverable allowlist: **26 public / 12 auth / 2 quota**. All 40 have attributed adapter paths. Static native classifications (8 native, 4 native-partial, 28 upstream-only) are ownership declarations, not 40 live successes. See [exact inventory](EXACT-ACTION-INVENTORY.md).

Eight fresh CLI subprocess refusals covered both `youtube transcribe` and `xiaoyuzhou transcribe`: no consent => quota_required; auth-only => quota_required; quota-only => auth_required; both flags plus ASR veto => asr_disabled. Every result had empty argv; the sentinel upstream executable never started. No billable or authenticated call was made.

Normal search's maintained fallback is integrated, not a disconnected CLI demonstration: trusted default runtime only, explicitly configured executable, five public search route mappings, no auth/quota consent, a bounded fallback after zero results or thin results, strict distinct-URL superset required for replacement, attribution retained. Full-suite regressions verify this current contract. The earlier real thin-fault recovery is documented in [routing verification](ROUTING-FALLBACK-VERIFICATION.md), not misrepresented as a new natural outage or newly repeated live recovery.

Fresh unpaired seven-family CLI sweep used sanitized public-only environment and an explicitly enabled maintained executable, ASR veto, limit one, extraction enabled; 30.636 seconds. This is **not a configured warm benchmark**, nor a matched comparison. Each family returned one lead; automated extraction marked four usable (web, Reddit, TikTok, GitHub), one unusable X CAPTCHA page, and two blocked (Instagram, YouTube). Inspection rejects the Reddit Unity navigation-agent result as irrelevant to Agent Reach despite automated partial lexical usability. Thus do not report four human-validated sources; web/GitHub duplicate the same repository. TikTok captions are not ASR or inspected frames. The X transport status is `ok` but evidence_usable=false; security chrome is not content evidence.

Four actual attributed public CLI calls succeeded: V2EX hot (2 items), Bilibili hot (2), Xueqiu quote (1), GitHub search (1). All reported native=false, public_only=true, isolated-temp home, forced backend equal to reported backend. These are four calls, not exhaustive live parity.

## Important safety finding: a global criterion does not pass

The **two attributed transcription paths pass their consent gates**, but a separate legacy native ASR fallback remains automatic when the veto is unset and a Groq key is configured. `extract.py` calls `_fetch_youtube_asr` after caption failures (lines 4364–4368 at this revision); `_ensure_asr_enabled` checks only the veto (lines 434–450), and the helper obtains a key then invokes transcription. The TikTok helper similarly has a veto-only entry guard. A claimed free tier does not establish zero cost or authorize quota use.

Therefore **global “no automatic key/quota-consuming ASR” is NOT verified and must not be claimed**. All live verification here used the veto and sanitized environment; no provider call was needed to identify this source-level gap. Follow-up **t_c46f0f73**, assigned to `monchobot`, must resolve native default consent with hermetic provider/download sentinels and independent validation. It is a new prerequisite of the existing whole-product root, not a request to redo the adapter or a fabricated paid test. This verification phase does not silently modify the product.

## Evidence custody and remaining acceptance

Raw reports are in Jr scratch with non-overwriting names:
- `trailhead-final-compare-run289.json`
- `trailhead-final-sweep-run289.json` and its exact stdout JSON
- `trailhead-public-cli-verification-run289.json`
- `trailhead-final-inventory-run289.json`
- `trailhead-final-gates-run289.json`

The sanitized committed ledger retains hashes, counts, conditions, gate checks and observations without copying third-party post bodies. Original parent report names and historical observations remain untouched.

`o.txt` remains untracked and unchanged: SHA256 `1d3e2496f6911856b8abce624935e7c7c045b0ec54b4d3f3f4734f09abf26595`. No staged inclusion or modification. All authored changes are local commits; this phase runs no push/publication operation. Local Git state alone cannot prove that no unrelated actor ever published anything.

Still open: native automatic ASR gate above; exhaustive live action/artifact depth and unknown continuation; human-reviewed multilingual relevance; genuine multi-day reliability (only day one observed); comparable final-source resource distributions; final-source clean-machine/cross-OS coverage; authenticated artifacts and account lifecycle; live quota-backed transcript/podcast content and billing bounds. Historical clean Linux evidence is not final-source search certification. Existing dated observation coordination is not duplicated or reset.

Exact consent requirement: name disposable platform/account/test targets and explicitly authorize allowed login/status/expiry/switch/logout/revoke/removal operations; never import an existing session implicitly. Separately authorize each transcript/podcast target and per-call quota/spend budget. Disposable macOS/Windows environments and human relevance adjudication are also outstanding. None of these waives independent public product work. Completing this phase releases downstream work; it does **not** complete the whole-product goal.
