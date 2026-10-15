---
name: hermes-trailhead
description: Use for hard-source research via Hermes Trailhead — one command fans out across X, Reddit, YouTube, TikTok, Instagram, GitHub, and the open web, returning content with transcripts, quality scores, and honest caveats.
---

# Hermes Trailhead

Trailhead is a research CLI that fans one question out across seven source
families, extracts readable content (not just links), ranks results by source
quality, and reports exactly what it could not reach. Use it whenever a
research question would benefit from practitioner discussion, platform-native
content, or spoken transcripts — and prefer it over generic web search for
anything social, technical, or "where do people actually talk about this".

## Start here

```bash
hermes-trailhead doctor        # what's available on THIS machine — always run first
```

`doctor` is the local truth: it shows which lanes are ready, which are
degraded, and why. Never assume a lane works because the README says so —
doctor is the reality check.

## Core commands

```bash
# Full fanout across all seven lanes (the workhorse)
hermes-trailhead search all "your research question" --execute --extract --score --limit 3 --extract-limit 3 --format json

# Single lane when you know where the answer lives
hermes-trailhead search x "query" --execute --extract --limit 5 --format json
hermes-trailhead search youtube "query" --execute --extract --format json

# Discovery only (fast, no extraction)
hermes-trailhead search all "query" --execute --limit 5 --format json

# Reliability trends per lane; deterministic product contract
hermes-trailhead reliability
hermes-trailhead gauntlet
```

Output formats: `--format json` (machine), `text` (human). With `--score`,
hits are ranked by source authority (canonical > practitioner > current >
community > generic > SEO) and `extracted[]` is sorted by score — join by URL
when `--extract-limit` < hit count.

## What each lane gives you

| Lane | Content |
|---|---|
| youtube | Video descriptions + full spoken transcripts (captionless included via ASR fallback) |
| reddit | Thread titles, dates, excerpts, subreddit context |
| x | Post text, author, engagement from practitioner discussions |
| tiktok | Captions, hashtags, stats, top comments, transcripts (native captions first) |
| instagram | Post/reel captions, hashtags; full profile pages when a session is configured |
| github | Repo metadata, README excerpt, stars/forks/issues |
| web | Cleaned page content — docs, forums, PDFs |

## Reading results honestly

- Every hit is `url + title + summary + score + transcript_status`. **The
  summary is the product** — if a hit has no summary, treat it as a lead, not
  evidence.
- **Blocked is reported blocked, with the reason.** A lane returning `blocked`
  or empty is normal operation — report it to the user as a blind spot rather
  than retrying endlessly or padding the answer.
- Check `caveats` in the JSON before summarizing. They name what degraded
  (proxy windows, login walls, rate limits) so you can say it plainly.

## Optional: authenticated reach

Instagram profiles (and other login-walled pages) extract through a persistent
browser session **the user sets up themselves** — passwords are never handled
by the agent. If `TRAILHEAD_CAMOFOX_API` and `TRAILHEAD_CAMOFOX_USER` are set,
the tier is active; otherwise it skips silently and public routes continue.
See the README section "Bring your own accounts" for the one-time setup.

## Operations

- **Install:** clone the repo, run `sudo bash scripts/install-hermes-trailhead-wrapper.sh`
  (or `TRAILHEAD_BIN=~/.local/bin/hermes-trailhead bash scripts/...` without sudo).
  Zero runtime dependencies — Python stdlib only.
- **Update:** `git pull` in the repo. That's it.
- **Troubleshooting:** `hermes-trailhead doctor` first; then
  `docs/KNOWN-ISSUES.md` in the repo for the failure ledger and workarounds.
- **Tests (before/after any change):** `python3 -m pytest -q` and
  `python3 -m hermes_trailhead gauntlet`.

## Rules of engagement

- Free-first: default paths use public access; no accounts or paid APIs needed.
- One question → one fanout. Don't fire per-lane searches when `search all`
  answers it.
- Report the receipts: quote what the extraction actually returned; name the
  lanes that were blind.
