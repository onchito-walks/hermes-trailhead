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

## Mission

Make the hard-to-reach, high-signal internet part of every agent's normal research surface.

## Goals

1. **Find evidence where it actually lives.** Seven source families — X/Twitter, Reddit, YouTube, TikTok, Instagram, GitHub, and the open web — each with its own discovery chain and automatic failover.
2. **Take the best free-first route that works right now.** Loginless public access by default; privacy frontends, residential proxies, and browser escalation are fallbacks, not requirements. No accounts, no paid APIs by default.
3. **Return evidence, not coverage theater.** Every hit ships as `url + title + summary + score + transcript_status`, with honest caveats for anything that could not be reached.
4. **Rank by source authority.** 0–100 quality scores across canonical → practitioner → current → community → generic → SEO tiers.
5. **Say what is blind.** Blocked lanes, login walls, and dead links are reported as such — never painted green.

## Non-goals

Trailhead is **not** a crawler, a browser automation framework, a scraping toolkit, a SaaS connector marketplace, a credential broker, a social bot, or a public MCP registry. Generic web fetch/extract/crawl and browser automation are **Hermes-native** capabilities that Trailhead routes to; Trailhead owns source terrain, route choice, evidence requirements, and honest blind spots.

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

## Current product state (October 14, 2026 — verified live)

`hermes-trailhead doctor --live --record` on Oracle: **10 ok / 4 warn / 4 off, 0 fail**. Warnings are watched conditions, not failures — Reddit flips `ok`↔`warn` with the local Redlib upstream windows, and the `hermes-upstream` / `agent-reach` warns are by-design review gates. Scores rank leads; they do not verify claims or authorize automatic GBrain ingestion.

- **Tests:** 230 passing (from 218 this morning) · **PhD gauntlet:** 100/100 — 4 cases, 10 hard-source lanes.
- **Live sweep** (`search all --execute --extract --score`): 7/7 lanes execute; 21 hits discovered, 16/21 with readable content:
  - web, github, x — full content extraction ✔
  - tiktok, instagram — captions + engagement metadata ✔
  - youtube — transcripts via residential proxy when YouTube serves them (2/3 on the last sweep)
  - reddit — discovery always; thread content is best-effort (local Redlib window or old.reddit through the residential route pool, shell-skipping and failover — see "Honest limits" in `docs/boss-architecture.md`)

**YouTube transcripts are live.** Residential proxy rotation (<proxy-provider> + <proxy-provider>, with pool failover) bypasses YouTube's VPS IP block — 3,000+ characters of clean, deduplicated auto-captions per video when it serves.

**Instagram public posts and reels extract.** Proxy-backed HTTP fetching and stealth Chrome with browser fingerprinting bypass login walls. Full captions, hashtags, and engagement data at discovery grade.

**TikTok captions are rich.** oEmbed + rehydration blob return author, description, hashtags, and engagement stats.

**Web summaries are clean.** HTML is stripped to readable text. GitHub repos return full API metadata.

## Quick start

```bash
# Full breadth pass across all seven source families
python3 -m hermes_trailhead search all "your research question" --execute --limit 3 --format json

# Check what's available on this install
python3 -m hermes_trailhead doctor

# Run the deterministic product contract (no network dependency)
python3 -m hermes_trailhead gauntlet

# Emit a repeatable research deliverable (writes docs/outcome-loop/deliverable-<slug>.md)
python3 -m hermes_trailhead report "your research question" --out docs/outcome-loop
```

## Install

```bash
# Put the hermes-trailhead command on PATH for this machine
sudo bash scripts/install-hermes-trailhead-wrapper.sh

# Verify the active install
hermes-trailhead doctor

# Source-mode: run the full deterministic test suite (196 tests + 100/100 PhD gauntlet)
python3 -m pytest -q
python3 -m hermes_trailhead gauntlet

# Python dev/test dependencies (pytest). Either:
uv sync --group dev          # if using uv
pip install -e ".[dev]"       # or pip
# npm mirrors the Python suite once installed:
npm install && npm test
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
- **Jina Reader, yt-dlp, Tavily, old.reddit.com, local Redlib** — pragmatic access paths for current social/practitioner signal.
  (The local self-hosted Redlib instance serves search and thread pages for the Reddit lane's discovery and extraction fallback; public remote Redlib instances and Reddit OAuth remain blocked. `social-search` is an optional composite tool that is not installed on the current fleet — the Reddit lane does not require it.)
- **Firecrawl, Crawl4AI, Puppeteer** — mature extraction primitives Trailhead routes to, not replaces

## Launchpad

Hermes Trailhead was launched from **[Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)**. Agent-Reach showed the access doctrine worth keeping: use mature upstream tools, probe what is installed, keep fallback routes, and teach agents which path to take. Trailhead gives that doctrine a narrower product mission: better Hermes research through better source terrain.

## License

BSD 3-Clause. See [`NOTICE.md`](NOTICE.md) for prior-art acknowledgments.
