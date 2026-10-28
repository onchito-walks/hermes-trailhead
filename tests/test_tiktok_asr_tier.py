"""Hermetic tests for the TikTok ASR transcript tier (Groq Whisper via TikWM play URL)."""
from __future__ import annotations

import pytest

import hermes_trailhead.extract as ex


def test_tiktok_transcript_happy_with_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_get_groq_key", lambda: "gsk_test")
    monkeypatch.setattr(ex, "hermes_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ex, "_http_json",
        lambda url, timeout: {"data": {"play": "https://cdn.example/v.mp4", "duration": 20}},
    )

    def fake_download(url, out_base, timeout=45):
        with open(out_base + ".mp4", "wb") as fh:
            fh.write(b"x")
        return out_base + ".mp4"

    monkeypatch.setattr(ex, "_download_small_media", fake_download)
    monkeypatch.setattr(ex, "_transcribe_audio_groq", lambda path, key, timeout=150: "SPOKEN WORDS " * 12)

    out = ex._fetch_tiktok_transcript(
        "https://www.tiktok.com/@u/video/7123456789012345678",
        allow_authenticated=True,
        allow_quota_consuming=True,
    )
    assert "TikTok ASR transcript" in out
    assert "SPOKEN WORDS" in out
    # second call must hit the cache (network helpers must not run)
    def boom(*a, **k):
        raise AssertionError("should hit cache")
    monkeypatch.setattr(ex, "_http_json", boom)
    assert ex._fetch_tiktok_transcript(
        "https://www.tiktok.com/@u/video/7123456789012345678",
        allow_authenticated=True,
        allow_quota_consuming=True,
    ) == out


def test_tiktok_transcript_empty_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_get_groq_key", lambda: "gsk_test")
    monkeypatch.setattr(ex, "hermes_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ex, "_http_json",
        lambda url, timeout: {"data": {"play": "https://cdn.example/v.mp4"}},
    )

    def fake_download(url, out_base, timeout=45):
        with open(out_base + ".mp4", "wb") as fh:
            fh.write(b"x")
        return out_base + ".mp4"

    monkeypatch.setattr(ex, "_download_small_media", fake_download)
    monkeypatch.setattr(ex, "_transcribe_audio_groq", lambda path, key, timeout=150: "  ")

    with pytest.raises(RuntimeError, match="too short"):
        ex._fetch_tiktok_transcript(
            "https://www.tiktok.com/@u/video/7999999999999999999",
            allow_authenticated=True,
            allow_quota_consuming=True,
        )


def test_tiktok_transcript_photo_post_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_get_groq_key", lambda: "gsk_test")
    monkeypatch.setattr(ex, "hermes_state_dir", lambda: tmp_path)
    monkeypatch.setattr(ex, "_http_json", lambda url, timeout: {"data": {"images": ["a.jpg"]}})

    with pytest.raises(RuntimeError, match="no downloadable video URL"):
        ex._fetch_tiktok_transcript(
            "https://www.tiktok.com/@u/video/7333333333333333333",
            allow_authenticated=True,
            allow_quota_consuming=True,
        )


def test_extract_one_tiktok_caption_failure_does_not_run_asr(monkeypatch):
    """A captionless TikTok keeps metadata and never spends the configured key."""
    calls = {"key": 0, "download": 0, "provider": 0, "helper": 0}

    monkeypatch.setenv("GROQ_API_KEY", "gsk_configured")
    monkeypatch.setattr(ex, "_fetch_tikwm", lambda url, timeout=25: "META CONTENT " * 40)
    monkeypatch.setattr(
        ex, "_fetch_tiktok_captions",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no caption track on this video")),
    )

    def forbidden_asr(*a, **k):
        calls["helper"] += 1
        raise AssertionError("automatic extraction must not invoke ASR")

    def configured_key():
        calls["key"] += 1
        return "gsk_configured"

    def forbidden_download(*a, **k):
        calls["download"] += 1
        raise AssertionError("automatic extraction must not download media")

    def forbidden_provider(*a, **k):
        calls["provider"] += 1
        raise AssertionError("automatic extraction must not contact the provider")

    monkeypatch.setattr(ex, "_fetch_tiktok_transcript", forbidden_asr)
    monkeypatch.setattr(ex, "_get_groq_key", configured_key)
    monkeypatch.setattr(ex, "_download_small_media", forbidden_download)
    monkeypatch.setattr(ex, "_transcribe_audio_groq", forbidden_provider)

    r = ex.extract_one("https://www.tiktok.com/@u/video/7123456789012345678")
    assert r.status == "ok"
    assert "META CONTENT" in r.content
    assert calls == {"key": 0, "download": 0, "provider": 0, "helper": 0}
    assert r.video_evidence is not None
    assert r.video_evidence.caption_transcript_status == "not_available"
    assert r.video_evidence.caption_transcript == ""
    assert "no caption track" in r.video_evidence.caption_transcript_error
    assert r.video_evidence.audio_transcript_status == "not_configured"
    assert "opt-in" in r.video_evidence.audio_transcript_error
    assert "reach-call" in r.video_evidence.audio_transcript_error
    assert "allow-quota-consuming" in r.video_evidence.audio_transcript_error


def test_extract_one_tiktok_survives_caption_failure(monkeypatch):
    monkeypatch.setattr(ex, "_fetch_tikwm", lambda url, timeout=25: "META CONTENT " * 40)
    monkeypatch.setattr(
        ex, "_fetch_tiktok_captions",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("music only")),
    )
    monkeypatch.setattr(
        ex, "_fetch_tiktok_transcript",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ASR must not auto-run")),
    )

    r = ex.extract_one("https://www.tiktok.com/@u/video/7123456789012345678")
    assert r.status == "ok"
    assert "META CONTENT" in r.content
    assert r.video_evidence is not None
    assert r.video_evidence.caption_transcript_status == "not_available"
    assert "music only" in r.video_evidence.caption_transcript_error


def test_vtt_to_text_strips_and_dedupes():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world\n00:00:01.000 --> 00:00:02.000\nHello world\n<00:00:02.000>Again <c>here</c>\n"
    out = ex._vtt_to_text(vtt)
    assert out == "Hello world\nAgain here"


def test_tiktok_captions_happy_with_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "hermes_state_dir", lambda: tmp_path)
    page = ('<script>{"video":{"claInfo":{"captionInfos":[{"language":"eng-US",'
            '"url":"https:\\u002F\\u002Fcdn.example\\u002Fcap.vtt"}]}}}</script>')
    vtt = (
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nSpoken caption line about the printer\n"
        "00:00:02.000 --> 00:00:04.000\nSpoken caption line about the printer\n"
        "00:00:04.000 --> 00:00:06.000\nAnd here are more spoken words from the video\n"
    )

    def fake_http(url, timeout=15, headers=None):
        return vtt if "cap.vtt" in url else page

    monkeypatch.setattr(ex, "_http_text", fake_http)
    out = ex._fetch_tiktok_captions("https://www.tiktok.com/@u/video/7665567402905685261")
    assert "TikTok captions" in out
    assert "Spoken caption line" in out
    assert "And here are more spoken words from the video" in out
    assert "00:00" not in out
    # cached on second call
    def boom(*a, **k):
        raise AssertionError("should hit cache")
    monkeypatch.setattr(ex, "_http_text", boom)
    assert ex._fetch_tiktok_captions("https://www.tiktok.com/@u/video/7665567402905685261") == out


def test_tiktok_captions_absent_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "hermes_state_dir", lambda: tmp_path)
    monkeypatch.setattr(ex, "_http_text", lambda url, timeout=15, headers=None: "<html>no captions here</html>")
    with pytest.raises(RuntimeError, match="no caption track"):
        ex._fetch_tiktok_captions("https://www.tiktok.com/@u/video/7111111111111111111")


def test_extract_one_prefers_captions_over_asr(monkeypatch):
    monkeypatch.setattr(ex, "_fetch_tikwm", lambda url, timeout=25: "META CONTENT " * 40)
    monkeypatch.setattr(ex, "_fetch_tiktok_captions", lambda url, timeout=60: "NATIVE CAPTION " * 40)

    def asr_forbidden(*a, **k):
        raise AssertionError("ASR must not run when captions exist")

    monkeypatch.setattr(ex, "_fetch_tiktok_transcript", asr_forbidden)
    r = ex.extract_one("https://www.tiktok.com/@u/video/7665567402905685261")
    assert r.status == "ok"
    assert "NATIVE CAPTION" in r.content
    assert r.video_evidence is not None
    assert r.video_evidence.caption_transcript_status == "ok"
    assert r.video_evidence.audio_transcript_status == "not_configured"
    assert r.video_evidence.audio_transcript_error == ""
