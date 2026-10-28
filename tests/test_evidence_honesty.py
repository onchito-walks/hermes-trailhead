"""Regression tests for evidence honesty and query relevance.

These encode two defects reproduced on a live ``Agent Reach`` sweep:

1. ``visual_analysis_status`` was reported as ``"available"`` although no video
   frame was ever inspected — caption/page text had been relabelled as visual
   analysis.
2. An unrelated empty Instagram profile (``@agent.reach``, 0 posts, 1 follower)
   was reported as successful extraction and ranked as evidence, and a transcript
   could be reported ``"ok"`` from an empty payload.

The fixes separate *extraction transport success* from *evidence usability*:
an ``"ok"`` extraction can still be unusable evidence, and only text that matches
the query (token-level, not exact-string) is usable.
"""
from __future__ import annotations

import hermes_trailhead.extract as ex
from hermes_trailhead.extract import (
    ExtractedHit,
    ExtractionResult,
    VideoEvidence,
    extract_one,
)
from hermes_trailhead.scoring import (
    ScoredHit,
    SourceQuality,
    SourceScore,
    assess_evidence,
    assess_relevance,
    is_empty_social_profile,
    rank_hits,
    score_hit,
)
from hermes_trailhead.search import SearchHit, execute_search

QUERY = "Agent Reach"

IG_PROFILE_TEXT = (
    "Instagram\n\n"
    "1 Followers, 0 Following, 0 Posts - See Instagram photos and videos from "
    "AGENT REACH (@agent.reach)\n\n"
    "agent.reach\nAGENT REACH\n0 posts\n1 follower\n0 following\nFollow\n"
    "No posts yet\nSuggested for you\nSee all\n"
    "3dstlviewer\n3D STL Viewer: Cost Calculator\nFollow\n"
    "jlo\nJennifer Lopez\nFollow\n"
    "Meta\nAbout\nBlog\nJobs\nHelp\nAPI\nPrivacy\n"
    "© 2026 Instagram from Meta\nMessages"
)


def _hit(query: str = QUERY, **kwargs) -> ScoredHit:
    base = dict(
        title="AGENT REACH (@agent.reach) • Instagram photos and videos",
        url="https://www.instagram.com/agent.reach/",
        snippet="",
        extraction_status="ok",
        extraction_length=len(IG_PROFILE_TEXT),
        summary=IG_PROFILE_TEXT,
        query=query,
    )
    base.update(kwargs)
    return ScoredHit(**base)


# ── 1. Visual analysis requires inspected frames ────────────────────────


def test_visual_analysis_not_available_without_inspected_frames():
    ve = VideoEvidence(
        visual_analysis_status="available",
        visual_analysis_summary="TikTok caption text is not a visual summary",
    )
    assert ve.visual_analysis_status == "not_attempted"
    assert ve.visual_analysis_summary == ""
    assert ve.to_dict()["visual_analysis_status"] == "not_attempted"
    assert ve.to_dict()["visual_analysis_summary"] == ""


def test_visual_analysis_available_only_with_frames_and_summary():
    ve = VideoEvidence(
        visual_analysis_status="available",
        visual_analysis_summary="Frame 3 shows the CLI banner over a terminal.",
        visual_analysis_frames=3,
    )
    assert ve.visual_analysis_status == "available"
    assert ve.visual_analysis_summary.startswith("Frame 3")
    assert ve.to_dict()["visual_analysis_frames"] == 3


def test_available_without_summary_downgrades():
    ve = VideoEvidence(visual_analysis_status="available", visual_analysis_frames=5)
    assert ve.visual_analysis_status == "not_attempted"


def test_tiktok_caption_extraction_does_not_claim_visual_analysis(monkeypatch):
    import json as _json

    oembed = _json.dumps({
        "title": "Cool video with enough caption text to count as a useful TikTok summary.",
        "author_name": "user",
    })
    monkeypatch.setattr(
        ex.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no subprocess")),
    )

    result = extract_one("https://www.tiktok.com/@user/video/123", fetch=lambda u, timeout=0: oembed)
    assert result.status == "ok"
    ve = result.video_evidence
    assert ve is not None
    assert ve.caption_status == "ok"
    assert ve.visual_analysis_status == "not_attempted"
    assert ve.visual_analysis_summary == ""


def test_instagram_profile_extraction_is_transport_ok_not_visual(monkeypatch):
    def dead(*a, **k):
        raise RuntimeError("tier unavailable")

    monkeypatch.setattr(ex, "_fetch_instagram_api", dead)
    monkeypatch.setattr(ex, "_camofox_session_fetch", dead)
    monkeypatch.setattr(ex, "_fetch_browser_harness", dead)
    monkeypatch.setattr(ex, "_fetch_stealth_chrome", lambda url, timeout=30, cookies=None: IG_PROFILE_TEXT)

    result = extract_one("https://www.instagram.com/agent.reach/", fetch=lambda u, timeout=0: "")

    assert result.status == "ok"  # transport succeeded: page text came back
    ve = result.video_evidence
    assert ve is not None
    assert ve.visual_analysis_status == "not_attempted"
    assert ve.visual_analysis_summary == ""
    assert ve.caption_transcript_status == "not_available"


# ── 2. Empty payloads are not successful transcripts ────────────────────


def test_video_evidence_empty_transcript_cannot_be_ok():
    ve = VideoEvidence(caption_transcript_status="ok", caption_transcript="")
    assert ve.caption_transcript_status == "not_available"

    audio = VideoEvidence(audio_transcript_status="ok", audio_transcript="")
    assert audio.audio_transcript_status == "not_configured"


def test_tiktok_empty_transcript_payload_is_not_reported_ok(monkeypatch):
    monkeypatch.setattr(ex, "_fetch_tikwm", lambda url, timeout=25: "META CONTENT " * 40)
    monkeypatch.setattr(ex, "_fetch_tiktok_captions", lambda *a, **k: "")
    monkeypatch.setattr(ex, "_fetch_tiktok_transcript", lambda *a, **k: "")

    result = extract_one("https://www.tiktok.com/@u/video/7123456789012345678")
    assert result.status == "ok"
    ve = result.video_evidence
    assert ve is not None
    assert ve.caption_transcript_status == "not_available"
    assert ve.caption_transcript == ""
    assert "empty transcript payload" in ve.caption_transcript_error

    scored = score_hit(ScoredHit.from_extracted_hit(ExtractedHit(
        title="TikTok demo", url="https://www.tiktok.com/@u/video/7123456789012345678",
        snippet="", extraction=result,
    ))).to_dict()
    assert scored["transcript_status"] != "ok"


def test_youtube_captions_do_not_claim_audio_transcript(monkeypatch):
    monkeypatch.setattr(
        ex, "_fetch_ytdlp_transcript",
        lambda url, timeout: "YouTube auto-captions for abc123\n\nreal spoken words " * 5,
    )

    result = extract_one("https://www.youtube.com/watch?v=abc123")
    assert result.status == "ok"
    ve = result.video_evidence
    assert ve.caption_transcript_status == "ok"
    assert ve.audio_transcript_status == "not_configured"
    assert ve.visual_analysis_status == "not_attempted"

    scored = score_hit(ScoredHit.from_extracted_hit(ExtractedHit(
        title="Video", url="https://www.youtube.com/watch?v=abc123", snippet="",
        extraction=result, query="abc",
    ))).to_dict()
    assert scored["transcript_status"] == "ok"


# ── 3. Empty profiles: transport ok, evidence not usable ────────────────


def test_empty_profile_detection_is_conservative():
    assert is_empty_social_profile("https://www.instagram.com/agent.reach/", IG_PROFILE_TEXT) is True
    # Post/reel URLs are not profiles, even if the text mentions counts.
    assert is_empty_social_profile("https://www.instagram.com/reel/DbV8LwXPDxt/", IG_PROFILE_TEXT) is False
    # A live profile page is not flagged by one incidental count.
    assert is_empty_social_profile(
        "https://www.instagram.com/somecreator/",
        "12.4K followers · 500 following · 320 posts",
    ) is False


def test_empty_instagram_profile_is_not_usable_evidence():
    d = score_hit(_hit()).to_dict()

    assert d["extraction_status"] == "ok"       # transport succeeded
    assert d["transport_ok"] is True
    assert d["evidence_usable"] is False        # ...but there is no evidence
    assert d["evidence_relevance"] == "relevant"  # handle matches the query
    assert d["scoring"]["quality"] == "platform_shell"
    assert d["scoring"]["score"] == 0
    assert "empty social profile" in " ".join(d["evidence_reasons"]).lower()


def test_empty_profile_extraction_result_flows_through_from_extracted_hit():
    eh = ExtractedHit(
        title="AGENT REACH (@agent.reach) • Instagram photos and videos",
        url="https://www.instagram.com/agent.reach/",
        snippet="",
        extraction=ExtractionResult(
            status="ok", content=IG_PROFILE_TEXT,
            content_length=len(IG_PROFILE_TEXT), source_type="instagram",
        ),
        query=QUERY,
    )
    scored = score_hit(ScoredHit.from_extracted_hit(eh))
    assert scored.assessment.usable is False
    assert scored.assessment.transport_ok is True
    assert scored.scoring.quality == SourceQuality.PLATFORM_SHELL


# ── 4. Query relevance: conservative, token-level, not exact-string ─────


def test_relevance_is_token_level_not_exact_string():
    types, reasons = assess_relevance("Agent-Reach ships one CLI for agents.", QUERY)
    assert types == "relevant"
    assert reasons


def test_partial_query_match_remains_usable():
    relevance, _ = assess_relevance("An agent framework with tools.", QUERY)
    assert relevance == "partial"

    hit = _hit(
        title="Agent framework notes",
        url="https://example.com/agent-notes",
        summary="An agent framework with tools and memory.",
        extraction_length=48,
    )
    assessment = assess_evidence(hit)
    assert assessment.relevance == "partial"
    assert assessment.usable is True


def test_short_on_query_content_is_usable():
    hit = _hit(
        title="Agent Reach",
        url="https://example.com/agent-reach",
        summary="Agent Reach installs with one CLI and needs no API keys.",
        extraction_length=58,
    )
    assessment = assess_evidence(hit)
    assert assessment.usable is True
    assert assessment.relevance == "relevant"

    d = score_hit(hit).to_dict()
    assert d["description_available"] is True
    assert d["scoring"]["score"] > 0


def test_off_query_hit_is_not_usable_even_when_canonical():
    hit = ScoredHit(
        title="StealthChanger toolchanger assembly notes",
        url="https://github.com/example/stealthchanger/issues/7",
        snippet="",
        summary="StealthChanger carriage bolts and belt paths for the VORON build.",
        extraction_status="ok",
        extraction_length=900,
        query=QUERY,
    )
    d = score_hit(hit).to_dict()
    assert d["evidence_usable"] is False
    assert d["evidence_relevance"] == "unrelated"
    assert d["scoring"]["score"] <= 10
    # Domain signal is preserved; only usability/score are capped.
    assert d["scoring"]["quality"] == "technical"
    assert any("off-query" in r.lower() for r in d["evidence_reasons"])


def test_no_query_keeps_legacy_scores_unchanged():
    hit = ScoredHit(
        title="StealthChanger toolchanger assembly notes",
        url="https://github.com/example/stealthchanger/issues/7",
        snippet="",
        summary="StealthChanger carriage bolts and belt paths for the VORON build.",
        extraction_status="ok",
        extraction_length=900,
    )
    d = score_hit(hit).to_dict()
    assert d["evidence_relevance"] == "unknown"
    assert d["scoring"]["score"] > 10


def test_score_hit_accepts_explicit_query():
    hit = ScoredHit(
        title="StealthChanger build guide",
        url="https://github.com/example/stealthchanger/issues/7",
        snippet="",
        extraction_status="ok",
        extraction_length=900,
    )
    assert score_hit(hit).assessment.relevance == "unknown"
    assert score_hit(hit, query=QUERY).assessment.relevance == "unrelated"


def test_rank_hits_prefers_usable_evidence_over_flattering_urls():
    usable = score_hit(ScoredHit(
        title="Agent Reach repository",
        url="https://github.com/Panniantong/Agent-Reach",
        snippet="",
        summary="Agent Reach gives an agent eyes across the internet.",
        extraction_status="ok",
        extraction_length=700,
        query=QUERY,
    ))
    discovery_lead = score_hit(
        ScoredHit(
            title="Canonical docs",
            url="https://docs.example.com/guide",
            snippet="",
            summary="Unrelated documentation index.",
            extraction_status="not_attempted",
            extraction_length=0,
            query=QUERY,
            scoring=SourceScore(SourceQuality.CANONICAL, 75, ("Documentation site",), "Documentation site"),
        ),
    )
    ranked = rank_hits([discovery_lead, usable])
    assert ranked[0].url == "https://github.com/Panniantong/Agent-Reach"
    assert ranked[0].assessment.usable is True
    assert ranked[1].assessment.usable is False


# ── 5. Query propagation and backwards-compatible output ────────────────


def test_search_hits_carry_query_and_keep_public_dict_shape():
    markdown = (
        "## [Agent-Reach repo](https://github.com/Panniantong/Agent-Reach)\n"
        "Give your agent eyes across the internet.\n"
    )
    executed = execute_search("web", QUERY, limit=1, fetch=lambda url, timeout: markdown)
    hit = executed.executions[0].hits[0]

    assert hit.query == QUERY
    assert set(hit.to_dict()) == {"title", "url", "snippet"}

    extracted = ExtractedHit.from_search_hit(hit)
    assert extracted.query == QUERY
    assert extracted.to_dict().get("query") is None  # public dict unchanged


def test_extract_hits_propagates_query(monkeypatch):
    hits = (SearchHit(title="Agent Reach", url="https://example.com/ar", snippet="", query=QUERY),)

    def fake_fetch(url, timeout):
        return "Agent Reach installs with one CLI and reads public links. " * 3

    extracted = ex.extract_hits(hits, limit=1, fetch=fake_fetch)
    assert extracted[0].query == QUERY
    scored = ScoredHit.from_extracted_hit(extracted[0])
    assert scored.query == QUERY
    assert scored.assessment.relevance == "relevant"
    assert scored.assessment.usable is True


def test_scored_hit_dict_keeps_legacy_keys():
    d = _hit().to_dict()
    legacy = {
        "title", "url", "snippet", "summary", "extraction_status",
        "extraction_length", "scoring", "transcript_status",
        "description_available", "summary_available",
    }
    assert legacy <= set(d)
    assert d["query"] == QUERY
    assert d["evidence_usable"] is False
