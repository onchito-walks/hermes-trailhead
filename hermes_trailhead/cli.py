"""Hermes Trailhead CLI — source-terrain, route, and evidence commands for Hermes research."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable
from typing import cast

from . import __version__
from .channels import CHANNELS, Channel, CheckResult, check_all, check_all_live, get_channel
from .formatters import (
    STATUS_ORDER,
    RISK_ORDER,
    filter_rows,
    exit_code,
    format_json,
    emit,
    format_queue_text,
    format_plan_text,
    format_brief_json,
    format_brief_text,
    format_routes_json,
    format_routes_text,
    format_route_json,
    format_route_text,
    format_radar_text,
)
from .router import all_routes, route_for
from .router import route_for_with_live, score_route_with_live_state
from .search import PLATFORMS, Platform, execute_search, search_run, ExecutedSearchRun, SearchRun
from .extract import extract_hits
from .scoring import score_hits, rank_hits, ScoredHit
from .reliability import record_all_checks, reliability_summary
from .benchmarks import BENCHMARK_TASKS, run_all_benchmarks, run_benchmark, BenchmarkScore
from .gauntlet import run_gauntlet


RADAR_KEYS = [
    "hermes-upstream", "docs-watcher", "newsletter", "x-search", "agent-reach",
    "tiktok", "instagram", "youtube", "reddit", "github", "web-search", "web-extract",
]


def doctor_data(live: bool = False) -> list[tuple[Channel, CheckResult]]:
    """Return all channel check results without printing. Caller formats."""
    return check_all_live() if live else check_all()


def filtered_doctor_data(
    *,
    live: bool = False,
    only: str | None = None,
    risk: str | None = None,
    channel: str | None = None,
    tag: str | None = None,
) -> list[tuple[Channel, CheckResult]]:
    """Return filtered channel check results."""
    return filter_rows(doctor_data(live=live), only=only, risk=risk, channel=channel, tag=tag)


def queue_data(top: int | None = None) -> list[tuple[Channel, CheckResult]]:
    """Return prioritized gap list (non-ok channels, sorted by severity)."""
    rows = [(ch, res) for ch, res in check_all() if res.status != "ok"]
    rows.sort(key=lambda pair: (STATUS_ORDER.get(pair[1].status, 99), RISK_ORDER.get(pair[0].risk, 99), pair[0].key))
    if top:
        rows = rows[:top]
    return rows


def search_data(platform: str, query: str, *, live: bool = False) -> SearchRun:
    """Return a agent-usable search action plan without printing."""
    return search_run(cast(Platform, platform), query, live=live)


def search_execute_data(platform: str, query: str, *, live: bool = False, limit: int = 5) -> ExecutedSearchRun:
    """Execute a Hermes Trailhead search through loginless public search paths."""
    return execute_search(cast(Platform, platform), query, live=live, limit=limit)


def cmd_doctor(args: argparse.Namespace) -> int:
    all_rows = check_all_live() if args.live else check_all()
    rows = filter_rows(all_rows, only=args.only, risk=args.risk, channel=args.channel, tag=args.tag)
    if args.live and getattr(args, 'record', False):
        record_all_checks(all_rows)
    print(emit(rows, args.format, title="Hermes Trailhead doctor"))
    return exit_code(rows, strict=args.strict)


def cmd_queue(args: argparse.Namespace) -> int:
    rows = filter_rows(check_all(), only=args.only, risk=args.risk, channel=args.channel, tag=args.tag)
    rows.sort(key=lambda pair: (STATUS_ORDER.get(pair[1].status, 99), RISK_ORDER.get(pair[0].risk, 99), pair[0].key))
    if not args.all:
        rows = [(ch, res) for ch, res in rows if res.status != "ok"]
    if args.top:
        rows = rows[: args.top]
    if args.format == "json":
        print(format_json(rows))
    elif args.format == "markdown":
        print(emit(rows, "markdown", title="Hermes Trailhead queue"))
    else:
        print(format_queue_text(rows))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        ch = get_channel(args.channel)
    except KeyError:
        print(f"Unknown channel: {args.channel}", file=sys.stderr)
        print("Known channels: " + ", ".join(c.key for c in CHANNELS), file=sys.stderr)
        return 2
    res = ch.check()
    print(format_plan_text(ch, res))
    return 0


def cmd_capability_radar(args: argparse.Namespace) -> int:
    rows_by_key = {ch.key: (ch, res) for ch, res in check_all()}
    radar_keys = ["hermes-upstream", "docs-watcher", "newsletter", "x-search", "agent-reach"]
    rows = [rows_by_key[k] for k in radar_keys if k in rows_by_key]
    if args.format == "json":
        print(format_json(rows))
    else:
        print(format_radar_text(rows))
    return 0


def cmd_agent_brief(args: argparse.Namespace) -> int:
    rows = check_all()
    if args.format == "json":
        print(format_brief_json(rows, RADAR_KEYS))
    else:
        print(format_brief_text(rows, RADAR_KEYS))
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    routes = all_routes()
    if args.format == "json":
        print(format_routes_json(routes))
    else:
        print(format_routes_text(routes))
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    route = route_for(args.intent)
    if args.format == "json":
        print(format_route_json(route))
    else:
        print(format_route_text(route))
    return 0


def cmd_reliability(args: argparse.Namespace) -> int:
    summary = reliability_summary(lookback_days=getattr(args, 'days', 30))
    if args.format == "json":
        print(json.dumps(summary, indent=2))
        return 0
    print("# Hermes Trailhead reliability\n")
    print(f"Records: {summary['total_records']} | Updated: {summary['updated_at'][:19] if summary['updated_at'] else 'never'}")
    print()
    channels = summary.get("channels", {})
    if not channels:
        print("No reliability data yet. Run 'hermes-trailhead doctor --live --record' to start tracking.")
        return 0
    trend_icon = {"improving": "↑", "declining": "↓", "stable": "→"}
    for key, ch in sorted(channels.items()):
        icon = trend_icon.get(ch["trend"], "?")
        status_icon = {"ok": "✅", "warn": "⚠️", "off": "⬜", "fail": "❌"}.get(ch["recent_status"], "?")
        print(f"{status_icon} {icon} {key}: {ch['success_rate']}% ok ({ch['check_count']} checks) — {ch['trend']}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    if getattr(args, 'task', None):
        task = next((t for t in BENCHMARK_TASKS if t.id == args.task), None)
        if task is None:
            print(f"Unknown task: {args.task}", file=sys.stderr)
            print("Known tasks: " + ", ".join(t.id for t in BENCHMARK_TASKS), file=sys.stderr)
            return 2
        bench_run, score = run_benchmark(task, limit=args.limit)
        if args.format == "json":
            print(json.dumps({"task": task.name, "score": score.to_dict()}, indent=2, default=str))
            return 0
        print(f"# Benchmark: {task.name}\n")
        print(f"Category: {task.category} | Query: {task.query}")
        print(f"Hits: {bench_run.total_hits} across {bench_run.platforms_with_hits} platforms")
        print(f"Extraction: {bench_run.extracted_ok_count}/{bench_run.extracted_count} succeeded")
        print(f"Source types: {', '.join(bench_run.source_types_found) if bench_run.source_types_found else 'none'}")
        print()
        print(f"## Score: {score.total_score}/100 [{score.verdict.upper()}]")
        print(f"  Coverage:  {score.coverage_score}/100")
        print(f"  Extraction: {score.extraction_score}/100")
        print(f"  Source quality: {score.source_quality_score}/100")
        print(f"  Caveat honesty: {score.caveat_honesty_score}/100")
        if score.notes:
            print(f"  Notes: {'; '.join(score.notes)}")
        return 0

    result = run_all_benchmarks(limit=args.limit)
    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
        return 0
    print(f"# Hermes Trailhead benchmarks ({result['task_count']} tasks)\n")
    for r in result["results"]:
        s = r["score"]
        icon = {"pass": "✅", "partial": "⚠️", "fail": "❌"}.get(s["verdict"], "?")
        print(f"{icon} {s['total_score']:3d}/100 {r['task']}")
        if s["notes"]:
            print(f"   {'; '.join(s['notes'])}")
    agg = result["aggregate"]
    print(f"\nAggregate: {agg['average_score']}/100 | {agg['passes']} pass, {agg['partials']} partial, {agg['fails']} fail")
    return 0 if agg["fails"] == 0 else 1


def cmd_gauntlet(args: argparse.Namespace) -> int:
    """Run the deterministic PhD-level Trailhead product gauntlet."""
    result = run_gauntlet()
    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["aggregate"]["fails"] == 0 else 1

    print(f"# Hermes Trailhead PhD gauntlet ({result['case_count']} cases)\n")
    print(f"Mode: {result['mode']}")
    print("Hard-source lanes: " + ", ".join(result["hard_source_lanes"]))
    print()
    for r in result["results"]:
        icon = {"pass": "✅", "partial": "⚠️", "fail": "❌"}.get(r["verdict"], "?")
        print(f"{icon} {r['total_score']:3d}/100 {r['case_name']}")
        print(
            "   lanes={lane_coverage_score} extraction={extraction_contract_score} "
            "transcripts={transcript_score} quality={quality_score} caveats={caveat_honesty_score}".format(**r)
        )
        if r["notes"]:
            print("   " + "; ".join(r["notes"]))
    agg = result["aggregate"]
    print(f"\nAggregate: {agg['average_score']}/100 | {agg['passes']} pass, {agg['partials']} partial, {agg['fails']} fail")
    return 0 if agg["fails"] == 0 else 1


def cmd_search(args: argparse.Namespace) -> int:
    if args.execute:
        executed = search_execute_data(args.platform, args.query, live=args.live, limit=args.limit)
        if args.format == "json":
            result = executed.to_dict()
            # Extraction is default; --no-extract skips it. Scoring is additive on top.
            do_extract = getattr(args, 'extract', True)
            if do_extract or getattr(args, 'score', False):
                for i, execution in enumerate(executed.executions):
                    if execution.hits:
                        extract_limit = len(execution.hits) if args.extract_limit is None else min(args.extract_limit, len(execution.hits))
                        extracted = extract_hits(execution.hits, limit=extract_limit, timeout=10)
                        scored = [ScoredHit.from_extracted_hit(eh) for eh in extracted]
                        if getattr(args, 'score', False):
                            scored = rank_hits(score_hits(scored))
                        result["executions"][i]["extracted"] = [sh.to_dict() for sh in scored]
            print(json.dumps(result, indent=2))
            return 0
        print(f"# Hermes Trailhead executed search: {args.platform}\n")
        print(f"Query: {executed.plan.query}")
        print(f"Paid API required: {'yes' if executed.plan.paid_api_required else 'no'}")
        print()
        do_extract = getattr(args, 'extract', True)
        for execution in executed.executions:
            print(f"## {execution.platform} — {execution.status} ({execution.result_count} hits)\n")
            print(f"Engine: {execution.engine}")
            if execution.caveat:
                print(f"Caveat: {execution.caveat}")
            if execution.error:
                print(f"Error: {execution.error}")
            for i, hit in enumerate(execution.hits, start=1):
                print(f"  {i}. {hit.title[:100]}")
                print(f"     {hit.url}")
            # Show extracted evidence when available
            if do_extract and execution.hits:
                print()
                extract_limit = len(execution.hits) if args.extract_limit is None else min(args.extract_limit, len(execution.hits))
                extracted = extract_hits(execution.hits, limit=extract_limit, timeout=10)
                for eh in extracted:
                    ve = eh.extraction.video_evidence
                    ts = getattr(ve, 'caption_transcript_status', 'not_applicable') if ve else 'not_applicable'
                    desc = eh.extraction.content[:200] if eh.extraction.content else '(no description)'
                    icon = {'ok': '✅', 'available': '✅', 'blocked': '❌', 'not_available': '⚠️', 'not_configured': '⚠️'}.get(ts, '❓')
                    print(f"     {icon} transcript: {ts} | source: {eh.extraction.source_type or '?'} | {eh.extraction.content_length}B")
                    print(f"     desc: {desc}")
            print()
        return 0

    run = search_data(args.platform, args.query, live=args.live)
    if args.format == "json":
        print(json.dumps(run.to_dict(), indent=2))
        return 0

    print(f"# Hermes Trailhead search: {args.platform}\n")
    print(f"Query: {run.query}")
    print(f"Mode: {run.mode}")
    print(f"Paid API required: {'yes' if run.paid_api_required else 'no'}")
    print()
    for action in run.actions:
        approval = " approval-required" if action.approval_required else ""
        print(f"## {action.platform} — {action.status}{approval}\n")
        print(f"Recommended tool: {action.recommended_tool}")
        if action.site_query:
            print(f"Site query: {action.site_query}")
        if action.direct_url:
            print(f"Direct URL: {action.direct_url}")
        if action.frontend_url:
            print(f"Frontend: {action.frontend_url}")
        print(f"Paid API required: {'yes' if action.paid_api_required else 'no'}")
        if action.evidence_needed:
            print("Evidence needed:")
            for item in action.evidence_needed:
                print(f"- {item}")
        if action.caveat:
            print(f"Caveat: {action.caveat}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-trailhead",
        description="Make high-signal hard-to-reach internet sources part of Hermes research without paid APIs by default",
    )
    parser.add_argument("--version", action="version", version=f"hermes-trailhead {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--format", choices=["text", "json", "markdown"], default="text")
        p.add_argument("--only", help="Comma-separated statuses: ok,warn,off,fail")
        p.add_argument("--risk", help="Comma-separated risks: low,medium,high")
        p.add_argument("--channel", help="Comma-separated channel keys")
        p.add_argument("--tag", help="Comma-separated tags")

    doctor = sub.add_parser("doctor", help="Check which source routes are actually available")
    add_common(doctor)
    doctor.add_argument("--strict", action="store_true", help="Return nonzero on any warn/off result")
    doctor.add_argument("--live", action="store_true", help="Probe live endpoints for reachability evidence")
    doctor.add_argument("--record", action="store_true", help="Record live results to reliability tracker")
    doctor.set_defaults(func=cmd_doctor)

    queue = sub.add_parser("queue", help="Show source lanes whose gaps most limit research quality")
    add_common(queue)
    queue.add_argument("--all", action="store_true", help="Include green checks too")
    queue.add_argument("--top", type=int, help="Limit queue length")
    queue.set_defaults(func=cmd_queue)

    plan = sub.add_parser("plan", help="Print safe setup/usage plan for one channel")
    plan.add_argument("channel")
    plan.set_defaults(func=cmd_plan)

    radar = sub.add_parser("capability-radar", help="Summarize source-route readiness and upstream drift")
    radar.add_argument("--format", choices=["text", "json"], default="text")
    radar.set_defaults(func=cmd_capability_radar)

    brief = sub.add_parser("agent-brief", help="Emit Hermes research brief: best routes, gaps, and approvals")
    brief.add_argument("--format", choices=["text", "json"], default="text")
    brief.set_defaults(func=cmd_agent_brief)

    routes = sub.add_parser("routes", help="List task routes for web, social, browser, and extraction sources")
    routes.add_argument("--format", choices=["text", "json"], default="text")
    routes.set_defaults(func=cmd_routes)

    route = sub.add_parser("route", help="Choose a route for a natural-language internet/research task")
    route.add_argument("intent", help="Task intent, e.g. 'extract schema from pages' or 'login browser work'")
    route.add_argument("--format", choices=["text", "json"], default="text")
    route.add_argument("--live", action="store_true", help="Score route against live channel health checks")
    route.set_defaults(func=cmd_route)

    reliability = sub.add_parser("reliability", help="Show per-channel reliability trends over time")
    reliability.add_argument("--format", choices=["text", "json"], default="text")
    reliability.add_argument("--days", type=int, default=30, help="Lookback window in days (default: 30)")
    reliability.set_defaults(func=cmd_reliability)

    benchmark = sub.add_parser("benchmark", help="Run outcome-based benchmarks against real research tasks")
    benchmark.add_argument("--format", choices=["text", "json"], default="text")
    benchmark.add_argument("--limit", type=int, default=3, help="Max hits per platform (default: 3)")
    benchmark.add_argument("--task", help="Run a specific benchmark task by ID (default: run all)")
    benchmark.set_defaults(func=cmd_benchmark)

    gauntlet = sub.add_parser("gauntlet", help="Run deterministic PhD-level hard-source product contract")
    gauntlet.add_argument("--format", choices=["text", "json"], default="text")
    gauntlet.set_defaults(func=cmd_gauntlet)

    search = sub.add_parser(
        "search",
        help="Plan or execute a source-terrain search with evidence requirements",
        description="Plan source-family routes, or execute them via loginless public search paths with --execute.",
    )
    search.add_argument("platform", choices=["all", *PLATFORMS], help="Source family to search")
    search.add_argument("query", help="Search query / topic")
    search.add_argument("--format", choices=["text", "json"], default="text")
    search.add_argument("--live", action="store_true", help="Probe configured live frontends where supported")
    search.add_argument("--execute", action="store_true", help="Execute search using loginless public search paths and return real hits")
    search.add_argument("--limit", type=int, default=5, help="Max hits per platform when --execute is used")
    search.add_argument("--extract", action="store_true", default=True, help="Extract page content from search hits (default: on)")
    search.add_argument("--no-extract", action="store_false", dest="extract", help="Skip extraction — return discovery links only")
    search.add_argument("--extract-limit", type=int, default=None, help="Max hits to extract per platform (defaults to --limit)")
    search.add_argument("--score", action="store_true", help="Score and rank search hits by source quality")
    search.set_defaults(func=cmd_search)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
