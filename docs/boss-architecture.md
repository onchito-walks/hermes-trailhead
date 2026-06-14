# Hermes Reach Boss-Version Architecture

Hermes Reach is not meant to be a clone of Agent-Reach. Agent-Reach is a useful generic scaffold: it installs/probes external tools so agents can read more of the internet. Hermes Reach should become something sharper: a **Hermes-native reach map** that tells the agent which hard-to-access sources are reachable, which path to use, what is not configured, what requires approval, and what changed upstream.

## Upstream Agent-Reach weaknesses to exploit

### 1. CLI-first, not agent-native

Agent-Reach mostly orchestrates shell tools and MCP servers. That is useful, but it leaves the model to infer policy from prose. Hermes Reach should expose structured, typed output: statuses, evidence, approval requirements, risks, fallbacks, and next actions. The model should not parse decorative text to decide whether it may touch cookies.

### 2. Safety is advisory instead of enforced

Agent-Reach documents privacy/safety, but it still revolves around installing packages, configuring browser-session tools, and handling cookies. Hermes Reach should default to read-only diagnostics and setup plans. Any path involving cookies, credentials, paid services, posting, or global installs must be marked `approval_required` in machine-readable output.

### 3. Diagnostics lack durable history

A doctor command is useful, but a one-shot doctor forgets. Hermes is strongest when state becomes memory. Hermes Reach should eventually write run snapshots into GBrain or a local state file so the system can see recurring failures, channels that flap, and upstream changes that repeatedly matter.

### 4. Static channel model

Agent-Reach’s channel/back-end model is source-code-driven. Hermes Reach should move toward declarative manifests: channel metadata, probes, fallback order, approval gates, and setup plans should be data. Code should provide probe primitives and policy enforcement.

### 5. Weak install-vs-capability loop

Generic internet access is not enough. Hermes needs to know: “What can my current Hermes install already do, what did upstream add, and what should I adopt?” That is the differentiator. Hermes Reach should integrate with the docs watcher and daily briefing Capability Radar.

## Hermes-native product principles

1. **Hermes tools first.** Prefer built-in Hermes tools and MCP surfaces before installing external CLIs.
2. **Evidence over confidence theater.** Every status reports concrete evidence: file, command, env var, return code, or policy source.
3. **Approval boundaries are data.** Risk is not a paragraph. It is a field agents can consume.
4. **No silent mutation.** Doctor and queue are read-only. Plan explains. Apply, if added later, must be gated.
5. **Operator loop, not one-shot setup.** Feed capability drift into cron/newsletter/GBrain.
6. **Extensible but narrow.** Add channels as manifests/plugins, not hand-built bespoke scrapers.

## Current boss-version slice implemented

- Structured `CheckResult` with evidence, confidence, category, and approval fields.
- Structured `Channel` metadata with risk, tags, required flag, Hermes-native flag, and setup plan.
- `doctor --format json|markdown|text`.
- Filters: `--only`, `--risk`, `--channel`, `--tag`.
- `queue --top`, `queue --all`, machine-readable queue output.
- `agent-brief` command for Hermes agents to choose the right internet path.
- Robust cron parsing for docs watcher instead of substring-only matching.
- Default remote branch detection for Hermes upstream comparison.

## Next major feature bets

### Phase 1 — Manifest registry

Move channel definitions to declarative YAML/JSON manifests:

```yaml
key: x-search
title: X/Twitter
risk: high
approval_required: true
preferred_path: x_search
fallbacks: [nitter, web_extract]
probes:
  - type: env
    key: XAI_API_KEY
  - type: http
    url: http://localhost:8788
setup_plan:
  - Use x_search if credentialed.
  - Fallback to Nitter extraction.
  - Ask before cookies/posting.
```

### Phase 2 — State/history

Add:

```bash
hermes-reach snapshot --output state/reach.json
hermes-reach history
hermes-reach diff --since yesterday
```

Then wire into GBrain or the morning newsletter.

### Phase 3 — Remediation planner

Add safe, explicit remediation plans:

```bash
hermes-reach apply x-search --dry-run
hermes-reach apply youtube --project-venv /path/to/project
```

No `--yes` for high-risk channels unless the user explicitly approved the action in the active turn.

### Phase 4 — Hermes MCP/service surface

Expose Hermes Reach as an MCP server or native Hermes toolset so the agent can ask:

- “best channel for X?”
- “what requires approval?”
- “what broke since last week?”
- “which external tool should I install, if any?”

## Competitive position

Agent-Reach gives agents more internet tools. Hermes Reach should give Hermes a verified **reach map**: what sources are reachable, what path works, what is missing, and what evidence proves the result.
