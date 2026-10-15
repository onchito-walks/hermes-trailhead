# Hermes Trailhead

The internet is full of answers that search engines can't reach. Practitioner
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
terrain part of every agent's normal research surface.

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
- **Transcripts** — spoken content from YouTube and TikTok (each platform's own caption track first, full audio transcription when there are none)
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
| **TikTok** | Captions, hashtags, engagement stats; top comments; transcripts (native captions → ASR fallback) | Photo posts: metadata only |
| **Instagram** | Post/reel captions, author, hashtags; full profile pages via authenticated session | Posts: captions; profiles: session-dependent |
| **GitHub** | Repo description, stars, forks, open issues, language, homepage | N/A |
| **Web** | Cleaned page content, canonical docs, forums, PDFs | N/A |

## Product principles

**Free-first, not free-only.** Default paths use public access with no accounts or paid APIs. Residential proxies and stealth browser extraction are escalation paths that make blocked content reachable — not the default.

**Evidence, not coverage theater.** Trailhead says exactly what it found and what it couldn't reach. It never claims to have "searched TikTok" if it only found two dead links.

**Summaries are the product.** Discovery (finding URLs) is plumbing. The product deliverable is the summary, caption, description, or transcript that you can actually read and use.

**Honest about limits.** Login-walled content, JS-rendered shells, VPS IP blocks — these are reported truthfully with caveats, not painted green.

## The Score

**Ask anything; get what the internet actually says — with receipts, and with an honest list of what couldn't be reached.**

*Machine-readable and live: `hermes-trailhead score --live` prints this scorecard with every lane probed against your own host, right now.*

### Part 1 — product dimensions

| Dimension | Grade | What that means in practice |
|---|---|---|
| **Breadth** | **A** | One question fans out across seven platform families at once — video, social, forum, code, and open web — in a single sweep. |
| **Depth** | **A−** | Not links — content: captions, full threads, spoken transcripts, top comments, profile pages, repository facts. |
| **Freshness** | **A** | Platforms are read live — this hour's threads, today's posts — not a stale index. |
| **Authenticated reach** | **A−** | What sits behind a login is reachable too: the account inbox, plus live Instagram and Facebook sessions that persist. |
| **Honesty** | **A** | Blocked is reported blocked, with the reason. Failure is a first-class output, never painted green. |
| **Reliability** | **B+** | Lanes are watched and self-healing; the remaining weak spot (single-route fallbacks) is named openly in the failure ledger. |
| **Effort & cost** | **A** | One command — or just ask your agent. Free-first by default; the entire cache weighs kilobytes, not gigabytes. |

### Part 2 — per-lane grades (verified live, October 14, 2026)

| Lane | Grade | What you get |
|---|---|---|
| **YouTube** | **A** | Full spoken transcripts — captionless videos included |
| **GitHub** | **A** | Repository facts, READMEs, releases, file trees |
| **Web** | **A−** | Clean deep content — docs, forums, PDFs |
| **Reddit** | **A−** | Full threads with comment context |
| **X/Twitter** | **A−** | Structured posts and practitioner discussions |
| **TikTok** | **A−** | Metadata, top comments, and the video's actual spoken words |
| **Instagram** | **A−** | Reel/post captions plus full profile pages |

*Does it really run like this? Yes — every grade was re-verified against live runs on the date shown. A− means "strong, with named edges still worth filing down" — and those edges are listed, not hidden, in [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md). `score --live` re-probes every lane on your own host.*

## Aspirations — where this goes

1. **Every answer arrives with receipts.** Research you can act on without double-checking: quotes, numbers, authors, dates — each traceable to its source, extracted rather than guessed.
2. **Nothing behind a login stays unreachable.** Email, social, membership walls — access matures into infrastructure (insured, monitored, self-healing), and the reachable frontier keeps moving outward.
3. **The front door for every agent in the fleet.** Every bot and workflow asks its research questions here first, because answers come back grounded — and what's learned flows into durable memory, compounding over time.
4. **Depth on every terrain.** The gaps shrink each cycle: photo posts, comment threads, long videos, niche platforms — each becomes just another lane that works.
5. **The lightest path that works.** Prefer the platform's own structured data before brute force — the caption track over the download, the smallest fetch over the crawl. Efficiency is a feature, not an optimization.
6. **Quiet, boring, unbreakable.** Maintenance trends to zero. A lane that breaks announces itself before anyone notices. Trust is earned by being dull.
7. **Value you can hand to someone.** Reports that change decisions — what competitors shipped this week, what practitioners discovered, what the market is actually saying — evidence-first and story-ready.

*The story: a research surface that makes the invisible internet visible — so that no question is answered with "I couldn't find it" when the answer was there the whole time.*

## The landscape — how this compares

Honest map, not trash talk. Most of these are allies — Trailhead routes to several of them when they're the best path.

| Family | Examples | What they're best at | Where Trailhead differs |
|---|---|---|---|
| **Search APIs** | Tavily, Exa, Brave, Serper | Fast, clean web results | Web-only depth; per-call pricing; no platform-native content. Trailhead reads the platforms themselves, free-first. |
| **Scraping platforms** | Firecrawl, Apify, Browserbase | Industrial extraction infrastructure | They are plumbing you assemble; Trailhead is the assembled research product — lanes, failover, evidence rules, honest caveats. |
| **Social data APIs** | Per-platform scraper APIs | Single-platform data at scale | One platform, one key, one bill each; Trailhead is multi-lane, needs no keys by default, and brings-your-own-session for authenticated reach. |
| **Answer engines** | Perplexity, deep-research modes | Synthesized prose answers | Answers from the indexed web with opaque sourcing; Trailhead returns the content itself — with receipts and named blind spots. |
| **Open-source building blocks** | yt-dlp, Jina Reader, Redlib/Nitter frontends, PullPush | Excellent single-purpose access | Not products — parts. Trailhead assembles, supervises, and fails over between them. |

## Future trails worth adding

Ranked by value-to-effort — candidates, not commitments:

| Candidate | Value | Effort | Why it earns a lane |
|---|---|---|---|
| **Hacker News** | High | Trivial | Official API; practitioner gold; front-page signal |
| **Podcasts** | High | Low | RSS feeds + the transcript machinery already built |
| **Bluesky** | High | Trivial | Public API; a growing practitioner base |
| **Stack Overflow / Exchange** | High | Trivial | The deep technical Q&A canon |
| **arXiv / papers** | High | Trivial | Primary research sources, citation-ready |
| **Threads** | Medium | Medium | Meta's API walls — the same session approach as Instagram |
| **LinkedIn** | High | Hard | Aggressive walls; session-based, careful pacing required |
| **Discord communities** | High | Hard | Invite-gated; session-based |
| **Telegram public channels** | Medium | Medium | Public channel API path exists |
| **Twitch** | Medium | Medium | Clips + VOD transcripts |
| **Reviews** (Steam, app stores, G2) | Medium | Low | Buying-decision signal |

## Bring your own accounts (bot-ready logins)

Some of the best terrain sits behind a login: profile pages, membership forums, inboxes that receive verification codes. Trailhead covers that **without ever touching your passwords**:

1. **Run a persistent browser profile** the tool can drive locally (any browser server with a saved profile and a remote screen you can open in a tab).
2. **Sign in once, yourself.** Open the browser's remote screen and log into the accounts you want covered — your fingers, your credentials. Nothing is shared with the agent.
3. **The session persists.** The profile saves its cookies on a clean shutdown; the tool then reads pages through that profile as you. Sign out any time to revoke everything instantly.

Point the authenticated extraction tier at your profile with two environment variables (`TRAILHEAD_CAMOFOX_API`, `TRAILHEAD_CAMOFOX_USER`). With none set, the tool simply skips that tier and continues on its public routes.

Recovery and verification codes land in your email — connect a mailbox (e.g. via OAuth) and the agent can read those too, with your consent and without codes ever entering a conversation.

**This is how the project runs in production.** The reference sessions were captured exactly this way: one manual sign-in in a persistent browser, verified to survive restarts, then reused by every extraction — no password sharing, no cookie handling by the agent.

## Privacy — what never leaves your machine

- **No credentials in this repo.** No passwords, cookies, tokens, or personal emails — verified by a sweep that is part of the release checklist.
- **Sessions live outside the code**, in the browser profile's local files on your machine.
- **Instance specifics are environment configuration** (`HERMES_HOME`, `TRAILHEAD_CAMOFOX_*`), never source code.
- **You are the operator.** The tool only reads pages you've already made accessible to it; logging out of the profile revokes everything.

---

# How it works

**Everything from here down explains the current implementation for the curious. It is explanatory only and subject to change — the product promise lives in everything above.**

## Quick start

```bash
# Full breadth pass across all seven source families
python3 -m hermes_trailhead search all "your research question" --execute --limit 3 --format json

# Check what's available on this install
python3 -m hermes_trailhead doctor

# Per-lane scorecard, with every lane probed live on your host
python3 -m hermes_trailhead score --live

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

# Source-mode: run the full deterministic test suite (274 tests + 100/100 PhD gauntlet)
python3 -m pytest -q
python3 -m hermes_trailhead gauntlet

# Python dev/test dependencies (pytest). Either:
uv sync --group dev          # if using uv
pip install -e ".[dev]"       # or pip
# npm mirrors the Python suite once installed:
npm install && npm test
```

See `docs/HERMES-INTEGRATION.md` for how Trailhead fits into Hermes and Quiver, and [`TEAM.md`](TEAM.md) for the engineering team structure.

## Current state (verified live, October 14, 2026)

`hermes-trailhead doctor --live --record` on a live deployment host: **10 ok / 5 warn / 4 off, 0 fail** across 18 channels. Warnings are watched conditions, not failures — Reddit + frontends flip with the local Redlib upstream windows, and the `hermes-upstream` / `agent-reach` warns are by-design review gates. Scores rank leads; they do not verify claims or authorize automatic GBrain ingestion.

- **Tests:** 274 passing · **PhD gauntlet:** 100/100 — 4 cases, 10 hard-source lanes.
- **Live sweep** (`search all --execute --extract --score`): 7/7 lanes execute; 28 hits discovered, **27/28 with readable content** (the 1 miss = a 17-second speechless clip, reported honestly):
  - web — full page content ✔
  - **x — clean tweet text + engagement (FxTwitter API), local Nitter fallback (tweet + replies)** ✔
  - **reddit — always-on threads (PullPush / Arctic Shift → Redlib live → route pool)** ✔
  - **tiktok — metadata + top comments + real transcripts (platform caption track first; full audio transcription when none)** ✔
  - **instagram — post/reel captions + full profile pages through the authenticated session** ✔
  - **youtube — transcripts (disk cache + JS-runtime + impersonation + timeout headroom) with an ASR tier that covers captionless videos** ✔
  - **github — repo metadata + README excerpt (≈1.3k chars/repo)** ✔

**Reddit threads no longer depend on Redlib's windows.** PullPush + Arctic Shift extraction tiers were added 2026-10-14 — verified 3/3 threads with real content while Redlib was throttled.

**YouTube transcripts are live.** Residential proxy (with pool failover) bypasses YouTube's VPS IP block — thousands of characters of clean, deduplicated auto-captions per video when it serves.

**Instagram public posts and reels extract.** Full captions, hashtags, and engagement data at discovery grade — and profile pages now extract through the authenticated session (verified live: a 104M-follower profile returned its full metadata and page).

**Facebook pages extract** through the same authenticated session tier.

**TikTok goes deep.** Metadata, top comments, and the video's actual spoken words — the platform's own caption track is read first (a tiny text file, near-instant), with full audio transcription as the fallback for videos that have none.

**Web summaries are clean.** HTML is stripped to readable text. GitHub repos return full API metadata.

## Prior art

- **[Agent-Reach](https://github.com/Panniantong/Agent-Reach)** — the direct launchpad for the access doctrine: channel registry, probes, upstream-tool realism
- **Jina Reader, yt-dlp, Tavily, old.reddit.com, local Redlib** — pragmatic access paths for current social/practitioner signal.
  (The local self-hosted Redlib instance serves search and thread pages for the Reddit lane's discovery and extraction fallback; public remote Redlib instances and Reddit OAuth remain blocked. `social-search` is an optional composite tool that is not installed on the current fleet — the Reddit lane does not require it.)
- **Firecrawl, Crawl4AI, Puppeteer** — mature extraction primitives Trailhead routes to, not replaces

## Launchpad

Hermes Trailhead was launched from **[Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)**. Agent-Reach showed the access doctrine worth keeping: use mature upstream tools, probe what is installed, keep fallback routes, and teach agents which path to take. Trailhead gives that doctrine a narrower product mission: better Hermes research through better source terrain.

## License

BSD 3-Clause. See [`NOTICE.md`](NOTICE.md) for prior-art acknowledgments.
