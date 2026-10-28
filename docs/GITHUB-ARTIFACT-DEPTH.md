# GitHub issue / pull-request artifact depth

Native `read` of a GitHub issue or pull request used to route to
`_github_repo_metadata`, so `github.com/<owner>/<repo>/issues/<n>` returned
repository stats plus a README excerpt — `status: "ok"` for the wrong artifact.
The requested body, the discussion and the identifiers a caller needs to cite
were never fetched.

This change routes number-shaped issue/pull URLs to the existing public GitHub
REST helper (`_github_api_json`), not to a new connector or service framework.
The repository root keeps its existing behaviour (full README plus labelled
metadata), and every other GitHub path keeps its existing handler.

## Routing

| URL shape | Artifact returned |
|---|---|
| `github.com/o/r` | Full README + labelled repository metadata (unchanged) |
| `github.com/o/r/releases[...]` | Release notes (unchanged) |
| `github.com/o/r/blob/<ref>/<path>` | File content (unchanged) |
| `github.com/o/r/tree/<ref>/<path>` | Directory listing (unchanged) |
| `github.com/o/r/issues/<n>` | That issue's title/state/labels/body + bounded comments |
| `github.com/o/r/pull/<n>` (or `/pulls/<n>`) | That PR's title/state/branches/counts/body + bounded conversation, reviews and inline review comments |
| `github.com/o/r/issues` (no number) | Existing repository-metadata fallback |

A number-shaped issue/pull URL **never** falls back to repository metadata. If
the primary endpoint fails (404, rate limit, transport error, or an API error
object), `_fetch_github_summary` raises; `read` reports an extraction error
instead of presenting repository metadata as the requested artifact.

The response's own `number` is checked against the requested number. An endpoint
returning a different object is rejected as a failure, not rendered as evidence.

## Public endpoints used

All are the maintained GitHub REST v3 endpoints already reached by the shared
helper (`_github_request_headers()` — anonymous when no token is configured):

```text
GET /repos/{owner}/{repo}/issues/{n}
GET /repos/{owner}/{repo}/issues/{n}/comments        # issue comments, and PR conversation comments
GET /repos/{owner}/{repo}/pulls/{n}
GET /repos/{owner}/{repo}/pulls/{n}/reviews
GET /repos/{owner}/{repo}/pulls/{n}/comments         # inline review comments
```

No new module, connector, credential, or account flow is added. The reader
never prints a token, and the live probes below ran with `GITHUB_TOKEN`,
`GH_TOKEN` and `GH_ENTERPRISE_TOKEN` unset and `HOME` pointed at an empty
directory, so no `$HERMES_HOME/.env` token could be picked up.

## Capture disclosure

Every collection line states what was captured, the page budget, the per-item
cap, and whether more exists — including the next page URL:

```text
Conversation comments: captured 14 of 14 (1 page(s), per_page 100, body cap 4000 chars per item); complete for this endpoint.
Conversation comments: captured 6 of 9 (3 page(s), per_page 100, body cap 4000 chars per item); NOT complete — more exist beyond this capture; next page: https://api.github.com/repos/o/r/issues/5/comments?per_page=100&page=4
```

Counts come from the parent payload where GitHub exposes them (issue/PR
`comments`, PR `review_comments`). Reviews have no public total, so they are
reported as `captured N` with the page budget and next URL, never as a total.
The "of N" form is only emitted when N is at least the number captured.

Per-item bounds:

- issue/PR body: 20,000 chars, with an explicit
  `[body truncated at 20000 of N chars]` marker when applied;
- each comment/review/review comment: 4,000 chars, with the same measured
  marker;
- up to 3 pages of 100 items per collection;
- 400,000-char discussion-text budget. When that budget is reached, the
  remaining captured items are named: `[discussion text cap 400000 chars
  reached; K captured comment(s) not included]`.

That discussion-text budget stays below the unchanged 1,000,000-char `read`
retrieval cap, so native `read --offset/--max-chars` pagination still pages the
resulting text (20,000 default window, 200,000 max window) with contiguous,
no-gap windows. `search --execute --extract` still slices its preview at the
20,000-char readable limit.

## Pull requests are not the whole conversation

A PR has three separate public discussion collections. All three are captured
bounded and labelled, and the artifact ends with an explicit scope note:

```text
Capture note: this is the pull-request body plus bounded public conversation
comments, reviews and inline review comments. It is NOT the complete PR
conversation: timeline events, review-thread resolution, reactions, force-push
history, per-commit diffs and hidden/deleted comments are not captured.
```

A secondary endpoint failure (for example reviews returning 500) is disclosed in
place and does not discard the successfully fetched body:

```text
Conversation comments: not captured (RuntimeError: HTTP Error 500: Server Error);
the requested artifact above is unaffected by this secondary endpoint failure.
```

## Frozen live artifacts

Identities were recorded from the anonymous public API **before** any code
change, then the Trailhead `read` output was validated against them — title,
issue/PR id and every frozen comment id, not character counts:

- `pallets/flask#5` — "Implement SQLAlchemy", issue id 170451, comment ids
  308703 and 308779. Live `read`: `ok: true`, both ids present, no
  `GitHub repository:` text, `captured 2 of 2`.
- `pallets/flask#112` — "JSONP", pull id 541, 14 conversation comment ids
  (382640 … 4489650), 0 reviews, 0 inline review comments. Live `read`:
  `ok: true`, all 14 ids present, `captured 14 of 14`, reviews and inline review
  comment sections present, explicit "NOT the complete PR conversation".
- `pallets/flask/issues/999999999` — live `read`: exit `1`,
  `error.code: "extraction_error"`, no repository metadata.

Evidence: [evidence/github-artifact-depth.json](evidence/github-artifact-depth.json).
Frozen values are also pinned in `tests/test_github_artifact_depth.py`; if
upstream changes a title or deletes a comment, the live probe needs re-freezing
and that is a fixture update, not a contract relaxation.

## Regression tests

`tests/test_github_artifact_depth.py` (17 tests, no network) covers:

- issue and pull URLs return their own body/identifiers, never repository
  metadata or README text;
- a wrong returned issue number is rejected;
- a failed issue API raises and `extract_one` does not substitute repository
  metadata; an API error object is not rendered as evidence;
- pagination across more than one page, both complete and NOT complete with the
  next-page URL;
- per-comment body cap, artifact text cap, and PR body truncation disclosure;
- secondary collection failure disclosed without losing the main artifact;
- an `/issues/<n>` number that is really a PR is read as a PR;
- native `read` paginates the resulting GitHub artifact text with contiguous
  windows while `READ_RETRIEVAL_CHAR_CAP` remains 1,000,000 and the search
  preview stays at 20,000 chars.

```bash
python3 -m pytest -q tests/test_github_artifact_depth.py
python3 -m hermes_trailhead read https://github.com/pallets/flask/issues/5 --format json
```

## Not claimed

- A complete issue/PR conversation or history export: timeline events,
  reactions, edits, resolved-thread state, force-push history, diffs and
  hidden/deleted comments are outside the capture.
- Authenticated rate limits, private repositories, or any account flow.
- That the frozen upstream identifiers, titles or comment counts cannot change.
- That content length proves completeness; only the enumerated artifact markers
  and explicit capture disclosures do.
