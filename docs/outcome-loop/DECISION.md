---
slug: projects/trailhead/outcome-loop-decision
tags: [trailhead, money-loop, outcome-loop, product, decision]
title: Outcome Loop Decision — Trailhead Product over Bounty Work
created: 2026-09-17
status: decided
decision: trailhead_product
---

# Outcome Loop Decision: Trailhead Product

## The decision

**Take the money loop to Trailhead-the-product, not open-source bounty hunting.**

Card `t_73ca9a77` ("Rebuild outcome loop: pick money loop") is resolved. This
doc is the durable record; it lives in `docs/outcome-loop/` in the
hermes-trailhead repo. Decision made under Ray's blanket authorization
("do all"), with no public outreach, spend, or signups required.

## Why not bounty work (evidence)

The independent `bounty-market-reality` research page (May 2026) and the
`revenue-audit-trail` (May 2026) give the body of evidence:

- Bounty programs are saturated with AI claimants; maintainers are
  overwhelmed. curl ended its bug bounty (valid reports fell below 5%);
  Turso shut its bounty; Ghostty left GitHub; Node HackerOne now needs
  Signal score 1.0+.
- AI PR merge rate is 32.7% vs 84.5% for humans (LinearB, 8.1M PRs); AI PRs
  are 2.5x larger and wait 5x longer for first review.
- Mcs: bots swarm issues (tscircuit #34 had 44 claimants; #29 had 54);
  UnsafeLabs is a known fake honeypot, yet bots still submit.
- **Live result: exactly $0 earned, 0 PRs merged** (revenue-audit-trail,
  2026-05-20).
- The scarce resource is trusted human maintainer attention — which an
  agent cannot buy or automate away.

Conclusion: bounty hunting is not a durable money loop.

Also observed: May's closed bounty loop (daily-bounty-scan cron) was the
forerunner; it produced a ranked digest but no merged revenue.

## Why Trailhead product (evidence)

Ray's own 2026-08-04 tabling comment on `t_73ca9a77`: "bounty hunting + CLU
Core are not revenue products. Trailhead is the leading candidate (already a
productized research tool, 7 source lanes, daily use)."

Verified on 2026-09-17, local, no network spend, no signups:

- `hermes-trailhead doctor`: fails=0, working source terrain.
- PhD gauntlet (deterministic product contract): **100/100 across 10 lanes**.
- Live `search all --execute --extract` across all 7 platform lanes returned
  real, scored, extracted hits (web, x, reddit, tiktok, instagram, youtube,
  github) — no paid API, free-first paths only.
- 155 tests passing; BSD-3-Clause; agent-facing product installed on the
  Hermes path.

Trailhead is a working, continuously-used product we own. It compounds
(report capability, lane coverage, scoring) where bounties did not.

## The money loop that replaces the closed bounty loop

```text
Trailhead product capability
  → produces a verifiable research deliverable (report, digest, ranked set)
  → that deliverable is the evidence of value and the seed of demand
  → iterate capability (product first), then package/monetize later
```

Constraints honored: local-first, no public posting, no outreach, no spend,
no signups. Each step yields a real artifact.

## First deliverable (generated this decision)

See `docs/outcome-loop/deliverable-sample-open-source-bounty-market.md` —
a real Trailhead-generated research report on the open-source bounty market,
produced with the local tool on 2026-09-17. It is the proof the product loop
emits artifacts end-to-end.

## Next execution units (kanban)

1. **D-1** — Ship the sample deliverable and a repeatable report command.
2. **D-2** — Pick the highest-signal target question, generate a second
   deliverable report via the repeatable command.
3. **D-3** — Package the report command as a documented CLI subcommand
   (trailhead `report`), no external dependency.

Each unit is produceable without outreach, spend, or signups.