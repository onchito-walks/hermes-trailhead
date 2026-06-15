# Notices

Hermes Trailhead is original code, built as a local agent-native reach map for searching, reading, and verifying internet sources that are often difficult for agents to access reliably.

It was inspired by prior work in agent reach, MCP, browser automation, crawl/extract tooling, and local-agent harnesses. This file records those influences so downstream users can see what shaped the project.

## Direct inspiration

### Agent-Reach

- Repository: https://github.com/Panniantong/Agent-Reach
- License: MIT
- Copyright notice in upstream license: Copyright (c) 2025 Agent Eyes
- Upstream commit inspected during creation: `71b85f8 docs(readme): clarify browser action boundary`

Hermes Trailhead does **not** vendor Agent-Reach code. It reimplements the useful pattern for Hermes:

1. Maintain a registry of internet reach channels.
2. Provide doctor checks.
3. Provide setup plans.
4. Prefer mature upstream tools over bespoke scraping.
5. Keep agent-facing instructions durable.

Hermes Trailhead differs by making local coverage state, approval boundaries, and evidence requirements first-class.

## Adjacent agent capability systems

Hermes Trailhead is informed by, but does not vendor code from:

- Composio — broad integration catalog and managed auth: https://composio.dev/
- Pipedream Connect / MCP — managed API integration via MCP: https://pipedream.com/docs/connect/mcp
- Arcade.dev — tool catalog, runtime, and authorization patterns: https://docs.arcade.dev/
- Zapier MCP — large SaaS action surface: https://zapier.com/mcp
- Official MCP Registry — ecosystem metadata and publishing: https://modelcontextprotocol.io/registry/about
- Glama MCP directory — MCP discovery/gateway patterns: https://glama.ai/mcp/servers
- PulseMCP — MCP discovery and ecosystem tracking: https://www.pulsemcp.com/servers

## Browser, crawl, search, and extraction prior art

Hermes Trailhead routes to specialized engines instead of replacing them:

- Firecrawl: https://docs.firecrawl.dev/
- Crawl4AI: https://docs.crawl4ai.com/
- Browserbase: https://docs.browserbase.com/
- Stagehand: https://docs.stagehand.dev/
- browser-use: https://github.com/browser-use/browser-use
- Playwright MCP: https://github.com/microsoft/playwright-mcp
- Jina Reader: https://jina.ai/reader/
- Exa: https://exa.ai/docs/reference/search
- SearXNG: https://searxng.org/
- Whoogle: https://github.com/benbusby/whoogle-search
- LibreX: https://github.com/hnhx/librex

## Harness prior art

Hermes Trailhead also borrows ideas from harness-first agent systems:

- OpenClaw: https://github.com/openclaw/openclaw
- MCPorter: https://github.com/openclaw/mcporter
- Claude Code skills, subagents, hooks, and MCP: https://docs.anthropic.com/en/docs/claude-code/overview
- OpenAI Codex CLI: https://github.com/openai/codex
- gstack: https://github.com/garrytan/gstack

## Attribution requirement

Hermes Trailhead is licensed under BSD 3-Clause. Redistribution must preserve the copyright notice, license text, and this notice file when distributed with the source tree.
