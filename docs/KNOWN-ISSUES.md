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
| 1 | `proxitok-web` container (:8791) — TikTok frontend | PARKED | 2026-10-14: content routes return 404 / `API error code 3 (EMPTY_RESPONSE)`; container log shows chromedriver `TimeoutException` while scraping TikTok | Try a clean restart chain (redis → chromedriver → web) / newer image; may be a TikTok-side datacenter block. TikTok lane does not depend on it (discovery + captions work). |
| 2 | `proxigram` container (:8790) — Instagram frontend | PARKED | 2026-10-14: all routes HTTP 500; logs loop `connect ECONNREFUSED 127.0.0.1:32859` | Inspect its internal provider process / env; IG lane does not depend on it (discovery + captions work). |
| 3 | `social-search` composite tool | RETIRED (docs/chains) | 2026-10-14: binary absent on the fleet; code paths fail through gracefully | Re-list only if the tool is reinstalled **and** verified serving. |
| 4 | Reddit thread content | KNOWN LIMIT | 2026-10-14: Reddit policy-blocks the datacenter IP outright (reproduced via stealth browser); residential routes serve shells/403s in unstable windows; local Redlib serves full threads (330KB verified) in bursts | No code fix; pipeline maximizes attempt diversity (redlib → direct → route pool, shell-skip, 2 rounds) and reports honest `blocked` otherwise. Re-check if Reddit policy changes or a sticky residential route stabilizes. |
| 5 | Remote public Redlib instances / Reddit OAuth | RETIRED | Blocks confirmed July 2026, re-confirmed 2026-10-14 | Do not point config at remote Redlib instances; the local instance is the route. |
| 6 | GitHub lane relevance on numeric queries ("5 axis …") | FIXED 2026-10-14 | Before: query reduced to `axis` → unrelated repos (agent frameworks, AXI controllers). After: `5-axis` → Open5x, Fractal-5-Pro, Gen5X, CARVER_X5 | — |
| 7 | yt-dlp missing from project venv | FIXED 2026-10-14 | Dangling `~/.local/bin/yt-dlp` symlink; YouTube lane degraded to fallbacks | — |
