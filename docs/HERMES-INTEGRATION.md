# Hermes Trailhead / Hermes Integration

Trailhead is the research lane in Hermes: one command fans out across hard-source terrain, extracts summaries/transcripts/metadata, scores source quality, and reports what it could not reach. Hermes should be able to call it without remembering repo paths.

## Install on a new machine (or a friend's Hermes)

Zero runtime dependencies — Python 3 stdlib only. Five minutes, end to end:

```bash
# 1. Get the code
git clone https://github.com/onchito-walks/hermes-trailhead.git
cd hermes-trailhead

# 2. Put the CLI on PATH
sudo bash scripts/install-hermes-trailhead-wrapper.sh
#    (no sudo? user-local: TRAILHEAD_BIN=~/.local/bin/hermes-trailhead bash scripts/install-hermes-trailhead-wrapper.sh)

# 3. See what THIS machine can reach (always the first command)
hermes-trailhead doctor

# 4. First real run — full fanout across all seven lanes
hermes-trailhead search all "your first research question" --execute --extract --score --limit 3 --format json

# 5. Optional — teach your Hermes agent how to drive it
mkdir -p ~/.hermes/skills/research/hermes-trailhead
cp integrations/hermes/skills/hermes-trailhead/SKILL.md ~/.hermes/skills/research/hermes-trailhead/
```

Updates are `git pull` in the repo. The authenticated tier (login-walled pages)
is opt-in via `TRAILHEAD_CAMOFOX_API` / `TRAILHEAD_CAMOFOX_USER` — see
[`AUTHENTICATED-TIER.md`](AUTHENTICATED-TIER.md) for the complete setup guide;
without it, the tool runs entirely on public routes.

**Platforms:** verified on Linux (the reference deployment). The core is pure
Python 3 stdlib and written to be portable — on macOS or Windows, run from
source (`python3 -m hermes_trailhead doctor`) and let `doctor` report what
that machine can reach. The wrapper script and service examples are POSIX
(bash / systemd).

## Commands

From an installed wrapper:

```bash
hermes-trailhead doctor
hermes-trailhead search all "query" --execute --extract --score --limit 3 --extract-limit 3 --format json
hermes-trailhead reliability
hermes-trailhead gauntlet
```

From source, equivalent:

```bash
cd /path/to/hermes-trailhead
python3 -m hermes_trailhead doctor
```

## Relationship to Quiver

Quiver is the capability-selection layer. Trailhead is a capability.

When the task is social/practitioner/hard-source research, `search-routing` should put Trailhead in the initial research fanout. Quiver keeps Trailhead discoverable by keeping the relevant skills and GBrain tool catalog wired without forcing all browser/social/search tools into every default Hermes turn.

## Sync rules

- Changes to Trailhead code/docs must be committed and pushed to GitHub.
- The `hermes-trailhead` executable should exist on PATH and point at the active repo unless the package is installed into a managed venv.
- `python3 -m hermes_trailhead doctor` is the local truth for lane availability.
- Live search proof is required after meaningful backend/search changes; tests alone are not enough.
- With scoring on, `hits[]` follows the ranked evidence order and `extracted[]` is sorted by score, so the JSON presents quality-ranked results end to end. They match when extraction covers every hit; still join by URL for safety (`--no-score` runs, or hits beyond `--extract-limit`). The active engine can differ between identical runs (e.g. `ddg_lite` vs `jina_duckduckgo`).
