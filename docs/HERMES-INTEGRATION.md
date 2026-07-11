# Hermes Trailhead / Hermes Integration

Trailhead is the research lane in Hermes: one command fans out across hard-source terrain, extracts summaries/transcripts/metadata, scores source quality, and reports what it could not reach. Hermes should be able to call it without remembering repo paths.

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
cd /home/ubuntu/src/hermes-trailhead
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
