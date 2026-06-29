from hermes_trailhead.scoring import (
    SourceQuality,
    SourceScore,
    ScoredHit,
    score_hit,
    score_hits,
    rank_hits,
)
from hermes_trailhead.extract import ExtractedHit, ExtractionResult


def test_source_score_to_dict():
    score = SourceScore(quality=SourceQuality.CANONICAL, score=85, reasons=("Official docs",), label="Docs")
    d = score.to_dict()
    assert d["quality"] == "canonical"
    assert d["score"] == 85
    assert d["reasons"] == ["Official docs"]
    assert d["label"] == "Docs"


def test_scored_hit_to_dict():
    hit = ScoredHit(
        title="Test",
        url="https://github.com/nousresearch/hermes-agent",
        snippet="A repo",
        extraction_status="ok",
        extraction_length=5000,
        scoring=SourceScore(quality=SourceQuality.CANONICAL, score=70, reasons=("GitHub repo root",), label="GitHub repo root"),
    )
    d = hit.to_dict()
    assert set(d) == {"title", "url", "snippet", "summary", "extraction_status", "extraction_length", "scoring", "transcript_status", "description_available", "summary_available"}
    assert d["summary"] == "A repo"
    assert d["summary_available"] is True
    assert d["scoring"]["score"] == 70


def test_github_issue_scores_high():
    hit = ScoredHit(
        title="Bug report",
        url="https://github.com/NousResearch/hermes-agent/issues/42",
        snippet="",
        extraction_status="ok",
        extraction_length=3000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.TECHNICAL
    assert result.scoring.score >= 80
    assert "GitHub issue/PR" in result.scoring.reasons[0]


def test_reddit_thread_scores_practitioner():
    hit = ScoredHit(
        title="Anyone else seeing this?",
        url="https://www.reddit.com/r/hermesagent/comments/abc123/bug_report/",
        snippet="",
        extraction_status="ok",
        extraction_length=2000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.PRACTITIONER
    assert 60 <= result.scoring.score <= 75


def test_docs_site_scores_canonical():
    hit = ScoredHit(
        title="Configuration",
        url="https://docs.hermes-agent.nousresearch.com/config",
        snippet="",
        extraction_status="ok",
        extraction_length=4000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.CANONICAL
    assert result.scoring.score >= 70


def test_help_site_scores_canonical():
    hit = ScoredHit(
        title="Prusa PLA guide",
        url="https://help.prusa3d.com/article/pla_2062",
        snippet="",
        extraction_status="ok",
        extraction_length=4000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.CANONICAL
    assert result.scoring.score >= 70


def test_stealthchanger_official_sources_score_canonical():
    hits = [
        ScoredHit(
            title="Getting Started",
            url="https://stealthchanger.com/getting_started/",
            snippet="",
            extraction_status="ok",
            extraction_length=5000,
        ),
        ScoredHit(
            title="Docs",
            url="https://sdylewski.github.io/StealthChanger/",
            snippet="",
            extraction_status="ok",
            extraction_length=4000,
        ),
        ScoredHit(
            title="Product",
            url="https://ldomotion.com/products/stealth-changer",
            snippet="",
            extraction_status="ok",
            extraction_length=3000,
        ),
    ]

    scored = [score_hit(hit) for hit in hits]
    assert all(hit.scoring.quality == SourceQuality.CANONICAL for hit in scored)
    assert all(hit.scoring.score >= 74 for hit in scored)


def test_github_feature_pages_score_generic():
    hit = ScoredHit(
        title="GitHub Copilot",
        url="https://github.com/features/copilot",
        snippet="",
        extraction_status="ok",
        extraction_length=1000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.GENERIC
    assert result.scoring.score <= 40


def test_github_security_noise_scores_generic():
    hit = ScoredHit(
        title="GitHub Security",
        url="https://github.com/security/advanced-security",
        snippet="",
        extraction_status="ok",
        extraction_length=1000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.GENERIC
    assert result.scoring.score <= 40


def test_pdf_scores_canonical():
    hit = ScoredHit(
        title="Routing whitepaper",
        url="https://example.edu/papers/agent-routing-fallback.pdf",
        snippet="",
        extraction_status="ok",
        extraction_length=4000,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.CANONICAL
    assert result.scoring.score >= 70


def test_medium_blog_scores_low():
    hit = ScoredHit(
        title="10 Tips for AI Agents",
        url="https://medium.com/@author/top-10-ai-agent-tips-abc123",
        snippet="",
        extraction_status="ok",
        extraction_length=1500,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.SEO
    assert result.scoring.score <= 25


def test_tiktok_blocked_is_platform_shell():
    hit = ScoredHit(
        title="Demo video",
        url="https://www.tiktok.com/@user/video/123",
        snippet="",
        extraction_status="blocked",
        extraction_length=0,
    )
    result = score_hit(hit)
    # Without video_evidence, blocked still scores as PLATFORM_SHELL
    assert result.scoring.quality == SourceQuality.PLATFORM_SHELL
    assert result.scoring.score == 0
    assert "blocked" in result.scoring.reasons[0].lower()


def test_tiktok_with_video_evidence_scores_community():
    from hermes_trailhead.extract import VideoEvidence
    hit = ScoredHit(
        title="Demo video",
        url="https://www.tiktok.com/@user/video/123",
        snippet="discovered via search",
        extraction_status="blocked",
        extraction_length=0,
        video_evidence=VideoEvidence(
            metadata_url="https://www.tiktok.com/@user/video/123",
            metadata_title="Demo video",
            visual_analysis_status="available",
            caption_transcript_status="not_attempted",
        ),
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.COMMUNITY
    assert result.scoring.score == 25
    assert "discovered" in result.scoring.reasons[0].lower()


def test_dead_link_scores_zero():
    hit = ScoredHit(
        title="Dead page",
        url="https://example.com/404",
        snippet="",
        extraction_status="error",
        extraction_length=0,
    )
    result = score_hit(hit)
    assert result.scoring.quality == SourceQuality.DEAD
    assert result.scoring.score == 0


def test_high_signal_keyword_boosts_score():
    hit = ScoredHit(
        title="Changelog",
        url="https://example.com/project/changelog-v2",
        snippet="",
        extraction_status="ok",
        extraction_length=1000,
    )
    result = score_hit(hit)
    # Should have a boost from "changelog" keyword
    assert result.scoring.score >= 35  # base generic score
    assert any("changelog" in r.lower() for r in result.scoring.reasons)


def test_score_hits_batch():
    hits = [
        ScoredHit(title="A", url="https://github.com/x/y/issues/1", snippet="", extraction_status="ok", extraction_length=1000),
        ScoredHit(title="B", url="https://medium.com/@x/post", snippet="", extraction_status="ok", extraction_length=500),
        ScoredHit(title="C", url="https://docs.example.com", snippet="", extraction_status="ok", extraction_length=2000),
    ]
    scored = score_hits(hits)
    assert len(scored) == 3
    # Canonical docs should outrank Medium
    assert scored[2].scoring.score > scored[1].scoring.score


def test_rank_hits_sorts_descending():
    hits = [
        ScoredHit(title="Low", url="https://medium.com/x", snippet="", extraction_status="ok", extraction_length=100, scoring=SourceScore(SourceQuality.SEO, 20, ("SEO",), "Medium")),
        ScoredHit(title="High", url="https://github.com/x/y/issues/1", snippet="", extraction_status="ok", extraction_length=1000, scoring=SourceScore(SourceQuality.TECHNICAL, 85, ("GitHub issue",), "Issue")),
        ScoredHit(title="Mid", url="https://docs.example.com", snippet="", extraction_status="ok", extraction_length=500, scoring=SourceScore(SourceQuality.CANONICAL, 75, ("Docs",), "Docs")),
    ]
    ranked = rank_hits(hits)
    assert ranked[0].scoring.score >= ranked[1].scoring.score >= ranked[2].scoring.score
    assert ranked[0].title == "High"


def test_x_status_url_scores_higher_than_profile():
    status = ScoredHit(
        title="breaking news",
        url="https://x.com/nousresearch/status/123456",
        snippet="",
        extraction_status="ok",
        extraction_length=500,
    )
    profile = ScoredHit(
        title="nousresearch profile",
        url="https://x.com/nousresearch",
        snippet="",
        extraction_status="ok",
        extraction_length=2000,
    )
    status_result = score_hit(status)
    profile_result = score_hit(profile)
    assert status_result.scoring.score > profile_result.scoring.score
    assert profile_result.scoring.quality == SourceQuality.CURRENT
    assert "profile" in profile_result.scoring.reasons[0].lower()


def test_scored_hit_from_extracted_hit():
    eh = ExtractedHit(
        title="Test",
        url="https://github.com/x/y",
        snippet="Snippet",
        extraction=ExtractionResult(status="ok", content_length=500, source_type="github"),
    )
    sh = ScoredHit.from_extracted_hit(eh)
    assert sh.title == "Test"
    assert sh.extraction_status == "ok"
    assert sh.extraction_length == 500


def test_summary_prefers_snippet_when_extraction_is_raw_html_shell():
    from hermes_trailhead.extract import ExtractedHit, ExtractionResult
    from hermes_trailhead.scoring import ScoredHit, score_hit

    eh = ExtractedHit(
        title="X post",
        url="https://x.com/example/status/123",
        snippet="Maintainer says the fix shipped yesterday.",
        extraction=ExtractionResult(status="ok", content='<!DOCTYPE html><html data-app-env="prod"><head></head><body>app shell</body></html>', content_length=90),
    )

    scored = score_hit(ScoredHit.from_extracted_hit(eh)).to_dict()

    assert scored["summary"] == "Maintainer says the fix shipped yesterday."
    assert scored["summary_available"] is True
    assert "<!DOCTYPE" not in scored["summary"]
