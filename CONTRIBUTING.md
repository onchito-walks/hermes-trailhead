# Contributing

Hermes Trailhead is intentionally small. Contributions should make the router safer, clearer, or more useful for agents.

## Good contributions

- Add a new task route with clear approval boundaries.
- Add a channel check that returns structured evidence.
- Improve JSON contract tests.
- Add prior-art research that changes a route decision.
- Tighten security behavior so secrets/cookies/accounts stay protected.

## Bad contributions

- Automatic cookie extraction by default.
- Global installer scripts without a dry-run and approval gate.
- Posting or account mutation from diagnostic commands.
- Large crawlers hidden behind a simple channel check.
- Secret values in docs, tests, fixtures, or screenshots.

## Development

```bash
python3 -m py_compile hermes_trailhead/*.py
python3 -m pytest -q
python3 -m hermes_trailhead doctor --format json
python3 -m hermes_trailhead routes --format json
```

## Design rule

A route is only good if it says all four things:

1. what to use first
2. what to use as fallback
3. what to avoid
4. what evidence proves success
