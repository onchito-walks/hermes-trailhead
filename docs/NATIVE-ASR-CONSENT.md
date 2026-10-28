# Native extraction never spends transcription consent on its own

Status: **corrected and tested 2026-10-28** (task `t_c46f0f73`, parent verification
`t_4c26b5a6` at `9e109bd`). This closes the finding recorded in
[FINAL-VERIFICATION.md](FINAL-VERIFICATION.md); it does not close the whole
product goal.

## The gap that was found

Independent final verification could not establish "no automatic key/quota
spending ASR" because native extraction still had a fallback:

- `hermes_trailhead/extract.py` called `_fetch_youtube_asr` automatically after
  the caption tiers failed. `_ensure_asr_enabled()` only checked
  `TRAILHEAD_DISABLE_ASR`, so **unset meant enabled**; with a configured Groq key
  an ordinary `search --extract`/`read` of a captionless video could download
  audio and call Whisper with no per-invocation consent.
- The TikTok transcript tier had the same shape: captions first, then
  `_fetch_tiktok_transcript` (ASR) as an automatic second tier, with the same
  veto-only gate.

Both were reachable from ordinary research/extraction, not only from the
explicitly gated forwarding surface.

## Default behavior now

| Situation | Behavior |
|---|---|
| YouTube extraction, captions available | Captions returned as before. No key lookup, no download, no provider call. |
| YouTube extraction, captions fail | Page/stealth/direct tiers run. `audio_transcript_status="not_configured"` with `audio_transcript_error` explaining that ASR is opt-in. **No ASR helper call.** |
| TikTok extraction, captions available | Public caption VTT used as before. |
| TikTok extraction, captions fail | Metadata/comments retained; `audio_transcript_status="not_configured"` plus the opt-in note. **No ASR helper call.** |
| `TRAILHEAD_DISABLE_ASR=1` (any truthy spelling) | Absolute veto. It is checked *before* consent, so it wins even for a caller passing both consent keywords, including supplied environment overrides used by comparison/benchmark runs. |
| `_fetch_youtube_asr` / `_fetch_tiktok_transcript` called without both consent keywords | `RuntimeError("ASR is opt-in: …")` raised before URL parsing, cache read, key lookup, media download or provider request. Consent defaults to absent and is keyword-only, so it cannot be smuggled positionally. |
| Consented one-call path | The existing explicit surfaces remain: native helpers with `allow_authenticated=True, allow_quota_consuming=True`, and the forwarding actions `reach-call youtube transcribe` / `reach-call xiaoyuzhou transcribe --allow-authenticated --allow-quota-consuming`. Attribution and double gating unchanged. |

No new public flag, wrapper, or global "enable" switch was introduced: the fix is
the removal of the implicit fallback plus a default-deny gate on the two legacy
helpers, reusing the consent vocabulary that already existed in
`reach_backend.py`.

## Evidence

Hermetic (`tests/test_asr_consent.py`, plus the extraction-level cases in
`tests/test_extract.py` and `tests/test_tiktok_asr_tier.py`) — every external
boundary (`_get_groq_key`, transcript cache dir, `subprocess.run`,
`_download_small_media`, `_http_json`, `_transcribe_audio_groq`,
`urllib.request.urlopen`) is spied:

- configured key + caption failure through `extract_one` for YouTube and TikTok
  ⇒ `{"key": 0, "download": 0, "provider": 0, "helper": 0}`;
- helper calls with no / auth-only / quota-only consent ⇒ same zero counts;
- veto plus **full** consent ⇒ veto error, still zero counts;
- positional consent ⇒ `TypeError`.

Live public CLI smoke (no credential, no paid call; stub `GROQ_API_KEY` set to a
non-secret placeholder, `TRAILHEAD_DISABLE_ASR` unset, `yt-dlp` wrapped to log
argv): `hermes-trailhead read <youtube url>` produced exactly one `yt-dlp`
invocation — `--skip-download --write-auto-subs …` (captions) — with no
`bestaudio`/audio download, no `/tmp/yt-audio-*` file, and a truthful
`audio_transcript_status: not_configured` plus the opt-in note.

Full suite on the change: **1145 passed** (baseline was 1134; +11 consent
contract tests), `python3 -m py_compile hermes_trailhead/*.py` clean,
`git diff --check` clean.

## What this does not claim

- No live paid transcription was run; consent-path behavior is proven by
  fixtures, not by billing.
- `_transcribe_audio_groq` is a private uploader that takes an already-consented
  key and file. Consent is enforced by its only callers, both gated helpers; it
  must not be wired into an extraction path.
- Real multi-day reliability, authenticated action artifacts, and human-reviewed
  multilingual relevance remain open in
  [SUPERIORITY-ACCEPTANCE.md](SUPERIORITY-ACCEPTANCE.md).
