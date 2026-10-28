"""Hermetic consent contract for the legacy media-ASR helpers.

Ordinary extraction/research must never download media, read a configured
transcription key, touch the transcript cache, or call a provider.  The private
``_fetch_youtube_asr`` / ``_fetch_tiktok_transcript`` helpers are retained for
explicit one-call opt-in only: both consent keywords are required and the
``TRAILHEAD_DISABLE_ASR`` veto is checked first.

Every external boundary is spied here; no network, key, or paid call is made.
"""
from __future__ import annotations

import pytest

import hermes_trailhead.extract as ex

YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123XYZ"
TIKTOK_URL = "https://www.tiktok.com/@user/video/7123456789012345678"

HELPERS = (
    ("youtube", ex._fetch_youtube_asr, YOUTUBE_URL),
    ("tiktok", ex._fetch_tiktok_transcript, TIKTOK_URL),
)

_FULL_CONSENT = {"allow_authenticated": True, "allow_quota_consuming": True}


def _wire_effect_spies(monkeypatch, tmp_path):
    """Count every effect the gate must prevent; none may fire without consent."""
    calls = {"key": 0, "cache": 0, "download": 0, "provider": 0}

    def key_lookup():
        calls["key"] += 1
        return "gsk_configured"

    def cache_dir():
        calls["cache"] += 1
        return tmp_path

    def download(*a, **k):
        calls["download"] += 1
        raise AssertionError("media download attempted without consent")

    def provider(*a, **k):
        calls["provider"] += 1
        raise AssertionError("transcription provider attempted without consent")

    def proxy_plan():
        calls["download"] += 1
        return [None]

    monkeypatch.setattr(ex, "_get_groq_key", key_lookup)
    monkeypatch.setattr(ex, "hermes_state_dir", cache_dir)
    monkeypatch.setattr(ex, "_proxy_failover_plan", proxy_plan)
    monkeypatch.setattr(ex.subprocess, "run", download)
    monkeypatch.setattr(ex, "_download_small_media", download)
    monkeypatch.setattr(ex, "_http_json", provider)
    monkeypatch.setattr(ex, "_transcribe_audio_groq", provider)
    monkeypatch.setattr(ex.urllib.request, "urlopen", provider)
    return calls


@pytest.mark.parametrize("platform,helper,url", HELPERS)
@pytest.mark.parametrize(
    "consent",
    (
        {},
        {"allow_authenticated": True},
        {"allow_quota_consuming": True},
    ),
    ids=("no-consent", "auth-only", "quota-only"),
)
def test_helper_refuses_without_both_consent_keywords_before_any_effect(
    monkeypatch, tmp_path, platform, helper, url, consent
):
    monkeypatch.delenv(ex.ASR_DISABLE_ENV, raising=False)
    calls = _wire_effect_spies(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="ASR is opt-in"):
        helper(url, **consent)

    assert calls == {"key": 0, "cache": 0, "download": 0, "provider": 0}, platform


@pytest.mark.parametrize("platform,helper,url", HELPERS)
def test_veto_wins_over_full_consent_before_any_effect(monkeypatch, tmp_path, platform, helper, url):
    monkeypatch.setenv(ex.ASR_DISABLE_ENV, "1")
    calls = _wire_effect_spies(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="ASR disabled for this run"):
        helper(url, **_FULL_CONSENT)

    assert calls == {"key": 0, "cache": 0, "download": 0, "provider": 0}, platform


@pytest.mark.parametrize("platform,helper,url", HELPERS)
def test_consent_is_keyword_only(monkeypatch, platform, helper, url):
    """Consent cannot be smuggled positionally by an automatic caller."""
    monkeypatch.delenv(ex.ASR_DISABLE_ENV, raising=False)
    with pytest.raises(TypeError):
        helper(url, 30, True, True)  # type: ignore[misc]
