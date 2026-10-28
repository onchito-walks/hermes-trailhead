"""Hermes Trailhead report — turn a live ``search all --execute --extract`` run into a
repeatable markdown research deliverable.

The `report` subcommand is the Trailhead product loop's emitter: it runs the same
loginless, free-first search-all pipeline as ``search --execute --extract`` and
formats the collected, scored evidence into a self-contained markdown report that is
written to ``docs/outcome-loop/deliverable-<slug>.md`` (or any ``--out`` dir).

This module keeps the render/format logic pure and testable offline: the network is
touched only inside ``run_report`` (via ``execute_search`` / ``extract_hits``), so the
markdown renderer and the CLI writer are covered by deterministic regression tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Iterable, Sequence

from .search import ExecutedSearchRun, execute_search
from .extract import extract_hits
from .scoring import ScoredHit, rank_hits, score_hits

# Column order for the Coverage table, matching the sample deliverable.
LANE_ORDER: tuple[str, ...] = ("web", "x", "reddit", "tiktok", "instagram", "youtube", "github")

# Truncation lengths for readable table cells.
SUMMARY_MAX = 220
TITLE_MAX = 80


def slugify(query: str, max_len: int = 48) -> str:
    """Turn a search query into a filesystem-safe, repeatable slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "report"
    return slug[:max_len].rstrip("-")


def humanize(slug: str) -> str:
    """Turn ``open-source-bounty-market`` into ``Open Source Bounty Market``."""
    return " ".join(word.capitalize() for word in slug.replace("-", " ").split())


def default_title(slug: str) -> str:
    return f"{humanize(slug)} — Trailhead Research Report"


@dataclass(frozen=True)
class LaneCoverage:
    """One row of the Coverage table."""

    platform: str
    status: str
    engine: str
    hit_count: int
    extracted_count: int
    #: Non-empty when this lane's hits were forwarded from a third-party tool.
    #: Carried through from :class:`~hermes_trailhead.search.SearchExecution` so a
    #: report never presents borrowed capability as a native Trailhead result.
    attribution: str = ""


@dataclass(frozen=True)
class NotableSource:
    """One row of the Notable extracted sources table."""

    platform: str
    title: str
    url: str
    score: int
    summary: str
    #: Non-empty when this row came from a forwarded (third-party) lane.
    attribution: str = ""


@dataclass(frozen=True)
class Report:
    """A fully-assembled research report ready to render."""

    title: str
    slug: str
    query: str
    generated_at: str
    coverage: tuple[LaneCoverage, ...]
    notable: tuple[NotableSource, ...]
    caveats: tuple[str, ...]


def _clean_summary(summary: str, max_len: int = SUMMARY_MAX) -> str:
    """Collapse whitespace and cap a summary to a readable table-cell length."""
    text = re.sub(r"\s+", " ", (summary or "")).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _md_escape_cell(text: str) -> str:
    """Escape pipes so arbitrary extracted titles/summaries don't break table rows."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def collect_from_execution(
    executed: ExecutedSearchRun,
    *,
    extract_limit: int | None = None,
    timeout: int = 10,
    per_lane: int = 2,
) -> Report:
    """Build a :class:`Report` from an executed search run, extracting + scoring lanes.

    Mirrors the ``search all --execute --extract --score`` pipeline so the report and
    the interactive search agree on evidence.
    """
    coverage: list[LaneCoverage] = []
    notable: list[NotableSource] = []

    executions_by_key = {e.platform: e for e in executed.executions}
    for platform in LANE_ORDER:
        execution = executions_by_key.get(platform)
        if execution is None:
            continue
        scored: list[ScoredHit] = []
        if execution.hits:
            limit = len(execution.hits) if extract_limit is None else min(extract_limit, len(execution.hits))
            extracted = extract_hits(execution.hits, limit=limit, timeout=timeout)
            scored = rank_hits(score_hits([ScoredHit.from_extracted_hit(eh) for eh in extracted]))
        coverage.append(
            LaneCoverage(
                platform=execution.platform,
                status=execution.status,
                engine=execution.engine,
                hit_count=execution.result_count,
                extracted_count=len(scored),
                attribution=execution.attribution,
            )
        )
        for hit in scored[:per_lane]:
            notable.append(
                NotableSource(
                    platform=execution.platform,
                    title=hit.title,
                    url=hit.url,
                    score=hit.scoring.score if hit.scoring else 0,
                    summary=_clean_summary(hit.summary or hit.snippet),
                    attribution=execution.attribution,
                )
            )

    caveats: list[str] = []
    for execution in executed.executions:
        if execution.caveat and execution.caveat not in caveats:
            caveats.append(execution.caveat)
        # A forwarded lane is borrowed evidence, not a native result: say so in
        # the caveats so the markdown cannot be read as a Trailhead-native win.
        if execution.attribution:
            note = forwarded_caveat(execution.platform, execution.attribution)
            if note not in caveats:
                caveats.append(note)

    return Report(
        title="",
        slug="",
        query=executed.plan.query,
        generated_at="",
        coverage=tuple(coverage),
        notable=tuple(notable),
        caveats=tuple(caveats),
    )


FORWARDED_MARK = "†"


def forwarded_caveat(platform: str, attribution: str) -> str:
    """The honest one-liner for a lane whose leads came from a third-party tool."""
    return (
        f"{platform} leads came from {attribution}; treat them as "
        "third-party results, not native Trailhead hits."
    )


def render_markdown(report: Report, *, footer: str | None = None) -> str:
    """Render a :class:`Report` into the deliverable markdown format."""
    lines: list[str] = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(f"*Generated by Hermes Trailhead, {report.generated_at} · free-first paths only · no paid API*")
    lines.append("")
    lines.append("## Query")
    lines.append("")
    lines.append(f"`{report.query}`")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append("| Lane | Status | Engine | Hits | Extracted |")
    lines.append("|------|--------|--------|------|-----------|")
    for c in report.coverage:
        engine = f"{c.engine} {FORWARDED_MARK}" if c.attribution else c.engine
        lines.append(f"| {c.platform} | {c.status} | {engine} | {c.hit_count} | {c.extracted_count} |")
    lines.append("")
    lines.append("## Notable extracted sources")
    lines.append("")
    lines.append("| Lane | Title | Score | Summary |")
    lines.append("|------|-------|-------|---------|")
    for n in report.notable:
        lane = f"{n.platform} {FORWARDED_MARK}" if n.attribution else n.platform
        lines.append(
            f"| {lane} | {_md_escape_cell(_clean_summary(n.title, TITLE_MAX))} "
            f"| {n.score} | {_md_escape_cell(n.summary)} |"
        )
    lines.append("")
    forwarded = _forwarded_lanes(report)
    if forwarded:
        lines.append(
            f"{FORWARDED_MARK} Forwarded leads: these rows came from the optional Agent Reach "
            "third-party CLI, not from a native Trailhead backend."
        )
        for platform, attribution in forwarded:
            lines.append(f"- {platform}: {attribution}")
        lines.append("")
    lines.append("## Caveats (honest blind spots)")
    lines.append("")
    for caveat in report.caveats:
        lines.append(f"- {caveat}")
    lines.append("")
    lines.append("---")
    if footer is None:
        footer = (
            "Evidence output of Trailhead `search all --execute --extract`. This report is "
            "generated by the repeatable `report` subcommand; see docs/outcome-loop/DECISION.md "
            "for the Trailhead product money loop."
        )
    lines.append(footer)
    lines.append("")
    return "\n".join(lines)


def _forwarded_lanes(report: Report) -> list[tuple[str, str]]:
    """Distinct ``(lane, attribution)`` pairs for forwarded rows, in report order."""
    seen: list[tuple[str, str]] = []
    for item in (*report.coverage, *report.notable):
        pair = (item.platform, item.attribution)
        if item.attribution and pair not in seen:
            seen.append(pair)
    return seen


def default_generated_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run_report(
    query: str,
    *,
    title: str | None = None,
    slug: str | None = None,
    limit: int = 3,
    extract_limit: int | None = None,
    timeout: int = 10,
    per_lane: int = 2,
    fetch=None,
) -> Report:
    """Execute ``search all`` for ``query`` and assemble a :class:`Report`.

    ``fetch`` is injectable for tests; the default uses the loginless public path.
    """
    executed = execute_search("all", query, limit=limit, fetch=fetch)
    base = collect_from_execution(executed, extract_limit=extract_limit, timeout=timeout, per_lane=per_lane)
    slug = slug or slugify(query)
    return Report(
        title=title or default_title(slug),
        slug=slug,
        query=base.query,
        generated_at=default_generated_at(),
        coverage=base.coverage,
        notable=base.notable,
        caveats=base.caveats,
    )


def write_report(report: Report, out_dir: str = "docs/outcome-loop") -> str:
    """Write ``out_dir/deliverable-{slug}.md`` and return the absolute path."""
    from pathlib import Path

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"deliverable-{report.slug}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return str(path.resolve())