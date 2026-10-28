# Reader upstream-status fix — 2026-10-28

This corrects the failed missing-issue check in
[CLEAN-LINUX-FINAL.md](CLEAN-LINUX-FINAL.md). That historical container result
remains 10/11; it is not retroactively relabeled a pass.

Reader HTTP 200 is not necessarily target HTTP 200. A leading reader envelope
that reports target 404/410 is now rejected as a missing artifact; other
reported 4xx/5xx statuses are blocked. Status text in document titles or after
`Markdown Content:` is not transport metadata. Positive regression cases keep
articles quoting the diagnostic readable.

Parent verification after review and two additional boundary regressions:

- Full suite: **1071 passed in 50.63 seconds**.
- Python compilation and `git diff --check`: passed.
- Fresh empty HOME/HERMES_HOME, no account tokens, ASR disabled:
  - `read https://github.com/pallets/flask/issues/999999999`: exit 1,
    `ok:false`, `extraction_blocked`, zero content, `usable:false`.
  - Existing issue `https://github.com/pallets/flask/issues/1`: exit 0,
    `ok:true`, 1056 characters, `usable:true`.
- Exact recorded reader-envelope fixture and injected Jina-route tests reject
  the formerly successful 404 wrapper, independently of current network behavior.

This proves the bounded fix and its live controls. A clean-container rerun of
this newer source and the whole-product competitive goal remain separate work.
