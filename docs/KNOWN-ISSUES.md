# Known Issues / Parked Components Ledger

Purpose: everything that is dead, degraded, or parked gets logged here **at the
moment it is discovered**, with raw evidence and a fix-scope estimate — so
nothing rusts silently and any item can be picked up cold, later, without
re-investigation.

Legend: **PARKED** (known, not being worked now) · **RETIRED** (deliberately out
of scope) · **KNOWN LIMIT** (external, no code fix) · **FIXED** (resolved; kept
briefly for the record).

| # | Item | Status | Evidence (last verified) | Fix scope |
|---|------|--------|--------------------------|-----------|
| 1 | `proxitok-web` container (:8791) — TikTok frontend | PARTIAL (verified 2026-10-14) | Deployed v2.5.0.0 has no `/search`, `/trending`, `/discover` routes (earlier 404s were false signals); real routes are `/following`, `/foryou`, `/tag/…`, `/@user`. After a redis→chromedriver→web restart: `/following` serves live Discover content (23.5KB); `/foryou` and `/tag/fyp` return TikTok's `EMPTY_RESPONSE` (datacenter-IP silent filtering — raw 0-byte API body captured). Stack itself healthy (chromedriver ready, redis PONG). | Upstream-side; recheck if TikTok eases datacenter filtering, or try a newer ProxiTok release. TikTok lane does not depend on it. |
| 2 | `proxigram` container (:8790) — Instagram frontend | FIXED structural (2026-10-14) | All routes 500 (Next.js render worker bound IPv6-only loopback while the app dialed IPv4 `127.0.0.1` → ECONNREFUSED per request; cross-family test: v4 refused, v6 connected). Fixed via compose env `NODE_OPTIONS=--dns-result-order=ipv4first` on the proxigram service (compose: `<HERMES_SHARED>/trailhead-services/proxigram/docker-compose.yml`; container recreated; pre-edit backup kept as `docker-compose.yml.bak-20261014-191137`). Independently verified: `/`, `/+/about`, `/+/settings` → 200 and rendering (was all-500). Residual (app layer, NOT transport, proven): (a) `/[username]` data pages render the app's own "Something went wrong" page — its Instagram fetch returns no data; a proxy-route swap was tested and did NOT fix it (the fix is the app's headless/browser chain, `USE_HEADLESS_PROVIDERS`/browser binaries); env restored to the configured state after the test. (b) `/api/instance_info` 500s on a cosmetic `ENOENT .git/HEAD` (image lacks `.git`). | Follow-up (optional): enable/install the app's headless data path. IG lane does not depend on it. |
| 3 | `social-search` composite tool | RETIRED (docs/chains) | 2026-10-14: binary absent on the fleet; code paths fail through gracefully | Re-list only if the tool is reinstalled **and** verified serving. |
| 4 | Reddit thread content | FIXED (2026-10-14) | Historically window-dependent (Reddit policy-blocks the datacenter IP; Redlib upstream throttles in bursts). Now **always-on** via PullPush + Arctic Shift extraction tiers (public Pushshift-successor JSON APIs; verified 3/3 threads with real content while Redlib was throttled — full sweep 19/21). | Residual: very fresh threads may lag pushshift ingests; the Redlib live tier covers most freshness when its window is open. |
| 5 | Remote public Redlib instances / Reddit OAuth | RETIRED | Blocks confirmed July 2026, re-confirmed 2026-10-14 | Do not point config at remote Redlib instances; the local instance is the route. |
| 6 | GitHub lane relevance on numeric queries ("5 axis …") | FIXED 2026-10-14 | Before: query reduced to `axis` → unrelated repos (agent frameworks, AXI controllers). After: `5-axis` → Open5x, Fractal-5-Pro, Gen5X, CARVER_X5 | — |
| 7 | yt-dlp missing from project venv | FIXED 2026-10-14 | Dangling `~/.local/bin/yt-dlp` symlink; YouTube lane degraded to fallbacks | — |

## Fragility register (critical pass — 2026-10-14)

Where the lanes are still exposed — watched, logged, never hidden:

| Area | Fragility | Status |
|------|-----------|--------|
| Residential proxy pool | **One live route** serves YouTube transcripts + Reddit fallbacks; the second route's credentials died (disabled; restore-candidate also failed the neutral test) | Open — re-add from the provider dashboard. Transcript cache softens repeats. |
| YouTube no-caption videos | **FIXED 2026-10-14**: `_fetch_youtube_asr` downloads bestaudio via the proxy pool and transcribes with Groq's free-tier whisper-large-v3-turbo (verified: 6,874 chars on a captioned video, matching its captions; speechless clips report honestly). Groq API is behind Cloudflare — browser UA + Origin required (error 1010 without). | Closed. |
| Instagram profiles | **RESOLVED (2026-10-14)** — authenticated fetch through the Camofox persistent profile (`_camofox_session_fetch` in `extract.py`; logged-in session). Verified live: `@nasa` returned 104M-follower metadata + full authed page text. `web_profile_info` remains 429-walled even authed — the profile HTML + `og:description` route is the working path. | Closed. Dependency: the Camofox profile must stay logged in (one-time noVNC login; state persists on graceful close). Facebook pages ride the same tier. |
| TikTok depth | **RESOLVED (2026-10-14)** — metadata + top-10 score-ranked comments + **video audio transcripts**: `_fetch_tiktok_transcript` pulls the no-watermark MP4 via TikWM's `play` URL and transcribes with Groq Whisper (free tier), cached per video id. Verified live: 467-char spoken transcript on a real video. Photo posts / music-only → honest `not_available` with reason. | Closed. |
| X external dependency | FxTwitter is a single external dep for clean tweets (fallback: local Nitter → weak Jina page text) | Monitored — guardian Pattern 5. |
| PullPush burst throttling | 429s under rapid probe bursts (observed, then cooled to OK) | Covered by Arctic Shift fallback; both monitored. |
| GitHub API limits | Anonymous cap was 60 req/hr — the lane could degrade under sustained sweeps | **FIXED 2026-10-14**: `GITHUB_TOKEN` from `.env` now attached (verified 5,000/hr core + 30/min search). |
| Reddit freshness | Very fresh threads can lag pushshift ingests | Mitigated by the Redlib live tier when its window is open. |
| Latency | A fully blocked video can take 60–90s through the sequential tiers | Accepted; the transcript cache removes repeats. |
| Third-party API observability | fxtwitter/tikwm/pullpush/arctic had no monitoring | **FIXED 2026-10-14**: guardian Pattern 5 checks all four every 30 min. |
