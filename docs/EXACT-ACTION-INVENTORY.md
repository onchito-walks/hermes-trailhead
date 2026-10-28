# Exact action inventory and user-facing capability surface

Inventory only; **live artifact parity is not established**. No grades or overall
winner are assigned. This document distinguishes implementation ownership,
invocability, and observed outcomes; none implies the other two.

## Snapshot boundary and attribution

- Reference: [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach),
  version **1.6.0**, commit **14c213405669414492bda0f8d52cc6531d062c45**:
  **14 channels, 40 actions**.
- Requested Trailhead baseline: **2571d18**. Its adapter allowlists **38 read-only
  actions**; both `transcribe` actions are absent from that adapter.
- Actual inspected Trailhead HEAD: **5c7de6edb458d860d9cc43aaaac28dfd7064d9da**.
  The task description predates intervening implementation. At this HEAD both
  transcribe actions are implemented as **attributed, quota/auth-gated forwards**,
  not absent. They remain unverified against live paid endpoints.
- Implementation sources: `hermes_trailhead/reach_backend.py`, `cli.py`,
  `comparative.py`, `search.py`, and `extract.py`. Baseline was inspected using
  `git show 2571d18:<path>`, not reconstructed from current documentation.
- Current [ACTION-PARITY.md](ACTION-PARITY.md) uses a different vocabulary:
  `native`, `native-partial`, `upstream`. Its static counts are 8 / 4 / 28.
  Those are code declarations, not 40 successful live artifacts. Its five
  `live` tags are historical annotations, not a current exhaustive run ledger.

**Status in the matrix** is the best available implementation lane at the
requested baseline: `native` means a Trailhead-owned search/extraction lane
exists, `attributed` means the complete named action is supplied through the
optional Agent Reach adapter (even if Trailhead has a narrower native analog),
and `absent` means the baseline adapter cannot invoke it. Native does not mean
no third-party dependencies, complete content, or proven equivalent ranking.

**Every `reach-call` execution is attributed**, including actions with a native
alternative. It never selects the native implementation. Attribution is
`Agent Reach (third-party CLI), forwarded by Hermes Trailhead`; JSON exposes
`engine=agent-reach`, `provenance.native=false`, `provenance.attribution`, route,
requested action, reported/forced backend and home mode. Text prints attribution,
route and backend. Native alternatives are invoked through `search` / extraction
(and at current HEAD `read`), not by renaming forwarded output as native.

## Exhaustive 40-action matrix

`P` = public route, `A` = explicit authenticated consent, `Q` = quota plus auth
consent. These are route policies, **not availability guarantees**. All 38
non-transcribe rows have an attributed `reach-call CHANNEL ACTION` path at both
snapshots. Rows marked native additionally have a native alternative; the notes
bound that claim. The current status differs from baseline only in the two quota
rows for this three-state classification; native depth has also improved.

| # | Channel | Action | Baseline status | Current status | Gate | Artifact / native alternative and limits |
|---|---|---|---|---|---|---|
| 1 | github | search | native | native | P | Repository search; native `search github`. `reach-call` remains attributed. |
| 2 | github | read | attributed | attributed | P | Repo README / repository or issue/PR artifact. Native baseline metadata + README excerpt is narrower; current native README and bounded issue/PR capture exist, not universal full-history parity. |
| 3 | twitter | search | native | native | P | Native `search x` discovers indexed tweets via source-specific/search routes; not proof of equivalent tweet corpus or structured artifacts. |
| 4 | twitter | profile | attributed | attributed | A | Account profile. |
| 5 | twitter | tweets | attributed | attributed | A | Account tweet listing; bounded, not exhaustive history. |
| 6 | twitter | thread | attributed | attributed | A | Tweet/thread and replies; completeness unproved. |
| 7 | youtube | read | native | native | P | Native video extraction/metadata lane; metadata is not a speech transcript. |
| 8 | youtube | search | native | native | P | Native `search youtube`; ranking parity unproved. |
| 9 | youtube | subtitle | native | native | P | Native caption extraction; can be blocked or captions absent. Not ASR. |
| 10 | youtube | transcribe | absent | attributed | Q | Speech-to-text; absent from baseline adapter, now explicit gated forwarding. Native extraction keeps only opt-in-only ASR helpers that refuse without both consent keywords, so it never substitutes for this action and is not evidence of live parity. |
| 11 | reddit | search | native | native | P | Native `search reddit`, including configured Redlib/search routes. |
| 12 | reddit | read | attributed | attributed | P | Post/thread artifact. Native public page extraction is not exhaustive reply capture. |
| 13 | reddit | subreddit | attributed | attributed | A | Subreddit listing; native search for posts is not the same listing artifact. |
| 14 | facebook | search | attributed | attributed | P | Public indexed discovery, not access to private Facebook content. |
| 15 | facebook | profile | attributed | attributed | A | Profile/page artifact. |
| 16 | instagram | search | attributed | attributed | A | Upstream platform search. Native `search instagram` site discovery is narrower. |
| 17 | instagram | profile | attributed | attributed | A | Profile artifact. |
| 18 | instagram | posts | attributed | attributed | A | Account post listing. |
| 19 | bilibili | search | attributed | attributed | P | Video search; public policy selects installed `bili-cli`, not a guaranteed tool installation. |
| 20 | bilibili | read | attributed | attributed | P | Video title, uploader, description, statistics; not video understanding. |
| 21 | bilibili | hot | attributed | attributed | P | Trending videos. |
| 22 | bilibili | subtitle | attributed | attributed | A | Video subtitle artifact; session/credential gate retained. |
| 23 | xiaohongshu | search | attributed | attributed | P | Public-web discovery. |
| 24 | xiaohongshu | read | attributed | attributed | P | Public note artifact; missing-page shells must not count as notes. |
| 25 | xiaohongshu | comments | attributed | attributed | A | Note comments; pagination/completeness unproved. |
| 26 | linkedin | jobs | attributed | attributed | P | Public job search. |
| 27 | linkedin | read | attributed | attributed | P | Public job/profile artifact through public-web route; not unrestricted account access. |
| 28 | boss | search | attributed | attributed | P | Public job discovery. |
| 29 | boss | read | attributed | attributed | P | Job detail; loading/login shells are not job descriptions. |
| 30 | v2ex | hot | attributed | attributed | P | Hot topics. |
| 31 | v2ex | node | attributed | attributed | P | Node topic listing. |
| 32 | v2ex | read | attributed | attributed | P | Topic and replies; native generic forum extraction is a narrower alternate lane. |
| 33 | v2ex | user | attributed | attributed | P | Public user information. |
| 34 | xueqiu | quote | attributed | attributed | P | Quote via Tencent public backend; reported source is not necessarily Xueqiu itself. |
| 35 | xueqiu | search | attributed | attributed | P | Public securities search via Tencent. |
| 36 | xueqiu | hot_posts | attributed | attributed | A | Popular posts using upstream session route. |
| 37 | xueqiu | hot_stocks | attributed | attributed | A | Popular stocks using upstream session route. |
| 38 | xiaoyuzhou | transcribe | absent | attributed | Q | Podcast speech transcript; current explicit quota/auth forward, no live paid verification. |
| 39 | web | search | native | native | P | Native `search web`; configured search engines remain external sources. |
| 40 | web | read | native | native | P | Native generic page extraction; transport/extractor/window bounds apply. |

Counts, reconciled by pair (not merely row count): **40 unique actions / 14
channels**. Baseline best-lane statuses: **8 native, 30 attributed, 2 absent**.
Baseline adapter paths: **38 attributed, 2 absent**, because native alternatives
are not executed by `reach-call`. Current best-lane statuses: **8 native,
32 attributed, 0 absent**. Current adapter paths: **40 attributed** (38 read-only
plus 2 quota), of which **26 public / 12 auth / 2 quota**. These counts do not
assert any authenticated or paid live success.

## Complete CLI capability surface

Use `.venv/bin/python -m hermes_trailhead` below (or the installed
`hermes-trailhead` entry point). Optional executable discovery for `reach` and
`reach-call`: explicit `--agent-reach PATH`, then `TRAILHEAD_AGENT_REACH_BIN`,
then PATH. Trailhead does not install, configure or log in to upstream.

### `reach`: native inventory of attributed routes

```bash
.venv/bin/python -m hermes_trailhead reach --format json
.venv/bin/python -m hermes_trailhead reach --agent-reach /path/to/agent-reach
```

Complete options: `--agent-reach PATH`, `--timeout SECONDS` (default 30),
`--allow-authenticated`, `--allow-quota-consuming` (current only),
`--format text|json` (default text), plus standard help.

This is **native inventory/reporting**, not retrieval. It reports executable
availability and discovered routes, with the static pinned 40-action inventory
at current HEAD. Consent flags here describe readiness; they do not execute
artifacts or authorize future calls. Inspect `found`, `error`, `capabilities`,
and gates, not just `parity.counts.surfaced=40`: a missing executable produces
zero discovered capabilities while the static reference still lists 40 rows.
At baseline only the 38 read-only pairs were discoverable.

### `reach-call`: attributed retrieval for every adapter row above

```bash
.venv/bin/python -m hermes_trailhead reach-call v2ex hot --limit 2 --format json
.venv/bin/python -m hermes_trailhead reach-call github search hermes-trailhead --format text
```

Syntax: `reach-call CHANNEL ACTION [ARGUMENTS ...]`.
Complete options: repeatable `--param NAME=VALUE`, `--limit N` (default 10),
`--timeout SECONDS` (default 30), `--allow-authenticated`,
`--allow-quota-consuming` (current only), `--agent-reach PATH`,
`--format text|json` (default text), plus standard help. Positional arguments
fill required parameters in registry-declared order; `--param` supplies named
parameters validated against that action's registry schema. It is not arbitrary
shell execution or a general passthrough for upstream options.

All 40 action names and artifacts are enumerated above; availability is checked
against the installed registry. Public mode uses empty homes and redirected
config/cache variables; declared `public-web` routes are forced and verified.
Public API overrides are `github-api` for GitHub, `v2ex-api` for V2EX,
`bilibili-api` for Bilibili hot/read, `bili-cli` for Bilibili search, and `tencent`
for Xueqiu quote/search. Public-only mode does not intentionally fall through to
browser/session routes. **Environment isolation is not a filesystem/process
security sandbox** and does not prove absolute-path credentials are inaccessible.

Auth rows refuse with `auth_required` without per-call
`--allow-authenticated`. That flag allows upstream's existing configured home;
it does not create a login or grant approval to import accounts. Current quota
rows require **both** consent flags; otherwise `quota_required` / `auth_required`
refuse execution. `TRAILHEAD_DISABLE_ASR=1` vetoes quota execution even with both
flags (real process or supplied environment). The adapter does not meter or cap
paid spend. No billable invocation is reproduced in this inventory.
Management/login/setup/update/removal commands remain excluded.

Current forwarded `read` / `thread` / `comments` bodies share a bounded 250,000
character budget under the 4 MB captured-output ceiling; discovery text retains
its 4,000-character bound. Inspect item limits, truncation fields and limitations.
Unknown upstream continuation is **not** proof of complete replies, full history,
or an available pagination cursor; see [FORWARDED-BODY-EQUALITY.md](FORWARDED-BODY-EQUALITY.md).

### `compare`: native comparison harness, two explicitly labeled tool sides

```bash
.venv/bin/python -m hermes_trailhead compare --list-cases --format json
.venv/bin/python -m hermes_trailhead compare --case github-requests-readme --timeout 20 --format json
```

Complete options: repeatable `--case ID`, `--include-auth`, `--timeout SECONDS`
(default 30 per side), `--limit N` (default 3 question hits), `--agent-reach PATH`,
`--no-agent-reach`, `--out PATH`, `--list-cases`, `--sandbox DIR`,
`--format text|json|markdown` (default text), plus standard help. The comparison
CLI uses explicit path or PATH for upstream; do not assume the adapter's
environment-variable discovery applies here.

Complete built-in manifest (unchanged between the snapshots):

| Case ID | Trailhead side | Agent Reach side (attributed) | Access |
|---|---|---|---|
| docs-python-typing | native URL extraction | `read URL` | public |
| github-requests-readme | native GitHub extraction | `github read URL` | public |
| web-wikipedia-http | native URL extraction | `read URL` | public |
| forum-v2ex-topic | native forum extraction | `v2ex read URL` | public |
| forum-v2ex-node | native URL extraction | `v2ex node python` | public |
| video-youtube-transcript | native caption extraction, ASR vetoed | `youtube subtitle URL` | public |
| question-typing-protocol | native search + extraction | `web search QUERY` | public |
| instagram-profile-session-tier | native URL extraction attempt | `instagram profile nasa` | auth-shaped, skipped by default |
| facebook-page-session-tier | native URL extraction attempt | `facebook profile nasa` | auth-shaped, skipped by default |

`compare` is **not** a generic 40-action runner and does not invoke the adapter
as its Trailhead side. Trailhead owns the harness and native engine side;
Agent Reach owns the labeled upstream side. JSON records per-side `tool`, backend,
command, status, duration, evidence/error fields and environment provenance;
text/Markdown label the tools. No aggregate winner is computed.
`--no-agent-reach` records upstream `not_run`, not a Trailhead win.

Both sides run in killable subprocesses under equal per-case wall deadlines;
ASR is disabled, environment credentials/sessions/proxies are withheld and homes
are isolated. A fresh sandbox is cold; explicit reuse via `--sandbox DIR` is warm.
`--include-auth` merely includes **unauthenticated attempts** in empty homes;
it is not account consent or an authenticated comparison. A returned page/length
threshold establishes neither relevance nor complete requested artifacts.

### Native alternatives and extra scope

`search` exposes `all`, `web`, `x`, `reddit`, `tiktok`, `instagram`, `youtube`,
`github`, with execution/extraction/scoring and current explicit source/language
preferences. TikTok is additional scope, not a fifteenth upstream channel.
Current `read URL --format text|json --offset N --max-chars N --timeout SECONDS`
is a native known-URL surface absent at baseline; offsets are refetched windows,
so document digests must match before reconstruction. It does not automatically
invoke Agent Reach or model/ASR fallback. Normal research now has optional
maintained public fallback with per-hit attribution; a forwarded hit is still
attributed even inside a native search command. These existing changes supersede
the task description's assertion that maintained fallback is disconnected.

## Cross-check against the three required parent reports

These are **historical observations**, not new live tests or certification of
current HEAD. Original files were read from Jr scratch; hashes identify the
exact reports even if scratch later expires. No raw third-party post/profile
payloads are copied into this inventory.

### Clean cold, no-auth matched comparison

`trailhead-final-compare.json`, generated `2026-10-28T11:47:35Z`, schema
`trailhead.comparative/2`, SHA256
`ea80774d6b6966157f5f0ca857d4185f9e90d23d5fbfdcb42132b2350b1205d4`.
Fresh separate homes, credential/session/proxy environment stripped, ASR disabled,
equal **20-second per-side wall budget**, no filesystem sandbox.

| Case | Trailhead | Agent Reach | Historical observation |
|---|---|---|---|
| GitHub requests repo | ok; 1,399 cleaned chars; 431 ms | ok; 2,874 cleaned chars; 441 ms | Both returned text; native baseline README was an excerpt, not equal artifact depth. |
| V2EX topic | ok; 9,290 cleaned chars; 1,956 ms | ok; 12,272 cleaned chars; 914 ms | Both returned text; upstream faster in this single sample. No general speed claim. |
| YouTube `aircAruvnKk` subtitles | blocked; 0 chars; 2,310 ms | blocked; 0 chars; 1,741 ms | Neither returned transcript evidence under these conditions. |

Report totals: 3 cases, 2 `both_evidence`, 1 `neither_evidence`; aggregate ranking
is null. Character counts are not quality or completeness scores.

### Configured normal sweep — not the cold comparison

`trailhead-final-sweep.json`, SHA256
`e5a120fe031a2867cd1785b7a3468b870197f98588a323de6a42ad81b374aaf8`.
Query `Agent Reach`, seven families, normal configured/warm context; this report
does **not** establish stripped credentials, fresh homes, equal tool conditions,
or paired cold/warm timing. Do not promote it to a controlled warm benchmark.

| Family | Engine | Hits | Recorded extraction / usability |
|---|---|---|---|
| web | jina_duckduckgo | 1 | ok / usable |
| x | social_search_x | 0 | gap; no extraction |
| reddit | redlib_local_search | 1 | ok / usable |
| tiktok | jina_duckduckgo_site_tiktok | 1 | ok / usable, caption transcript present |
| instagram | tavily_instagram | 1 | blocked / unusable; discovery lead only |
| youtube | yt_dlp_flat_search | 1 | ok / usable, captions for `aanqEqQwjNU` |
| github | github_api_search | 1 | ok / usable; baseline repository excerpt |

Totals: **6 hits, 5 usable extracted rows, 1 blocked extracted row, 1 empty
family**. Usability is the report's automated classification, not human relevance
or full-content adjudication. YouTube is a **different video and environment**
from the cold case. Its successful captions do not erase the cold block or prove
ASR coverage. Visual analysis was not attempted; captions are not inspected frames.

### Attributed public CLI verification

`trailhead-public-cli-verification.json`, SHA256
`83223787b0fbfd0a75948d5c9a75941b8becc3f50c9fb1c551ee1db9a33d6f1c`.
Four recorded calls succeeded: `v2ex hot` (2 retained items, `v2ex-api`),
`bilibili hot` (2, `bilibili-api`), `xueqiu quote` (1, `tencent`),
`github search` (1, `github-api`). Each records public-only, forced backend,
isolated-temp home, and explicit **non-native Agent Reach attribution**.
This is four forwarding calls, not 38/40 live successes or native wins.
Some results were limited/dropped to bound output; completeness is not established.
The report's older wording that operator files were invisible is too strong:
the implemented mechanism is environment isolation, not filesystem isolation.

## Concrete remaining work (not waived by an inventory)

1. **Reconcile operator-facing inventory language.** Distinguish static 40-row
   reference from installed/discovered/runnable counts when upstream is missing;
   change read-only banners/help that now include billable quota actions. Keep
   native search discovery separate from structured action artifact parity.
2. **Update stale evidence annotations.** Link later actual action/artifact runs
   into the existing parity table rather than infer all rows live from a sweep.
   GitHub native depth has advanced; retain bounded capture/pagination disclosure.
3. **Finish action artifact acceptance.** For each public row, freeze required
   artifact units and missing/reply/pagination rules; execute and inspect bodies,
   withholding login/loading/404 shells. Use existing
   [ACTION-ARTIFACT-EVIDENCE.md](ACTION-ARTIFACT-EVIDENCE.md) and
   [PUBLIC-REMAINING-ACCEPTANCE.md](PUBLIC-REMAINING-ACCEPTANCE.md), not another
   runner. Returned items are not complete artifacts; upstream continuation is
   still unknown for some forwards.
4. **Authenticated artifacts and account lifecycle.** Prepare named test targets
   for the 12 auth rows and obtain specific account/lifecycle consent before
   login, expiration, switch, logout/revocation/removal tests. Do not import
   existing sessions implicitly. `compare --include-auth` does not satisfy this.
5. **Live speech/podcast acceptance.** Existing gates need no duplicate
   implementation. Obtain separate per-call target and quota budget consent,
   then verify transcript content, billing bounds and veto/refusal controls.
   No current result establishes live paid transcription parity.
6. **Controlled retrieval quality and reliability.** Human-adjudicate multilingual
   search relevance and full artifact units. Continue genuine dated cold/warm
   observations; [PUBLIC-RELIABILITY-STATE.md](PUBLIC-RELIABILITY-STATE.md) has
   day-one evidence, not five elapsed days. Match environment, cache, credentials,
   versions, budgets and per-tool resources before a performance conclusion.
7. **Portability/integration/maintenance.** Keep measured clean Linux scope
   ([CLEAN-LINUX-RUN283.md](CLEAN-LINUX-RUN283.md)) separate from unrun disposable
   macOS/Windows onboarding. Verify account-safe agent-session workflows and
   bounded dependencies/output/runtime. Reuse existing harnesses and review their
   complexity instead of adding measurement infrastructure.

The implementation portions of follow-up cards on optional fallback and quota
paths already exist at inspected HEAD; those workers should verify current code
and remaining gaps rather than duplicate it. The whole-product parent goal
remains open. This inventory adds no account access, paid calls, product code,
credentials, publication or push.
