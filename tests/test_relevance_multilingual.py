"""Regression tests: CJK/mixed-script relevance and empty-profile detection.

Two defects are pinned here:

1. ``_query_terms`` returned a whole CJK run as a single token, so query
   ``茅台股价`` never matched text containing ``茅台``: the hit was judged
   ``unrelated`` and therefore unusable.  CJK text is not whitespace-delimited,
   so partial matching must work on contiguous >=2-character sub-strings — while
   a shared sub-string (智能 inside 智能手表 for query 人工智能) stays ``partial``
   and never claims certain relevance.
2. ``is_empty_social_profile`` counted follower/following markers, so a profile
   with real posts but 0 followers (or 1 follower) was branded an empty shell and
   discarded.  Only post/video content markers may mean "no content".
"""
from __future__ import annotations

from typing import Any

from hermes_trailhead.extract import VideoEvidence
from hermes_trailhead.scoring import (
    ScoredHit,
    SourceQuality,
    _query_terms,
    assess_evidence,
    assess_relevance,
    is_empty_social_profile,
    score_hit,
)

CJK_QUERY = "茅台股价"


def _hit(query: str = CJK_QUERY, **kwargs) -> ScoredHit:
    base: dict[str, Any] = dict(
        title="贵州茅台股价行情",
        url="https://example.com/moutai-quote",
        snippet="",
        summary="今日茅台股价上涨，机构上调目标价。",
        extraction_status="ok",
        extraction_length=400,
        query=query,
    )
    base.update(kwargs)
    return ScoredHit(**base)


# ── 1. CJK query terms stay whole; mixed-script runs split ──────────────


def test_cjk_query_run_is_kept_whole():
    assert _query_terms(CJK_QUERY) == (CJK_QUERY,)
    assert _query_terms("茅台 股价") == ("茅台", "股价")


def test_mixed_script_query_splits_at_script_boundary():
    assert _query_terms("华为Mate60") == ("华为", "mate60")
    assert assess_relevance("华为 Mate60 发布会实录", "华为Mate60") == (
        "relevant",
        ("on-query: 2/2 query terms matched",),
    )


def test_single_cjk_character_query_still_matches():
    assert _query_terms("茶") == ("茶",)
    assert assess_relevance("茶叶价格与产区", "茶")[0] == "relevant"


# ── 2. CJK partial matching: usable, but never "relevant" ───────────────


def test_cjk_short_text_is_partial_not_unrelated():
    relevance, reasons = assess_relevance("茅台 2024 年营收与渠道改革", CJK_QUERY)
    assert relevance == "partial"
    joined = " ".join(reasons)
    assert "CJK sub-string overlap" in joined
    assert "茅台" in joined


def test_cjk_partial_hit_stays_usable_and_unpenalized():
    hit = _hit(
        title="茅台渠道改革",
        url="https://github.com/example/moutai-notes/issues/7",
        summary="茅台 2024 年渠道改革与出厂价调整记录。",
        extraction_length=900,
    )
    assessment = assess_evidence(hit)
    assert assessment.relevance == "partial"
    assert assessment.usable is True

    d = score_hit(hit).to_dict()
    assert d["evidence_usable"] is True
    assert d["scoring"]["quality"] == "technical"  # GitHub issue
    assert d["scoring"]["score"] > 10  # not capped like an off-query hit


def test_cjk_full_term_is_relevant():
    assert assess_relevance("今日茅台股价上涨3.2%", CJK_QUERY)[0] == "relevant"


def test_generic_cjk_overlap_is_never_certain_relevance():
    # 智能 is a real shared sub-string, but it does not certify 人工智能.
    relevance, reasons = assess_relevance("智能手表评测与选购指南", "人工智能")
    assert relevance == "partial"
    assert "智能" in " ".join(reasons)


def test_cjk_unrelated_text_is_unrelated_and_unusable():
    relevance, reasons = assess_relevance(
        "StealthChanger carriage bolts and belt paths for the VORON build.", CJK_QUERY
    )
    assert relevance == "unrelated"
    assert reasons

    hit = _hit(
        title="StealthChanger assembly notes",
        url="https://github.com/example/stealthchanger/issues/7",
        summary="StealthChanger carriage bolts and belt paths for the VORON build.",
    )
    d = score_hit(hit).to_dict()
    assert d["evidence_relevance"] == "unrelated"
    assert d["evidence_usable"] is False
    assert d["scoring"]["score"] <= 10


# ── 3. Mixed Latin + CJK queries ────────────────────────────────────────


def test_mixed_latin_cjk_query_partial_then_full():
    query = "Agent Reach 茅台股价"

    partial, reasons = assess_relevance("Agent-Reach 发布 茅台 相关更新", query)
    assert partial == "partial"
    assert "CJK sub-string overlap" in " ".join(reasons)

    full, _ = assess_relevance("Agent-Reach 报道茅台股价", query)
    assert full == "relevant"


def test_mixed_query_partial_keeps_hit_usable():
    hit = _hit(
        title="Agent-Reach 与茅台数据源",
        url="https://example.com/agent-reach-moutai",
        summary="Agent-Reach 接入茅台相关数据源。",
        query="Agent Reach 茅台股价",
    )
    assessment = assess_evidence(hit)
    assert assessment.relevance == "partial"
    assert assessment.usable is True


# ── 4. Empty profiles: post/video content only, never follower counts ───

IG_URL = "https://www.instagram.com/coffee.lab/"


def test_profile_with_real_posts_and_zero_followers_is_not_empty():
    text = (
        "0 Followers, 0 Following, 48 Posts - See Instagram photos and videos "
        "from COFFEE LAB (@coffee.lab)\n\n0 followers\n0 following\n48 posts\n"
        "Latest: single-origin Ethiopian roast now shipping."
    )
    assert is_empty_social_profile(IG_URL, text) is False

    hit = _hit(
        title="COFFEE LAB (@coffee.lab) • Instagram photos and videos",
        url=IG_URL,
        summary=text,
        extraction_length=len(text),
        query="coffee lab",
    )
    d = score_hit(hit).to_dict()
    assert d["evidence_usable"] is True
    assert d["scoring"]["quality"] != SourceQuality.PLATFORM_SHELL.value
    assert d["scoring"]["score"] > 0


def test_profile_with_real_posts_and_one_follower_is_not_empty():
    text = "1 Follower, 0 Following, 12 Posts - COFFEE LAB (@coffee.lab)"
    assert is_empty_social_profile(IG_URL, text) is False


def test_follower_counts_alone_never_mean_no_content():
    text = "0 followers · 0 following · No bio yet · Link in bio"
    assert is_empty_social_profile(IG_URL, text) is False


def test_profile_with_no_posts_is_empty():
    for text in (
        "0 posts · 128 followers · 96 following",
        "AGENT REACH (@agent.reach)\nNo posts yet\nSuggested for you",
    ):
        assert is_empty_social_profile(IG_URL, text) is True, text


def test_profile_with_zero_videos_is_empty():
    assert is_empty_social_profile(
        "https://www.tiktok.com/@creator", "creator\n0 videos\n12 followers"
    ) is True
    assert is_empty_social_profile(
        "https://www.tiktok.com/@creator", "creator\n48 videos\n12 followers"
    ) is False


def test_post_urls_are_never_treated_as_empty_profiles():
    assert is_empty_social_profile(
        "https://www.instagram.com/reel/DbV8LwXPDxt/", "0 posts · 0 followers"
    ) is False


# ── 5. description_available / summary_available are not duplicates ─────


def test_caption_only_video_hit_reports_description_available():
    ve = VideoEvidence(caption_status="ok", caption_text="TikTok by @creator: caption only")
    d = ScoredHit(
        title="TikTok by @creator",
        url="https://www.tiktok.com/@creator/video/123",
        snippet="",
        summary="",
        extraction_status="ok",
        video_evidence=ve,
    ).to_dict()
    assert d["description_available"] is True
    assert d["summary_available"] is False

    with_summary = _hit().to_dict()
    assert with_summary["description_available"] is True
    assert with_summary["summary_available"] is True
