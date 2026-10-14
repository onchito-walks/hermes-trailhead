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
| 2 | `proxigram` container (:8790) — Instagram frontend | PARKED (root cause PROVEN 2026-10-14) | All routes HTTP 500. Mechanism proven: its Next.js render worker binds IPv6-only loopback (`::1:<random>`) while the app dials IPv4 `127.0.0.1:<same port>` → ECONNREFUSED per request (cross-family same-port test: IPv4 refused, IPv6 connected; distroless image, Node 18.17.1). No restart-only fix exists. | Needs a code/env change (consistent bind family) plus browser binaries for its scraping path. IG lane does not depend on it. |
| 3 | `social-search` composite tool | RETIRED (docs/chains) | 2026-10-14: binary absent on the fleet; code paths fail through gracefully | Re-list only if the tool is reinstalled **and** verified serving. |
| 4 | Reddit thread content | KNOWN LIMIT | 2026-10-14: Reddit policy-blocks the datacenter IP outright (reproduced via stealth browser); residential routes serve shells/403s in unstable windows; local Redlib serves full threads (330KB verified) in bursts | No code fix; pipeline maximizes attempt diversity (redlib → direct → route pool, shell-skip, 2 rounds) and reports honest `blocked` otherwise. Re-check if Reddit policy changes or a sticky residential route stabilizes. |
| 5 | Remote public Redlib instances / Reddit OAuth | RETIRED | Blocks confirmed July 2026, re-confirmed 2026-10-14 | Do not point config at remote Redlib instances; the local instance is the route. |
| 6 | GitHub lane relevance on numeric queries ("5 axis …") | FIXED 2026-10-14 | Before: query reduced to `axis` → unrelated repos (agent frameworks, AXI controllers). After: `5-axis` → Open5x, Fractal-5-Pro, Gen5X, CARVER_X5 | — |
| 7 | yt-dlp missing from project venv | FIXED 2026-10-14 | Dangling `~/.local/bin/yt-dlp` symlink; YouTube lane degraded to fallbacks | — |
