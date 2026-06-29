# Hermes Trailhead Product Architecture

Hermes Trailhead is a Hermes-native research trailhead. Its job is to make Hermes' answers better by sending research tasks into the right high-signal source terrain and bringing back usable evidence with honest caveats.

The architecture is intentionally boring because the product is not the infrastructure. The product is the experience: Hermes knows where to look, uses the safest working route first, returns real links, summaries, transcripts, and says what it could not reach.

## Product promise

For a given research question, Hermes Trailhead answers four operational questions:

1. **Where is the good evidence likely to live?** Web, X, Reddit, TikTok, Instagram, YouTube, GitHub, docs, forums, PDFs, or a mix.
2. **Which route works right now?** Native tools, loginless public search, privacy frontends, residential proxy, browser extraction.
3. **What evidence must come back?** Links, summaries, transcripts, quality scores, and failure/caveat state.
4. **What boundary requires approval?** Paid APIs, account sessions, credentials, posting, global installs.

Everything else is implementation detail.

## Architecture layers

```text
Research question
   ↓
Source terrain decision (7 platform families)
   ↓
Route choice + free-first retrieval
   ↓
Extraction (page content, transcripts, captions, metadata)
   ↓
Quality scoring (canonical → practitioner → community → SEO)
   ↓
Evidence returned (links + summaries + scores + caveats)
   ↓
Hermes synthesis
```

## Product state (June 29, 2026)

### Discovery — 7/7 lanes

| Lane | Engine |
|---|---|
| web | Bing search |
| x | social-search native |
| reddit | social-search native |
| tiktok | Tavily API |
| instagram | Tavily API |
| youtube | yt-dlp flat search |
| github | SearXNG site search |

### Extraction — evidence layer

| Lane | Summaries | Transcripts | Method |
|---|---|---|---|
| YouTube | ✅ descriptions | ✅ 3,000+ chars | yt-dlp via residential proxy (Decodo/DataImpulse rotation) |
| TikTok | ✅ captions + stats | Captions only | oEmbed + rehydration blob |
| Instagram | ✅ post/reel captions | Captions only | HTTP proxy fetch + stealth Chrome for JS shells |
| Reddit | ✅ excerpts | N/A | social-search snippets |
| X | ✅ post text | N/A | social-search snippets |
| GitHub | ✅ repo metadata | N/A | GitHub public API |
| Web | ✅ cleaned HTML | N/A | tiered HTTP (direct → proxy) |

### Scoring — quality ranking

Rule-based 0-100 across six tiers:

- **Canonical** (70-87): official docs, repos, maintainer sites
- **Practitioner** (55-70): Reddit threads, forums, firsthand reports
- **Current** (40-60): recent X/Twitter posts, active issues
- **Technical** (75-85): GitHub issues/PRs, changelogs
- **Community** (25-50): YouTube, TikTok demos, visual evidence
- **SEO/Generic** (10-25): blogs, articles, content mills

Scoring is default on every `search all --execute`.

### Infrastructure

- **Proxy rotation:** Decodo + DataImpulse residential proxies, roundrobin
- **Stealth Chrome:** puppeteer-extra with stealth plugin, proxy-backed, for JS-rendered pages
- **SRT deduplication:** Gemini auto-caption tripling removed, clean readable transcripts
- **HTML cleaning:** raw HTML shells stripped to readable text for web summaries

## Honest remaining limits

| Limit | Reason | Mitigation |
|---|---|---|
| Private Instagram accounts | Follow-approval required, not discoverable | N/A — content doesn't appear in search |
| X/Twitter deep content | Free-tier rate limits | Discovery snippets provide usable summaries |
| TikTok spoken transcripts | No ASR configured | Captions and descriptions are extracted |
| Instagram reel JS shells | Some reels serve no OG metadata | Stealth Chrome fallback renders the page |

## What Trailhead is not

- a crawler
- a browser automation framework
- a scraping toolkit
- a SaaS connector marketplace
- a credential broker
- a social bot
- a generic MCP registry

It is the local Hermes research trailhead: source terrain, route choice, free-first retrieval, evidence requirements, and honest blind spots.
