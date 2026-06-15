# Hermes Trailhead

**Hermes Trailhead makes the hard-to-reach, high-signal internet part of Hermes' normal research plane.**

Ask Hermes a research question. Hermes Trailhead maps the likely source terrain, takes the best free-first routes into the places where frontier/practitioner signal actually lives — X/Twitter, Reddit, TikTok, Instagram, YouTube, GitHub, forums, docs, PDFs, and niche communities — then returns with real links, evidence, source caveats, and the blind spots it could not close.

It exists because generic web search overweights SEO pages, stale summaries, and easy-to-index content. The useful answer is often buried in a maintainer post, a Reddit thread, a creator demo, a GitHub issue, a forum reply, or a platform-native conversation that normal search misses or ranks poorly.

## Mission

Hermes Trailhead should make Hermes feel like it knows where the good internet lives:

1. **Find the terrain** — identify which high-signal surfaces matter for a question.
2. **Take working routes** — use free/open/loginless paths first, with paid APIs only as optional accelerators.
3. **Bring back goods** — return links, excerpts, comments, transcripts, issue threads, and other usable evidence where reachable.
4. **Rank signal over sludge** — prefer practitioner/frontier/maintainer/firsthand sources over SEO filler.
5. **Be honest about blocked paths** — report weak, dead, blocked, or shallow coverage instead of pretending every platform was deeply searched.

## Launchpad and inspiration

Hermes Trailhead was launched from an earlier project named SourceScout, which itself began as a Hermes-specific response to **[Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)**.

Agent-Reach is the honest launchpad: it showed the right access doctrine for agent internet reach — choose the best current upstream tools, probe them, keep fallback routes, and teach the agent how to use them instead of pretending one scraper can own every platform. Hermes Trailhead keeps that lesson and gives explicit credit.

The mission is different and narrower: Agent-Reach is a broad capability bootstrapper for many agents; Hermes Trailhead is a Hermes-native research trailhead. Its job is not merely to install tools. Its job is to make Hermes' answers better by making hard-to-reach, high-signal sources part of the research experience.

## Source terrain

Hermes Trailhead focuses on sources that general web search and basic page fetchers often miss, block, truncate, or return poorly:

- X/Twitter posts, timelines, maintainer discussion, and frontier builder chatter
- Reddit posts and comment threads where practitioners debug real problems
- TikTok, Instagram, and YouTube creator/media surfaces where demos appear early
- GitHub repositories, issues, PRs, releases, and maintainer discussions
- forums, PDFs, docs, dynamic pages, browser-only sites, and future MCP/API tools

For each task, Hermes Trailhead tells the agent which route to use, what is not configured yet, what requires approval, what evidence proves the result worked, and where the map is still incomplete.

The default paths prefer open-source tools, public pages, privacy frontends, local CLIs, and existing Hermes tools. Paid APIs can be modeled as optional accelerators, but Hermes Trailhead should not depend on them for its core promise.

## Install

From a checkout:

```bash
python3 -m pytest -q
python3 -m hermes_trailhead doctor
```

Editable install:

```bash
uv venv .venv
. .venv/bin/activate
uv pip install -e .
hermes-trailhead doctor
```

## Core commands

```bash
# Check capability health with evidence
python3 -m hermes_trailhead doctor
python3 -m hermes_trailhead doctor --format json

# Show prioritized gaps
python3 -m hermes_trailhead queue
python3 -m hermes_trailhead queue --risk high --top 3

# Ask the router what path a task should use
python3 -m hermes_trailhead route "search X, TikTok, Instagram, Reddit, and YouTube for Hermes Agent discussion"
python3 -m hermes_trailhead route "read this known url as markdown"
python3 -m hermes_trailhead route "login to a site and fill a form"
python3 -m hermes_trailhead route "extract schema from website"

# Build a agent-usable search action plan
python3 -m hermes_trailhead search all "Hermes Agent discussion" --format json
python3 -m hermes_trailhead search reddit "Hermes Agent" --format json
python3 -m hermes_trailhead search tiktok "Hermes Agent" --live

# Execute the search through loginless public search paths and return real hits
python3 -m hermes_trailhead search all "Hermes Agent discussion" --execute --limit 3 --format json

# List all routing rules
python3 -m hermes_trailhead routes

# Emit an agent-facing brief
python3 -m hermes_trailhead agent-brief

# Print a safe setup plan for one channel
python3 -m hermes_trailhead plan x-search
python3 -m hermes_trailhead plan tiktok
python3 -m hermes_trailhead plan instagram
```

## agent-usable search plans

`hermes-trailhead search` is the agent-facing command. By default it emits a structured action plan that Hermes can execute with its own tools (`web_search`, `web_extract`, `x_search`, GitHub MCP, browser tools, media tools) without requiring paid APIs. With `--execute`, it also executes search through loginless public search pages rendered by Jina Reader and returns real retrieved links.

```bash
python3 -m hermes_trailhead search all "Hermes Agent discussion" --format json
```

Output contract:

```json
{
  "query": "Hermes Agent discussion",
  "platform": "all",
  "mode": "hermes_trailhead_action_plan",
  "paid_api_required": false,
  "actions": [
    {
      "platform": "reddit",
      "status": "ready",
      "recommended_tool": "web_search or reddit-search",
      "site_query": "site:reddit.com Hermes Agent discussion",
      "direct_url": "https://redlib.perennialte.ch/search?q=Hermes+Agent+discussion",
      "approval_required": false,
      "paid_api_required": false,
      "evidence_needed": ["query/subreddits", "post count", "comment/thread links", "working Redlib or Reddit links"]
    }
  ]
}
```

The point: Hermes can read this JSON and know exactly what to call next, what requires approval, and what evidence must be collected before claiming success.

To execute immediately:

```bash
python3 -m hermes_trailhead search all "Prusa XL PLA curling edges" --execute --limit 3 --format json
```

Executed output wraps the plan plus per-platform executions:

```json
{
  "plan": {"mode": "hermes_trailhead_action_plan"},
  "executions": [
    {
      "platform": "reddit",
      "status": "ok",
      "executed_query": "site:reddit.com Prusa XL PLA curling edges",
      "engine": "jina_duckduckgo",
      "result_count": 3,
      "hits": [{"title": "...", "url": "...", "snippet": "..."}]
    }
  ]
}
```

Supported source families:

```bash
python3 -m hermes_trailhead search --help
```

```text
{all,web,x,reddit,tiktok,instagram,youtube,github}
```

## Example: broad social/current search

```bash
python3 -m hermes_trailhead route "search X, Reddit, TikTok, Instagram, YouTube and the web for current Hermes Agent discussion"
```

Output shape:

```text
# Hermes Trailhead route: social-current-signal

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

Hermes Trailhead is intentionally boring.

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
| `hermes_trailhead/channels.py` | Capability inventory and setup plans. |
| `hermes_trailhead/router.py` | Task-class routing rules. |
| `hermes_trailhead/cli.py` | Human and machine-readable commands. |

The main data model is plain Python dataclasses. Output is text, Markdown, or JSON.

## Safety model

Hermes Trailhead is read-only by default.

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

Hermes Trailhead prefers search paths that do not require personal logins when the task allows it:

1. Search with public or configured search surfaces.
2. Read pages with clean readers like `web_extract` or Jina Reader.
3. Use privacy frontends such as SearXNG, Nitter, Redlib, ProxiTok-like tools, or other public mirrors when appropriate.
4. Use browser automation only when the page truly needs session state or interaction.
5. Require approval before touching cookies, accounts, paid APIs, or posting surfaces.

## Prior art

Hermes Trailhead is not claiming to be first. It is a local reach-and-routing take on ideas from several strong projects.

### Agent capability and MCP ecosystems

- [Agent-Reach](https://github.com/Panniantong/Agent-Reach) inspired the initial pattern: channel registry, doctor checks, and setup plans.
- [Composio](https://composio.dev/) shows the value of a broad tool catalog, managed auth, and meta-tools.
- [Pipedream Connect / MCP](https://pipedream.com/docs/connect/mcp) shows managed API integration at large scale.
- [Arcade.dev](https://docs.arcade.dev/) shows a clean split between tool catalog, runtime, and authorization.
- [Zapier MCP](https://zapier.com/mcp) shows the value of low-friction SaaS action surfaces.
- The [official MCP Registry](https://modelcontextprotocol.io/registry/about), [Glama](https://glama.ai/mcp/servers), and [PulseMCP](https://www.pulsemcp.com/servers) show the discovery/catalog side of the ecosystem.

### Browser, crawl, and extraction engines

Hermes Trailhead does not replace these tools. It routes to them when they fit.

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

## What Hermes Trailhead is not

Hermes Trailhead is not:

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
python3 -m py_compile hermes_trailhead/*.py
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

Hermes Trailhead is open source under the BSD 3-Clause License. You may use, modify, and redistribute it, but you must preserve the copyright notice and license text.

See `NOTICE.md` for prior-art acknowledgments.
