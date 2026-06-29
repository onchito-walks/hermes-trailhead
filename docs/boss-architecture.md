# Hermes Trailhead Product Architecture

Hermes Trailhead is a Hermes-native research trailhead. Its job is to make Hermes' answers better by sending research tasks into the right high-signal source terrain and bringing back usable evidence with honest caveats.

The architecture is intentionally boring because the product is not the infrastructure. The product is the experience: Hermes knows where to look, uses the safest working route first, returns real links and excerpts, and says what it could not reach.

## Product promise

For a given research question, Hermes Trailhead should answer four operational questions:

1. **Where is the good evidence likely to live?** Generic web, X, Reddit, TikTok, Instagram, YouTube, GitHub, docs, forums, PDFs, browser-only pages, or a mix.
2. **Which route works right now?** Native Hermes tools, loginless public search, privacy frontends, GitHub MCP, media tools, browser tools, or an approved external connector.
3. **What evidence must come back?** Working links, counts, extracted text, comments, transcripts, issue threads, source quality notes, and failure/caveat state.
4. **What boundary requires approval?** Cookies, browser sessions, credentials, paid APIs, posting, global installs, account mutation.

Everything else is implementation detail.

## Why Agent-Reach mattered

Agent-Reach was the launchpad because it had the right access realism: do not build bespoke scrapers for everything; identify mature upstream tools, probe what exists, document fallbacks, and give the agent durable instructions.

Hermes Trailhead keeps that doctrine but narrows the product. Agent-Reach is broad capability bootstrap. Trailhead is Hermes research quality: better terrain, better routes, better evidence, better caveats.

## Architecture layers

```text
Research question
   ↓
Source terrain decision
   ↓
Route choice + approval boundary
   ↓
Free-first retrieval / action plan
   ↓
Evidence returned + caveats
   ↓
Hermes synthesis
```

## Current code slice

| Layer | Current implementation | Product role |
|---|---|---|
| Source terrain | `search.py` platform plans: web, X, Reddit, TikTok, Instagram, YouTube, GitHub | Makes source families explicit instead of hiding them behind generic search. |
| Route choice | `router.py` task routes | Chooses known-URL read, discovery, social/current signal, extraction, browser work, or external tool enablement. |
| Capability state | `channels.py` checks | Prevents fake coverage claims by showing what the local Hermes install can actually use. |
| Evidence contract | dataclasses + JSON formatters | Gives Hermes structured fields for links, counts, status, caveats, and approval requirements. |
| Operator UX | CLI commands | Lets humans and agents inspect, execute, and verify source routes. |

## Product principles encoded in the architecture

### Free-first retrieval

The default path should work without paid APIs. `search --execute` uses loginless public search rendered through Jina Reader and DuckDuckGo HTML. That is not the final ideal retrieval system, but it proves the product can return real links across source families without paid API dependence.

### Honest weak lanes

TikTok, Instagram, and X are difficult. The architecture should represent that honestly: discoverable links are not the same as deeply readable posts; configured `x_search` is not the same as a local Nitter fallback; browser/session routes are not the same as accountless access.

### Evidence as data

Every machine-readable path should carry enough data for Hermes to avoid overclaiming: source family, query, route, status, result count, working URL, extraction attempt, caveat, approval requirement.

### Approval boundaries as data

Approval requirements must be fields, not vibes. A route involving account sessions, cookies, paid services, posting, or global installation must be machine-readable as approval-required.

### Upstream tools, not bespoke heroics

Trailhead should route to mature tools — web_extract, GitHub MCP, Jina Reader, Redlib/Nitter-style frontends, yt-dlp/media tools, Firecrawl, Crawl4AI, Stagehand, Browserbase — instead of inventing custom scrapers when established tools exist.

## Current state (June 29, 2026)

### ✅ Working — production-grade

| Capability | Status | Engine |
|---|---|---|
| Discovery — all 7 lanes | 7/7 green | yt-dlp (YouTube), social-search (Reddit/X), Tavily (TikTok/Instagram), Bing (web/GitHub) |
| Page content extraction | Working | Tiered HTTP: direct→proxy→raise; extracts 4-5KB per hit |
| Source quality scoring | Working | Rule-based 0-100: canonical/docs/practitioner/community/SEO tiers |
| Gauntlet (product contract) | 100/100 | 154 tests, 4 PhD cases, 10 hard-source lanes |
| Video evidence metadata | Working | yt-dlp flat metadata (title, duration, URL) |

### ❌ Blocked — genuine architectural limits

| Capability | Blocker | Root cause |
|---|---|---|
| YouTube caption transcripts | VPS IP blocked | YouTube's anti-bot measures reject transcript API from datacenter IPs. yt-dlp JS runtime fix (node configured June 29) only helps with metadata, not transcript access. |
| TikTok/Instagram deep extraction | Login-walled | Both platforms require authenticated sessions for content access. Discovery works (Tavily API). Extraction of known URLs works (oEmbed, internal API, stealth Chrome). Broad extraction without auth is architecturally impossible. |
| X/Twitter deep extraction | Rate-limited | Free-tier Nitter/SearXNG work for discovery links. Full post content requires `x_search` (Hermes native tool) or X API credits. |

### ⚠️ Partial — built but not default

| Capability | State |
|---|---|
| `--extract --score` workflow | Works when explicitly requested. Not the default search path. Extraction is ~10s per hit. |
| Transcript extraction from non-VPS IPs | Works (multiple backends: yt-dlp, YouTube API, stealth Chrome). Tested from residential IPs. |
| Browser-harness extraction | Built (stealth Chrome backend) but requires browser session. Not part of default free-first path. |

### ❌ Not built — specified but never implemented

| Capability | Spec location |
|---|---|
| Weekly operating loop / reliability dashboard | `docs/boss-architecture.md` P1 |
| Capability import from MCP catalogs | `docs/boss-architecture.md` P1 |
| Empirical PhD-level equivalence testing | `docs/boss-architecture.md` P2 |
| Automated `--extract --score` on every `search all` | TEAM.md verification checklist |

## Next architecture bets (prioritized by product impact)

### Immediate — unblock what's blocked

1. **YouTube transcript lane via residential proxy or browser session.** The extraction pipeline works (yt-dlp transcript, stealth Chrome, YouTube API). The blocker is IP reputation. Options: SSH tunnel through residential IP, browser session with logged-in YouTube, or paid transcript API (YouTube Data API v3 has a free tier).

2. **Make `--extract --score` the default for `search all`.** The pipeline works when explicitly requested. Making it the default closes the gap between "can discover" and "returns usable evidence."

### Short-term — complete the evidence pipeline

3. **source_type classification fix.** Hits from YouTube/TikTok/Instagram should be classified as `video` or `social` in extraction output. Currently some show `None`.

4. **Scored output in gauntlet.** The gauntlet tests product contracts but doesn't verify scoring output shape. Add scoring assertions to gauntlet cases.

### Medium-term — operating loop

5. **Weekly health cron.** Automate the weekly review: gauntlet + benchmark + doctor, report lane health trends, flag newly blocked platforms. Save to GBrain.

6. **Reliability history.** The `reliability.py` module exists but isn't wired into a cron or dashboard. Wire it.

## Non-goals

Hermes Trailhead should not become:

- a crawler
- a browser automation framework
- a scraping toolkit
- a SaaS connector marketplace
- a credential broker
- a social bot
- a generic MCP registry

It should remain the Hermes layer that knows source terrain, chooses routes, retrieves evidence, and reports blind spots.
