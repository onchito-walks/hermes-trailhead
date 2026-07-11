# Hermes Trailhead

The internet is full of answers that search engines can''t reach. Practitioner
discussions on X that never make it to Google. Reddit threads with the exact
workaround you need. YouTube videos where someone explains the bug and the fix
but the transcript lives behind a proxy wall. GitHub issues where maintainers
debate the architecture before it becomes a blog post.

Hermes Trailhead makes that terrain accessible to AI agents. It is a research
control plane that spans seven platform families — X/Twitter, Reddit, YouTube,
TikTok, Instagram, GitHub, and the open web — with per-lane backend chains,
automatic failover, and honest blind-spot reporting. When a research question
hits, Trailhead fans out across every reachable source, extracts summaries and
transcripts, ranks results by quality, and returns what it found along with
exactly what it could not reach.

Trailhead exists because the best answer to a technical question is often on a
platform that search engines treat as invisible. It lives to make that invisible
terrain part of every agent''s normal research surface.

## What Trailhead delivers

For any research question, you get:

- **Links** to actual content across all seven source families
- **Summaries** — readable captions, descriptions, and extracted text from every hit
- **Transcripts** — spoken-word transcripts from YouTube videos (via residential proxy)
- **Quality scores** — 0-100 ranking by source authority: canonical > practitioner > current > community > generic > SEO
- **Honest caveats** — platforms that were probed but blocked, content that is login-walled, transcripts that are unavailable
- **Searchable metadata** — author, date, engagement stats (likes/views/shares), repository stars/forks/issues

The output is always `url` + `title` + `summary` + `score` + `transcript_status`. No raw HTML. No JavaScript blocker text. No fake coverage reports.

## Source terrain covered

| Terrain | What you get | Transcripts |
|---|---|---|
| **YouTube** | Video descriptions + full spoken transcripts | ✅ via proxy |
| **Reddit** | Thread titles, dates, excerpts, subreddit context | N/A |
| **X/Twitter** | Post text, author, from practitioner discussions | N/A |
| **TikTok** | Captions, hashtags, engagement stats (hearts/views/comments/shares) | Captions only |
| **Instagram** | Post/reel captions, author, hashtags | Captions only |
| **GitHub** | Repo description, stars, forks, open issues, language, homepage | N/A |
| **Web** | Cleaned page content, canonical docs, forums, PDFs | N/A |

## Product principles

**Free-first, not free-only.** Default paths use public access with no accounts or paid APIs. Residential proxies and stealth browser extraction are escalation paths that make blocked content reachable — not the default.

**Evidence, not coverage theater.** Trailhead says exactly what it found and what it couldn't reach. It never claims to have "searched TikTok" if it only found two dead links.

**Summaries are the product.** Discovery (finding URLs) is plumbing. The product deliverable is the summary, caption, description, or transcript that you can actually read and use.

**Honest about limits.** Login-walled content, JS-rendered shells, VPS IP blocks — these are reported truthfully with caveats, not painted green.

## Current product state (June 29, 2026)

All seven source lanes return links, summaries, and quality scores by default. Extraction and scoring are automatic — no flags needed.

```
web        ✅  canonical docs    score: 87
x          ✅  practitioner posts score: 45
reddit     ✅  thread excerpts    score: 70
tiktok     ✅  captions + stats   score: 30
instagram  ✅  post/reel captions score: 25
youtube    ✅  full transcripts   score: 50
github     ✅  repo metadata      score: 70
```

**YouTube transcripts are live.** Residential proxy rotation (Decodo + DataImpulse) bypasses YouTube's VPS IP block. 3,000+ characters of clean, deduplicated auto-captions per video.

**Instagram public posts and reels extract.** Proxy-backed HTTP fetching and stealth Chrome with browser fingerprinting bypass login walls. Full captions, hashtags, and engagement data.

**TikTok captions are rich.** oEmbed returns author, description, hashtags, and engagement stats.

**Web summaries are clean.** HTML is stripped to readable text. GitHub repos return full API metadata.

## Quick start

```bash
# Full breadth pass across all seven source families
python3 -m hermes_trailhead search all "your research question" --execute --limit 3 --format json

# Check what's available on this install
python3 -m hermes_trailhead doctor

# Run the deterministic product contract (no network dependency)
python3 -m hermes_trailhead gauntlet
```

## Install

```bash
# Put the hermes-trailhead command on PATH for this machine
sudo bash scripts/install-hermes-trailhead-wrapper.sh

# Verify the active install
hermes-trailhead doctor

# Source-mode fallback
python3 -m pytest -q
python3 -m hermes_trailhead doctor
```

See `docs/HERMES-INTEGRATION.md` for how Trailhead fits into Hermes and Quiver.

## What Trailhead is not:

- a crawler
- a browser automation framework
- a scraping toolkit
- a SaaS connector marketplace
- a credential broker
- a social bot
- a public MCP registry

It is the local Hermes research trailhead: source terrain, route choice, free-first retrieval, evidence requirements, and honest blind spots.

See [`TEAM.md`](TEAM.md) for the engineering team structure.

## Prior art

- **[Agent-Reach](https://github.com/Panniantong/Agent-Reach)** — the direct launchpad for the access doctrine: channel registry, probes, upstream-tool realism
- **Jina Reader, yt-dlp, Redlib, Tavily, social-search** — pragmatic access paths for current social/practitioner signal
- **Firecrawl, Crawl4AI, Puppeteer** — mature extraction primitives Trailhead routes to, not replaces

## Launchpad

Hermes Trailhead was launched from **[Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)**. Agent-Reach showed the access doctrine worth keeping: use mature upstream tools, probe what is installed, keep fallback routes, and teach agents which path to take. Trailhead gives that doctrine a narrower product mission: better Hermes research through better source terrain.

## License

BSD 3-Clause. See [`NOTICE.md`](NOTICE.md) for prior-art acknowledgments.
