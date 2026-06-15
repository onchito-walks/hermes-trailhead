# Weekly Operating Loop

SourceScout should be maintained like a small company, not a stale script.

Every week:

1. **Test the product**
   - Run Python compile checks.
   - Run the pytest suite.
   - Run CLI smoke tests for `doctor`, `queue`, `routes`, and `route`.

2. **Check for bugs**
   - Look for failing tests.
   - Look for broken routes.
   - Look for channels that print too much or too little evidence.
   - Look for any output that could expose secrets.

3. **Review the state of the art**
   - Agent harnesses: OpenClaw, Claude Code, Codex CLI, gstack.
   - MCP ecosystem: official registry, Glama, PulseMCP, MCPorter.
   - Integration platforms: Composio, Pipedream, Arcade, Zapier MCP.
   - Browser runtimes: Playwright MCP, Stagehand, browser-use, Browserbase.
   - Crawl/search/read tools: Firecrawl, Crawl4AI, Jina Reader, Exa, SearXNG, Whoogle.

4. **Decide what changed**
   - Did a better default route emerge?
   - Did a new tool create a safer fallback?
   - Did a tool become risky, paid, or login-heavy?
   - Does the README need new prior-art credit?

5. **Create concrete work**
   - Open issues or write a small roadmap entry.
   - Prefer small route/test/doc improvements over vague rewrites.

The weekly loop should be low-noise. If nothing actionable changed, report that and stop.
