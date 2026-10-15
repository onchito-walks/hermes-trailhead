# Changelog

All notable changes to **Hermes Trailhead** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-15

**Added** — `score` command: the per-lane product scorecard, live-probed

- `hermes-trailhead score --live` prints each lane's grade (what a researcher
  gets today, verified against live runs) plus a real reachability probe from
  the local host — API routes, token status, session tier, transcript cache.
- `--format json` for machine consumption; grades and dimensions live in
  `hermes_trailhead/scores.py` and are re-verified when lanes change.

**Security** — privacy pass for public distribution

- Authenticated-tier config moved fully to environment variables
  (`TRAILHEAD_CAMOFOX_API` / `TRAILHEAD_CAMOFOX_USER`); no instance
  identifiers in source. Tier auto-disables when unset.
- Instance-specific paths and host references genericized across docs and
  scripts; `.gitignore` hardened against credential/session files.
- Sweep verified: no passwords, cookies, tokens, or personal emails tracked.

**Changed** — TikTok transcripts now prefer TikTok's native caption track (no media download)

- `_fetch_tiktok_captions`: parse the page's `captionInfos` VTT URL (the same
  track `yt-dlp --list-subs` reports), fetch the ~1KB WebVTT, convert to
  deduped text. Tier order: native captions → ASR fallback for captionless.
- Verified live 2026-10-14: 563-char transcript in **2.8s** (vs ~30s via the
  download+ASR path); all cached (`.captions.txt`).

**Added** — TikTok video audio transcripts (Groq Whisper ASR)

- `_fetch_tiktok_transcript`: pulls the no-watermark MP4 via TikWM's `play`
  URL (proxy-pool fallback, 24MB cap) and transcribes with Groq's free-tier
  whisper-large-v3-turbo; cached per video id (`.asr.txt`).
- Wired into the primary TikWM tier: metadata + comments + transcript in one
  extraction; transcript failures (photo posts, music-only) degrade to an
  honest `not_available` and never block the metadata result.
- Verified live 2026-10-14: 467-char spoken transcript on a real TikTok.
  Hermetic tests in `tests/test_tiktok_asr_tier.py` (264 total passing).

**Added** — authenticated session tier (Camofox) for Instagram profiles & Facebook pages

- New `_camofox_session_fetch` / `_camofox_req` in `extract.py`: fetch page content
  through the local Camofox browser server's persistent, logged-in profile
  (short-lived tab in the `trailhead` group, auto-closed afterwards).
- Instagram: profile URLs (no `/embed/` surface) and blocked posts fall through
  to the authenticated tier after the static embed attempt.
- Facebook: dedicated extraction path — no loginless surface exists from
  datacenter IPs; the session carries the content.
- Verified live 2026-10-14: `instagram.com/nasa` → 104M followers + full authed
  page; Facebook page fetch 200. Hermetic unit tests in `tests/test_camofox_tier.py`.

**Added** — local Redlib integration for the Reddit lane

- Reddit discovery now starts with the local Redlib instance
  (`http://127.0.0.1:8789`, backend `redlib_local_search`); DDG/Jina remain as
  fallbacks. Remote public Redlib instances and Reddit OAuth stay blocked.
- Reddit extraction tries the local Redlib thread view first, then
  old.reddit.com direct, then every residential route in the pool — skipping
  routes that serve a logged-out shell and taking the first route with usable
  content (verified serving full 330KB thread content when a route cooperates).
- `_fetch_proxy` now fails over across the whole residential proxy pool and
  retries once — a dead or flaky route (e.g. per-request 407) no longer kills
  the proxy tier while another enabled route works.

**Fixed** — doctor reporting drift + YouTube lane regression

- The live Redlib check probes the local instance first (remote as fallback);
  Firecrawl / Browserbase / Exa checks also recognise keys present in the
  Hermes `.env` the gateway loads (they previously read as "off" from bare
  shells). Only key names are checked — values are never read.
- Restored `yt-dlp` in the project venv (YouTube discovery/transcripts had
  silently degraded to fallbacks).
- GitHub discovery keeps numeric-axis compounds (`5 axis` → `5-axis`) in its
  search-API query: "DIY 5 axis 3D printer" now finds Open5x, Fractal-5-Pro and
  Gen5X instead of repos that merely contain `axis`.
- Web lane rejects interactive-media hosts (youtube/tiktok/instagram/facebook)
  at discovery — those belong to their family lanes; blocked platform pages no
  longer surface at the top of web results.
- TikTok lane rejects `shop.tiktok.com` listings (commercial pages, not
  creator content).
- JSON output: `hits[]` follows the ranked evidence order when scoring is on
  ("ranks results by quality"); `extracted[]` stays score-sorted.
- YouTube transcripts: per-attempt yt-dlp timeout floored at 30s (CLI extract
  budgets passed ~10s and starved every download -> false `blocked`),
  `--js-runtimes node` wired for YouTube challenge solving, and `curl_cffi`
  installed in the venv for extraction impersonation. The dead 407 residential
  route was pruned from the proxy failover plan.
- Proxigram container: compose-level `NODE_OPTIONS=--dns-result-order=ipv4first`
  resolves its IPv6/IPv4 loopback mismatch — structural routes render again
  (was all-500). App-level IG data paths remain degraded pending browser
  binaries (see `docs/KNOWN-ISSUES.md`).
- Reddit content extraction is now **always-on**: PullPush + Arctic Shift
  (Pushshift successors) wired as extraction tiers after Redlib — post + top-20
  comments via public JSON APIs reachable from any IP. Verified 3/3 threads
  with real content while Redlib was throttled (full sweep: 21 hits, 19/21
  extracted).
- Lane-native content methods (all verified live 2026-10-14 evening):
  - **X**: FxTwitter API (tweet text + engagement + media), local Nitter
    fallback (tweet + replies) — replaces ~150k-char whole-page reader text.
  - **TikTok**: TikWM public API tier (description, plays/likes/comments/
    shares/saves, music, duration).
  - **Instagram**: loginless `/embed/captioned/` tier (bot UA serves the
    static variant) — full caption + author + social proof (2.3–2.7k chars vs
    previous 110–453).
  - **YouTube**: transcript disk cache (repeat queries never re-hit YouTube).
  - **GitHub**: README excerpt appended to repo metadata (≈1.3k vs 145 chars).
  - Sweep after all updates: 21 hits / **20 extracted** — every lane returns
    substantial content.
- GitHub lane authenticates with `GITHUB_TOKEN` (env or `$HERMES_HOME/.env`):
  verified **5,000 req/hr core + 30 search/min** vs the 60/hr anonymous cap —
  the lane no longer degrades under sustained sweeps. Token never logged.
- Guardian Pattern 5: monitors the third-party content APIs (FxTwitter,
  TikWM, PullPush, Arctic Shift) every 30 minutes; 429 = throttled (window),
  not down. Fragility register added to `docs/KNOWN-ISSUES.md`.
- **TikTok depth**: TikWM's comment endpoint wired — videos now carry top-10
  score-ranked comment texts (1,036 vs 445 chars on the reference video).
- **YouTube ASR tier — the captionless gap is closed**: `_fetch_youtube_asr`
  downloads bestaudio through the proxy pool and transcribes with Groq's
  free-tier whisper-large-v3-turbo (verified live: 6,874 chars on MUDgtjQBERI,
  matching its captions; genuinely speechless clips report honestly, never
  fabricated). Groq's API sits behind Cloudflare — browser UA + Origin needed
  (403 error 1010 without, same signature as the opencode.ai GO tier).
- Instagram profiles: `web_profile_info` is walled (429 from both the
  datacenter IP and the residential route; bot-UA profile pages are generic
  shells) — posts/reels remain covered by the embed tier; profiles stay a
  logged gap, no loginless method found.
- Doctor: new `frontends` channel — a live map of nitter / redlib / searxng
  (plus parked proxitok / proxigram) so the container layer is visible in the
  health surface.
- Added `docs/KNOWN-ISSUES.md` — the parked/dead-component ledger (evidence +
  fix scope per item) so degradations are logged when discovered, never rusting
  silently.

Adds coverage for the new Redlib parser/chain, redlib-first extraction,
usable-route selection, proxy-pool failover, and the Hermes-env fallbacks
(test baseline 230).

**Fixed** — false-success extraction and evidence scoring

- The extractor's own failure narration (e.g. `Extraction failed: web_extract is
  configured to use "tavily," …`) is no longer reported as a successful
  extraction; the native web_extract path raises instead of returning it.
- Client-rendered HTML/JS shells (new Reddit, X, JS-only apps) are detected as
  non-readable and reported `blocked`, not `ok`; they no longer inherit the
  URL's practitioner/canonical quality or the long-content bonus.
- A requested GitHub release/blob/tree page now returns the release notes or
  file body it was asked for; when that specific resource cannot be retrieved
  it raises rather than substituting repository metadata (stars/forks).
- Media captions/descriptions are no longer reported as transcripts: video
  evidence now carries a distinct `caption_status`/`caption_text` alongside
  `caption_transcript_status`, so a caption-only TikTok/Instagram result reports
  `transcript_status: not_attempted` instead of `ok`.

Adds `tests/test_false_success_regressions.py` (test baseline 212).

**Added** — project identity and share-ready distribution

- `assets/`: pixel-art banner (README header), square logo, portrait poster,
  footer art, and favicon set (16/32/48 + `.ico`) — the project's visual
  identity.
- `integrations/hermes/skills/hermes-trailhead/SKILL.md`: a concise public
  Hermes skill so any agent install can drive the CLI (lanes, commands,
  honest-reading rules, optional auth tier).
- `docs/HERMES-INTEGRATION.md`: five-minute new-machine install flow
  (clone → wrapper → doctor → skill), including a no-sudo user-local option.
- README reorganized product-first: mission → scorecard (dimensions + lanes)
  → aspirations → landscape → future trails → bring-your-own-accounts →
  privacy; implementation notes moved below an "explanatory, subject to
  change" divider.

**Verified** (v1.1.0)

- 274 tests passing; PhD gauntlet 100/100.
- `score --live`: all seven lanes probed green on the deployment host.
- Fresh-clone install exercised end-to-end from GitHub before release.
- Privacy sweep: no credentials, cookies, tokens, or instance identifiers in
  tree or history.

## [1.0.0] - 2026-09-20

First stable release. All seven source lanes (X/Twitter, Reddit, YouTube,
TikTok, Instagram, GitHub, open web) return links, summaries, and quality
scores by default, with honest blind-spot reporting.

**Added**

- `search` subcommand: full-breadth pass across all seven source families with
  `--execute`, `--extract`, `--limit`, `--format json`.
- `doctor` subcommand: live capability check across all channels (usage:
  `hermes-trailhead doctor`).
- `gauntlet` subcommand: deterministic offline product contract, 4 PhD-grade
  research cases, aggregate 100/100.
- `report` subcommand: repeatable research deliverable written to
  `docs/outcome-loop/deliverable-<slug>.md`.
- `benchmark`, `reliability`, and `route` subcommands.
- YouTube transcripts via residential proxy rotation (provider rotation),
  bypassing YouTube's VPS IP block; clean, deduplicated auto-captions.
- Instagram post and reel caption extraction via proxy-backed HTTP and stealth
  Chrome — OG captions, hashtags, and engagement data without a login wall.
- TikTok caption extraction via oEmbed (author, description, hashtags,
  engagement stats).
- GitHub API repo/issue discovery and owner-aware ranking (official
  organizations outrank mirrors).
- Per-lane backend chains with automatic failover and circuit breakers.
- Proxy round-robin for blocked-source discovery.

**Fixed**

- Reddit discovery: Redlib and SearXNG return empty/blocked on datacenter IPs,
  so the Reddit lane extracts via `old.reddit.com` through the residential
  proxy. Redlib's OAuth flow is documented as blocked, not silently claimed.
- Instagram `/popular/` aggregation pages dropped from discovery (only real
  post/reel/profile results returned).
- Reduced verbose GitHub API search query for exact-match engines.
- Three architectural limits: SRT transcript dedup, clean web summaries, and
  TikTok/Instagram caption-as-transcript handling.
- Canonical `HERMES_HOME` path resolution for installed-skill and secrets
  discovery (no longer assumes `$HOME/.hermes`).
- yt-dlp transcript fail-over across enabled residential proxies.

**Tooling**

- `npm test` now runs the real Python test suite (`python3 -m pytest -q`);
  `test:live` and `doctor` npm scripts added.
- Python dev/test dependency group declared in `pyproject.toml`
  (`uv sync --group dev` or `pip install -e ".[dev]"`).
- Version pinned to `1.0.0` across `pyproject.toml`, `package.json`, and
  `hermes_trailhead/__init__.py`.

**Verified**

- 196 tests passing (`python3 -m pytest -q`).
- PhD gauntlet 100/100 across 10 hard-source lanes
  (`hermes-trailhead gauntlet`).
- Live doctor: ok=8, warn=4, off=6, fail=0 (`hermes-trailhead doctor --live`).
- Live Instagram caption extraction confirmed on real post and reel URLs.