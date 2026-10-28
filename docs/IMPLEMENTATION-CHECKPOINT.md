# Public implementation checkpoint — 2026-10-28

**Whole-product goal remains open. This checkpoint is ready for review, not a superiority claim.**

## Integrated and independently exercised

- `b20d4e3`: declared bool/float coercion, bounded shared registry cache, and discovery/action shared deadline. Five fallback lanes use one registry subprocess rather than five in the recorded stub measurement. Cache entries remain stale until refresh/clear/restart; no security sandbox is implied.
- `d6f5029`: actual Jina/DDG snippet recovery; explicit CLI `--prefer-language` and repeatable `--prefer-source` stable ordering (not language inference or filtering); native `read --offset/--max-chars` with separate transport/retrieval/window bounds and full available-document SHA256.
- GitHub issue and PR URLs now yield the requested body and bounded paginated discussion collections instead of repository metadata. Missing collections and body/item/page caps are disclosed; PR history completeness is explicitly NOT claimed.
- Parent final full suite: **945 passed in 52.02s**, compilation and `git diff --check` clean. Earlier deterministic gauntlet: 100/100; this is not live availability.

## Parent live evidence

- [Nine-call public verification](evidence/parent-public-followup.json): five reads reconstruct 78,047 extracted characters from Chinese typing docs, four contiguous windows equal the single full extraction, same document digest. Suffix windows correctly do not claim full-document completeness. Three searches return nine real snippets; explicit Chinese/Spanish preferences move the matching official URL first. One seven-lane search returns hits in every lane: hits are not proof of usable artifacts.
- [Matched cold two-case smoke](evidence/parent-followup-compare.json): GitHub README and V2EX node both return evidence on both tools under equal 20-second per-side deadlines, no credential environment forwarded. Agent Reach was faster in these two observations. No aggregate ranking or performance conclusion.
- [Independent GitHub issue/PR reads](evidence/parent-github-artifact-verification.json): anonymous fresh-home CLI reads of `pallets/flask#5` and PR `#112` check exact title/comment markers and 2/2 and 14/14 conversation comments. PR omitted-history disclosure present. Environment isolation is not an OS sandbox.

## What review must not waive

Public work remains: broader all-artifact depth verification for the action sweep, long/high-comment fixtures and real endpoints, cross-tool per-process resource measurements, multi-day freshness/reliability, further multilingual queries and human relevance adjudication, clean-machine onboarding, and measured maintenance complexity reduction where justified. See [public acceptance procedures](PUBLIC-REMAINING-ACCEPTANCE.md); these procedures are not executed results. The GitHub lane described there as pending is now integrated for this checkpoint only, not exhaustive GitHub parity.

Restricted work separately needs specific account/test-target and user-controlled lifecycle consent, explicit transcription/podcast quota budget, and disposable clean macOS/Windows environments. Those restrictions do not block the remaining independent public work. Do not import existing credentials or silently invoke billable APIs.

No push/publication, account change, paid call, or modification of the pre-existing untracked `o.txt` was performed. Requesting review of this checkpoint does not mark the whole task complete.
