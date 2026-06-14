# Hermes Reach

Hermes Reach helps Hermes and other command-line agents search and read the hard-to-reach parts of the internet.

It is for sources that general web search and basic page fetchers often miss, block, truncate, or return poorly:

- X/Twitter posts, timelines, and maintainer discussion
- Reddit posts and comment threads
- TikTok, Instagram, and YouTube creator/media surfaces
- GitHub repositories, issues, PRs, and release activity
- PDFs, docs, dynamic pages, browser-only sites, and future MCP/API tools

For each task, Hermes Reach tells the agent which path to use, what is not configured yet, what requires approval, and what evidence proves the result worked.

The “reach map” is the mechanism: a local inventory of source families, available tools, fallback routes, setup gaps, and proof requirements. The point is broader, more reliable internet reach.

## Why it exists

Modern agents have a lot of possible internet surfaces:

- web search
- page/PDF extraction
- X/Twitter search and Nitter fallbacks
- Reddit search and Redlib fallbacks
- TikTok / Instagram / YouTube discovery
- GitHub repos, issues, and PRs
- crawlers such as Firecrawl and Crawl4AI
- browser automation through Hermes browser tools, Browserbase, Stagehand, or browser-use
- MCP servers and SaaS integration catalogs
- local CLIs and privacy frontends

The hard part is not simply “can the agent access the internet?” The hard part is knowing **which surface gives the best coverage for this task**, whether that surface is currently configured, and whether the resulting links/data actually work.

Hermes Reach exists to make hard-to-reach sources usable from an agent harness without overstating what is actually configured.

## What it does

Hermes Reach has four jobs:

1. **Inventory reach** — show what channels are available, missing, weak, or risky.
2. **Route tasks** — choose the best search/read/browser/social path for a given request.
3. **Expose gaps** — say plainly when TikTok, Instagram, X, Reddit, or another channel is not really covered yet.
4. **Require evidence** — make the agent prove retrieved links/data work before claiming success.

It is supposed to answer practical questions like:

- “Can my agent actually search X right now?”
- “Can it read Reddit without giving me dead links?”
- “Do I have a TikTok or Instagram path, or is that source family not configured yet?”
- “Should this use web search, Redlib, Nitter, a browser session, Firecrawl, or an MCP tool?”
- “What should I install/configure next to increase reach?”

## Reach map

| Source family | Best current path | What Hermes Reach should report |
|---|---|---|
| Open web | Hermes `web_search`, `web_extract` | available path, query count, extracted sources |
| Known URL/PDF | `web_extract`, Jina Reader fallback | source URL, extraction status, failure reason if any |
| X/Twitter | `x_search` if credentialed, Nitter fallback | credential/frontend status, retrieved posts, working links |
| Reddit | `reddit-search`, Redlib links | subreddits/queries checked, retrieved posts, working Redlib links |
| TikTok | `site:tiktok.com` search, media/frontends/browser when configured | whether a real reader exists; otherwise mark as a gap |
| Instagram | `site:instagram.com` search, frontend/browser when configured | whether a real reader exists; otherwise mark as a gap |
| YouTube | media tools / `yt-dlp` when available | video results, transcript/metadata availability |
| GitHub | GitHub MCP / `gh` | repo/issue/PR path and auth boundary |
| Dynamic sites | Hermes browser tools, Browserbase, Stagehand, browser-use | account/session boundary and screenshot/log evidence |
| Crawl/extract | Firecrawl, Crawl4AI, Exa, Jina Reader | chosen extractor, fixture URL, schema/output evidence |
| External tools | MCP catalogs, Agent-Reach-like tools, SaaS connectors | setup status, required credentials, approval boundary |

The important behavior: if a source family is not actually reachable yet, Hermes Reach should say **not configured** or **gap**, not imply coverage.

## Install

From a checkout:

```bash
python3 -m pytest -q
python3 -m hermes_reach doctor
```

Editable install:

```bash
uv venv .venv
. .venv/bin/activate
uv pip install -e .
hermes-reach doctor
```

## Core commands

```bash
# Check capability health with evidence
python3 -m hermes_reach doctor
python3 -m hermes_reach doctor --format json

# Show prioritized gaps
python3 -m hermes_reach queue
python3 -m hermes_reach queue --risk high --top 3

# Ask the router what path a task should use
python3 -m hermes_reach route "search X, TikTok, Instagram, Reddit, and YouTube for Hermes Agent discussion"
python3 -m hermes_reach route "read this known url as markdown"
python3 -m hermes_reach route "login to a site and fill a form"
python3 -m hermes_reach route "extract schema from website"

# List all routing rules
python3 -m hermes_reach routes

# Emit an agent-facing brief
python3 -m hermes_reach agent-brief

# Print a safe setup plan for one channel
python3 -m hermes_reach plan x-search
python3 -m hermes_reach plan tiktok
python3 -m hermes_reach plan instagram
```

## Example: broad social/current search

```bash
python3 -m hermes_reach route "search X, Reddit, TikTok, Instagram, YouTube and the web for current Hermes Agent discussion"
```

Output shape:

```text
# Hermes Reach route: social-current-signal

Task: Current social/maintainer/community signal across X, Reddit, TikTok, Instagram, YouTube, and the public web
Primary: x_search/Nitter for X, Redlib/reddit-search for Reddit, yt-dlp/media tools for YouTube, privacy-frontends or supervised browser for TikTok/Instagram
Fallbacks: social-search, Nitter profile pagination, reddit-search with structured metadata, ProxiTok/alternative TikTok frontends when available, Bibliogram/Instagram frontends when available, web_search site:x.com/site:reddit.com/site:tiktok.com/site:instagram.com
Avoid: posting, cookie auth, claiming all posts from one page, reporting TikTok/Instagram coverage when no frontend/API/browser path is configured
Approval required: yes

Evidence required before claiming success:
- platforms checked
- handles/subreddits/queries
- time window
- retrieved count per platform
- dead-link/coverage caveat
```

That is the product: **broader reach, explicit gaps, working links, and evidence**.

## Architecture

Hermes Reach is intentionally boring.

```text
User task
   ↓
Reach inventory
   ↓
Router
   ↓
Capability channel
   ↓
Coverage, link, and evidence check
```

The code is split into three pieces:

| File | Purpose |
|---|---|
| `hermes_reach/channels.py` | Capability inventory and setup plans. |
| `hermes_reach/router.py` | Task-class routing rules. |
| `hermes_reach/cli.py` | Human and machine-readable commands. |

The main data model is plain Python dataclasses. Output is text, Markdown, or JSON.

## Safety model

Hermes Reach is read-only by default.

It does **not** automatically:

- install global packages
- read browser cookies
- dump environment variables
- write credentials
- post to social platforms
- mutate Hermes config
- buy API credits

High-risk routes and channels are marked `approval_required` in machine-readable output.

Examples of high-risk work:

- browser sessions tied to a real account
- cookie extraction
- paid API setup
- social posting
- global installer scripts
- credential storage

## Loginless-first search

Hermes Reach prefers search paths that do not require personal logins when the task allows it:

1. Search with public or configured search surfaces.
2. Read pages with clean readers like `web_extract` or Jina Reader.
3. Use privacy frontends such as SearXNG, Nitter, Redlib, ProxiTok-like tools, or other public mirrors when appropriate.
4. Use browser automation only when the page truly needs session state or interaction.
5. Require approval before touching cookies, accounts, paid APIs, or posting surfaces.

## Prior art

Hermes Reach is not claiming to be first. It is a local reach-and-routing take on ideas from several strong projects.

### Agent capability and MCP ecosystems

- [Agent-Reach](https://github.com/Panniantong/Agent-Reach) inspired the initial pattern: channel registry, doctor checks, and setup plans.
- [Composio](https://composio.dev/) shows the value of a broad tool catalog, managed auth, and meta-tools.
- [Pipedream Connect / MCP](https://pipedream.com/docs/connect/mcp) shows managed API integration at large scale.
- [Arcade.dev](https://docs.arcade.dev/) shows a clean split between tool catalog, runtime, and authorization.
- [Zapier MCP](https://zapier.com/mcp) shows the value of low-friction SaaS action surfaces.
- The [official MCP Registry](https://modelcontextprotocol.io/registry/about), [Glama](https://glama.ai/mcp/servers), and [PulseMCP](https://www.pulsemcp.com/servers) show the discovery/catalog side of the ecosystem.

### Browser, crawl, and extraction engines

Hermes Reach does not replace these tools. It routes to them when they fit.

- [Firecrawl](https://docs.firecrawl.dev/) for crawl/search/extract APIs.
- [Crawl4AI](https://docs.crawl4ai.com/) for open, deterministic crawl/extract workflows.
- [Browserbase](https://docs.browserbase.com/) for hosted browser infrastructure and persistent contexts.
- [Stagehand](https://docs.stagehand.dev/) for browser primitives like act, observe, and extract.
- [browser-use](https://github.com/browser-use/browser-use) for agentic browser automation.
- [Playwright MCP](https://github.com/microsoft/playwright-mcp) for structured browser control through MCP.
- [Jina Reader](https://jina.ai/reader/) for URL-to-markdown reading.
- [Exa](https://exa.ai/docs/reference/search) for semantic search and extraction.

### Social/current-signal tools

This is central to the project goal: broad current-world search across sources that are often difficult for agents to access reliably.

- X/Twitter search APIs and Nitter-style frontends.
- Reddit search and Redlib-style frontends.
- TikTok and Instagram public search/frontends where available.
- YouTube transcript/metadata tools.
- Site-specific web search when a dedicated reader is missing.

## What Hermes Reach is not

Hermes Reach is not:

- a public MCP registry
- a SaaS integration marketplace
- a browser automation framework
- a crawler
- a scraping toolkit
- a social bot
- a credential manager

It is the small local layer that tells an agent which of those things to use, what is missing, and how to prove the result worked.

## Tests

```bash
python3 -m py_compile hermes_reach/*.py
python3 -m pytest -q
```

The test suite covers:

- CLI JSON contract stability
- approval gates
- no-secret-output regressions
- router decision quality
- route serialization
- queue/filter behavior
- public README safety claims

## Weekly company loop

A healthy reach map needs maintenance. The intended weekly loop is:

1. Run tests.
2. Check for bugs and security regressions.
3. Review state-of-the-art changes in social search, current-signal tooling, MCP registries, crawlers, browser runtimes, and loginless search.
4. Propose concrete channel additions: X, Reddit, TikTok, Instagram, YouTube, GitHub, web, PDFs, browsers, MCP tools.
5. Update docs when positioning or prior art changes.

## License and attribution

Hermes Reach is open source under the BSD 3-Clause License. You may use, modify, and redistribute it, but you must preserve the copyright notice and license text.

See `NOTICE.md` for prior-art acknowledgments.
