# Notices

Hermes Trailhead is original code, built as a Hermes-native research trailhead for finding, reading, and verifying high-signal internet sources that are often difficult for agents to access reliably.

It was inspired by prior work in agent reach, MCP, browser automation, crawl/extract tooling, and local-agent harnesses. This file records those influences so downstream users can see what shaped the project.

## Direct inspiration

### Agent-Reach

- Repository: https://github.com/Panniantong/Agent-Reach
- License: MIT
- Copyright: Copyright (c) 2025 Agent Eyes
- Upstream commit inspected during creation: `71b85f8 docs(readme): clarify browser action boundary`
- Pinned version used in the public acceptance runs: `1.6.0` (`14c2134`)

**How Trailhead uses it.** Trailhead does **not** vendor Agent-Reach code and does
not re-license any of it. What it does is execute the upstream CLI as an optional
external dependency. Of the 40 reach actions Trailhead surfaces, **28 are Agent
Reach's own actions**, **4 are native actions that fall back to it**, and **8 are
fully native**. Delegated actions are invoked over `subprocess` with argument
arrays, no shell, in an isolated home for public calls. That code runs exactly as
its authors wrote it. The capability credit for those actions belongs to the Agent
Reach project and its contributors, not to Trailhead.

Trailhead originally adopted the doctrine and now delegates most of the surface.
Either way the debt is the same and it is recorded here: channel registry, probe
discipline, upstream-tool realism, and the insistence on teaching agents which
path to take.

Agent Reach is optional and is never installed, configured, or authenticated by
Trailhead automatically. Without it, the eight native actions and every
non-reach lane still work; `reach` reports a coded setup requirement instead of
pretending the action succeeded.

Because Agent Reach is MIT-licensed and its code is executed, its permission
notice is reproduced in full below and travels with this file:

```
MIT License

Copyright (c) 2025 Agent Eyes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The doctrine Trailhead reimplemented in its own code:

1. Maintain a registry of internet reach channels.
2. Provide doctor checks.
3. Provide setup plans.
4. Prefer mature upstream tools over bespoke scraping.
5. Keep agent-facing instructions durable.

Hermes Trailhead differs by making local coverage state, approval boundaries, and
evidence requirements first-class — and by refusing to report success when only
transport succeeded.

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
