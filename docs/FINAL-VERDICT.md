# Final verdict — Trailhead vs Agent Reach, 2026-10-28

**Bottom line: the engineering program is complete; the "better in every way"
claim is not established and is withdrawn.** Trailhead now reaches the same
40 actions across 14 channels, but 28 of them execute Agent Reach's own code
through Trailhead's adapter, 4 more use it as a fallback, and only 8 are native. A wrapper cannot beat the tool it wraps on that
tool's own capability — so "exceed in every way" was the wrong target, and
chasing it further would only add code without adding capability.

## What is now true, measured

| Fact | Evidence |
|---|---|
| 40 actions / 14 channels surfaced, no omissions or duplicates | `docs/EXACT-ACTION-INVENTORY.md`, asserted against the live registry |
| Coverage: 8 native, 4 native-with-upstream-fallback, 28 upstream (2 quota-gated) | `parity_inventory()` counts |
| Gates: 26 public / 12 auth / 2 quota | same |
| Test suite green, host-independent | 1145 passed in an ambient operator environment after `tests/conftest.py` isolated circuit + paid-key state |
| Clean Linux install, zero runtime dependencies | `docs/CLEAN-LINUX-RUN283.md` (11/11 on that revision) |
| Consented transcription produces real content | live: 233-char transcript, 17 s, one explicit per-call consent |
| Automatic extraction spends no key/quota | `docs/NATIVE-ASR-CONSENT.md`; default refusal with hermetic boundary spies |
| No automatic ASR even with consent when vetoed | `TRAILHEAD_DISABLE_ASR=1` wins |

## Where Trailhead is genuinely better

1. **Honesty.** A missing GitHub issue is a coded failure, not 6 KB of GitHub
   navigation chrome. Login walls, empty profiles, image assets and loading
   gates are rejected as evidence rather than counted as coverage. Agent Reach
   reports accurate errors too; Trailhead additionally refuses false *success*.
2. **Evidence judgment.** Transport success is separated from usable evidence;
   relevance is multilingual (CJK sub-string overlap, not exact token match);
   the thin-result fallback can only extend a result set, never shrink it.
3. **Safety.** Public calls run in throwaway homes with forced public backends
   and verified backend matching; quota-consuming transcription needs two
   explicit consents and never fires during ordinary research.
4. **One research question across every family.** A single sweep returns
   captions, transcripts, threads, repos and pages, then ranks and labels what
   it could not reach.

## Live lane reality (checked 2026-10-28 21:58 UTC)

"40/40 reachable" means every action is addressed by the interface, not that all of
them succeed. At 21:58 UTC `reliability` reports newsletter, web-extract, web-search,
x-search and youtube at 100% ok (52-53 checks each); **reddit at 54% declining**; and
**tiktok at 0% ok across 52 checks** (stagehand 0% is by design — not installed).
TikTok is the largest real gap behind the coverage number.

## Where Trailhead is not better, and why

- **Capability depth on 28 of 40 actions is borrowed outright, and 4 more fall back to the same code.** Post reads, thread
  replies, subreddit listings, Instagram/Facebook/Bilibili/Xiaohongshu/LinkedIn/
  Boss/Xueqiu/V2EX actions all run upstream. Equal at best, never ahead.
- **Content completeness is unproved.** Forwarded bodies are bounded at 250k
  characters; upstream offers no continuation cursor, so "full artifact" is
  claimed only where a document digest reconstructs exactly.
- **Speed is not established.** Matched samples split both ways (Trailhead
  faster on V2EX, Agent Reach faster on GitHub in one run; no distribution).
- **Reliability is one day of five.** Multi-day observations remain open by
  definition; the remaining dated runs are scheduled, not observed.
- **Unverified lanes:** authenticated account lifecycle, live paid transcript
  content and billing bounds, clean macOS/Windows, human-adjudicated
  multilingual relevance.

## The structural conclusion

Reuse was the correct engineering call — it is how 40 actions exist at all
without writing 32 scrapers. But it fixes the ceiling: any dimension where
Trailhead forwards Agent Reach inherits Agent Reach's behaviour exactly. Real
superiority would require native implementations of those lanes, which
contradicts the reuse mandate and would be a multi-month effort per platform
against platforms that actively fight automation.

The defensible position is the one now implemented: **match the surface by
reuse, beat it on evidence quality and safety, and say plainly which parts are
yours.** That is what the code does today.

## Outstanding, with what each needs

| Gap | Needs |
|---|---|
| Days 2–5 reliability | real calendar time; scheduled 16:00/16:35 UTC Oct 29–Nov 1 |
| Authenticated artifacts, account lifecycle | a named disposable account and explicit login/switch/logout/targets |
| Paid transcript content and billing bounds | a per-target spend budget |
| Clean macOS / Windows | disposable machines |
| Human-reviewed multilingual relevance | a human adjudicator |
