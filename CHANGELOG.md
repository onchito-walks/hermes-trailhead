# Changelog

All notable changes to **Hermes Trailhead** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

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
- YouTube transcripts via residential proxy rotation (<proxy-provider> + <proxy-provider>),
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