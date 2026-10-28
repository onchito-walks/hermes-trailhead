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
from .report import run_report, render_markdown, write_report


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


def cmd_score(args: argparse.Namespace) -> int:
    import json as _json

    from .scores import format_scores_text, lane_scores

    payload = lane_scores(live=args.live)
    if args.format == "json":
        print(_json.dumps(payload, indent=2))
    else:
        print(format_scores_text(payload))
    return 0


def _reach_text_inventory(payload: dict) -> str:
    lines = ["Agent Reach forwarding layer (optional, read-only, attributed)", ""]
    exe = payload.get("executable") or "(not found)"
    lines.append(f"  Executable: {exe}")
    if not payload.get("found"):
        lines.append(f"  Status:     unavailable ({payload.get('reason')})")
    else:
        lines.append(f"  Status:     available (registry schema {payload.get('schema_version')})")
    mode = "public-only (no browser fallback, no credentials)" if payload.get("public_only") else "authenticated forwarding allowed for this run"
    lines.append(f"  Mode:       {mode}")
    caps = payload.get("capabilities") or []
    channels = sorted({row["channel"] for row in caps})
    lines.append(f"  Forwarded:  {len(caps)} read-only action(s) across {len(channels)} channel(s)")
    lines.append("")
    if caps:
        width = max(len(row["channel"]) for row in caps)
        awidth = max(len(row["action"]) for row in caps)
        for row in caps:
            gate = "" if row["public"] else "  [needs --allow-authenticated]"
            backends = ", ".join(row.get("backends") or []) or "-"
            lines.append(
                f"  {row['channel']:<{width}}  {row['action']:<{awidth}}  "
                f"{row['mode']:<12} {backends}{gate}"
            )
        lines.append("")
    error = payload.get("error")
    if error:
        lines.append(f"  Error: {error.get('code')}: {error.get('message')}")
    lines.append("  Not forwarded: transcribe (paid/key-consuming) and every management verb")
    lines.append("  (setup, add, remove, login, browser, configure, update, uninstall, skill).")
    return "\n".join(lines)


def cmd_reach(args: argparse.Namespace) -> int:
    """Capability inventory for the optional Agent Reach forwarding layer."""
    from .reach_backend import AgentReachBackend

    backend = AgentReachBackend(
        args.agent_reach,
        timeout=args.timeout,
        allow_authenticated=args.allow_authenticated,
    )
    payload = backend.describe()
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0
    print(_reach_text_inventory(payload))
    return 0


def _reach_text_result(result) -> str:
    payload = result.to_dict()
    prov = payload.get("provenance") or {}
    head = f"agent-reach {payload.get('channel')} {payload.get('action')}"
    if payload.get("ok"):
        head += f" — ok in {payload.get('elapsed_ms')}ms"
    else:
        err = payload.get("error") or {}
        head += f" — {err.get('code')}: {err.get('message')}"
    lines = [head, ""]
    lines.append(f"  Attribution: {prov.get('attribution') or 'Agent Reach (third-party CLI)'}")
    lines.append(f"  Route:       {prov.get('route') or 'unknown'}"
                 + (f" | forced backend: {prov['forced_backend']}" if prov.get("forced_backend") else ""))
    lines.append(f"  Backend:     {payload.get('backend') or '(upstream did not report one)'}")
    items = payload.get("items") or []
    lines.append(f"  Items:       {len(items)}")
    for index, item in enumerate(items[:5], start=1):
        text = item.get("text") or ""
        title = (item.get("title") or item.get("url") or "(untitled)")[:90]
        lines.append(f"    {index}. {title} — {len(text)} chars")
        if text:
            lines.append("       " + " ".join(text.split())[:160])
    if len(items) > 5:
        lines.append(f"    ... {len(items) - 5} more item(s) in --format json")
    limitations = payload.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("  Limitations:")
        for item in limitations:
            lines.append(f"    - {item}")
    return "\n".join(lines)


def cmd_reach_call(args: argparse.Namespace) -> int:
    """Forward one allowlisted read-only channel/action to Agent Reach."""
    from .reach_backend import AgentReachBackend, ReachBackendError

    backend = AgentReachBackend(
        args.agent_reach,
        timeout=args.timeout,
        allow_authenticated=False,
    )
    params: dict[str, object] = {}
    for raw in args.param or []:
        if "=" not in raw:
            print(f"--param expects NAME=VALUE, got: {raw}", file=sys.stderr)
            return 2
        name, value = raw.split("=", 1)
        if not name.strip():
            print(f"--param expects a name before '=', got: {raw}", file=sys.stderr)
            return 2
        params[name.strip()] = value

    # Positional extras fill the action's required params in declared order.
    if args.arguments:
        declared: list[str] = []
        try:
            registry = backend.registry()
            channel = registry.channels.get(args.channel)
            action = channel.actions.get(args.action) if channel else None
            if action is not None:
                declared = [param.name for param in action.required_params]
        except ReachBackendError:
            declared = []
        extras = list(args.arguments)
        if declared:
            if len(extras) > len(declared):
                print(
                    f"{args.channel} {args.action} takes {len(declared)} positional "
                    f"argument(s) ({', '.join(declared)}); got {len(extras)}",
                    file=sys.stderr,
                )
                return 2
            for name, value in zip(declared, extras):
                params.setdefault(name, value)
        elif len(extras) == 1:
            params.setdefault("target", extras[0])
        else:
            print(
                "could not map positional arguments to declared params; use --param NAME=VALUE",
                file=sys.stderr,
            )
            return 2

    result = backend.execute(
        args.channel,
        args.action,
        params,
        allow_authenticated=args.allow_authenticated,
        max_items=args.limit,
    )
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_reach_text_result(result))
    return 0 if result.ok else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Measured head-to-head case benchmark against an optional Agent Reach CLI."""
    from .comparative import (
        CASES,
        format_compare_markdown,
        format_compare_text,
        run_compare,
        write_report,
    )

    if args.list_cases:
        if args.format == "json":
            print(json.dumps({"cases": [case.to_dict() for case in CASES]}, indent=2))
            return 0
        print("Case manifest (both tools are asked for the same outcome)")
        print()
        for case in CASES:
            gate = " [auth-gated, needs --include-auth]" if case.requires_auth else ""
            print(f"  {case.id:<28} {case.kind:<8} {case.family:<10}{gate}")
            print(f"      prompt:    {case.prompt}")
            print(f"      agent-reach: {' '.join(case.agent_reach_command)}"
                  f"   (requirement: {case.evidence_requirement})")
        return 0

    try:
        report = run_compare(
            case_ids=args.case,
            include_auth=args.include_auth,
            timeout_s=args.timeout,
            agent_reach=args.agent_reach,
            with_agent_reach=not args.no_agent_reach,
            search_limit=args.limit,
            sandbox_dir=args.sandbox,
        )
    except KeyError as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        print("Known cases: " + ", ".join(case.id for case in CASES), file=sys.stderr)
        return 2

    if args.out:
        path = write_report(report, args.out)
        if args.format == "json":
            print(f"Report saved: {path}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0
    if args.format == "markdown":
        print(format_compare_markdown(report))
        return 0
    print(format_compare_text(report))
    if args.out:
        print()
        print(f"Report saved: {args.out}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    if args.execute:
        executed = search_execute_data(args.platform, args.query, live=args.live, limit=args.limit)
        if args.format == "json":
            result = executed.to_dict()
            # Extraction and scoring are default; use --no-extract / --no-score to skip.
            do_extract = getattr(args, 'extract', True)
            # Scoring is an annotation/ranking pass over extracted evidence.
            # Respect --no-extract literally: discovery-only output should not
            # perform hidden page reads just because scoring defaults on.
            do_score = do_extract and getattr(args, 'score', True)
            if do_extract:
                for i, execution in enumerate(executed.executions):
                    if execution.hits:
                        extract_limit = len(execution.hits) if args.extract_limit is None else min(args.extract_limit, len(execution.hits))
                        extracted = extract_hits(execution.hits, limit=extract_limit, timeout=10)
                        scored = [ScoredHit.from_extracted_hit(eh) for eh in extracted]
                        if do_score:
                            scored = rank_hits(score_hits(scored))
                        extracted_dicts = [sh.to_dict() for sh in scored]
                        if not do_score:
                            for hit in extracted_dicts:
                                hit["scoring"] = None
                        result["executions"][i]["extracted"] = extracted_dicts
                        if do_score:
                            # Rank the top-level hits[] to follow the scored
                            # evidence order (README: 'ranks results by
                            # quality'). Unranked hits (beyond --extract-limit)
                            # keep discovery order after the ranked ones.
                            ranked_pos = {d.get("url"): idx for idx, d in enumerate(extracted_dicts)}
                            hits_now = result["executions"][i].get("hits") or []
                            result["executions"][i]["hits"] = sorted(
                                hits_now,
                                key=lambda h: ranked_pos.get(h.get("url"), len(ranked_pos)),
                            )
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
                    cap = getattr(ve, 'caption_status', 'not_applicable') if ve else 'not_applicable'
                    desc = eh.extraction.content[:200] if eh.extraction.content else '(no description)'
                    icon = {'ok': '✅', 'available': '✅', 'blocked': '❌', 'not_available': '⚠️', 'not_configured': '⚠️'}.get(ts, '❓')
                    print(f"     {icon} transcript: {ts} | caption: {cap} | source: {eh.extraction.source_type or '?'} | {eh.extraction.content_length}B")
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


def cmd_report(args: argparse.Namespace) -> int:
    """Run a live `search all --execute --extract` and emit a markdown research deliverable."""
    report = run_report(
        args.query,
        title=args.title or None,
        slug=args.slug or None,
        limit=args.limit,
        extract_limit=args.extract_limit,
    )
    if args.dry_run:
        print(render_markdown(report))
        return 0
    path = write_report(report, args.out)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "slug": report.slug,
                    "title": report.title,
                    "query": report.query,
                    "generated_at": report.generated_at,
                    "path": path,
                    "coverage": [
                        {
                            "platform": c.platform,
                            "status": c.status,
                            "engine": c.engine,
                            "hit_count": c.hit_count,
                            "extracted_count": c.extracted_count,
                        }
                        for c in report.coverage
                    ],
                    "notable_count": len(report.notable),
                    "caveats_count": len(report.caveats),
                },
                indent=2,
            )
        )
        return 0
    print(path)
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

    score = sub.add_parser("score", help="Per-lane product scorecard (historical static claims + measured route probes with --live)")
    score.add_argument("--format", choices=["text", "json"], default="text")
    score.add_argument("--live", action="store_true", help="Probe each lane's key route from this host")
    score.set_defaults(func=cmd_score)

    reach = sub.add_parser(
        "reach",
        help="Inventory the optional Agent Reach forwarding layer (read-only, attributed)",
        description=(
            "Print which read-only Agent Reach channel/action pairs Trailhead can "
            "forward, how each one can be reached (public API, forced public-web, or "
            "authenticated with explicit consent), and why the rest are excluded. "
            "Discovery order: --agent-reach, TRAILHEAD_AGENT_REACH_BIN, PATH. Nothing "
            "is installed, configured, logged in to, or copied."
        ),
    )
    reach.add_argument("--agent-reach", metavar="PATH", help="Path to an installed agent-reach CLI")
    reach.add_argument("--timeout", type=float, default=30, help="Registry/diagnostic timeout in seconds")
    reach.add_argument("--allow-authenticated", action="store_true", help="Report modes as if authenticated forwarding were consented")
    reach.add_argument("--format", choices=["text", "json"], default="text")
    reach.set_defaults(func=cmd_reach)

    reach_call = sub.add_parser(
        "reach-call",
        help="Forward one allowlisted read-only channel/action to Agent Reach (attributed)",
        description=(
            "Run a single read-only Agent Reach action and print the result with its "
            "Agent Reach attribution. Public mode forces --backend public-web where the "
            "upstream declares a public route and never falls back to a browser; "
            "session-only actions return auth_required unless --allow-authenticated is "
            "passed explicitly. Positional ARGS fill the action's required params in "
            "declared order; use --param NAME=VALUE for anything else."
        ),
    )
    reach_call.add_argument("channel", help="Channel name, e.g. github, v2ex, web")
    reach_call.add_argument("action", help="Read-only action, e.g. read, search, hot")
    reach_call.add_argument("arguments", nargs="*", help="Positional arguments for the action's required params")
    reach_call.add_argument("--param", action="append", metavar="NAME=VALUE", help="Action parameter (repeatable)")
    reach_call.add_argument("--limit", type=int, default=10, help="Max items returned (default: 10)")
    reach_call.add_argument("--timeout", type=float, default=30, help="Upstream timeout in seconds (default: 30)")
    reach_call.add_argument("--allow-authenticated", action="store_true", help="Consent to use the operator's existing Agent Reach login")
    reach_call.add_argument("--agent-reach", metavar="PATH", help="Path to an installed agent-reach CLI")
    reach_call.add_argument("--format", choices=["text", "json"], default="text")
    reach_call.set_defaults(func=cmd_reach_call)

    compare = sub.add_parser(
        "compare",
        help="Run the same URL/question cases against Trailhead and an installed Agent Reach CLI",
        description=(
            "Measured head-to-head benchmark over an explicit case manifest. Both "
            "tools are asked for the same outcome (a transcript case uses "
            "`youtube subtitle`, a node listing uses `v2ex node`). Records status, "
            "duration, raw and cleaned characters, evidence verdict, and upstream "
            "errors per side; no A/A- grades and no aggregate winner. Both sides "
            "run in killable subprocesses with equal wall-clock budgets and "
            "temporary homes; environment credentials, sessions and proxies "
            "are withheld, not filesystem-sandboxed. ASR is disabled. Auth-shaped "
            "cases are skipped unless --include-auth is passed; those remain "
            "unauthenticated attempts, not a configured-account comparison."
        ),
    )
    compare.add_argument("--case", action="append", metavar="ID", help="Case id to run (repeatable; default: all public cases)")
    compare.add_argument("--include-auth", action="store_true", help="Include auth-shaped cases (explicit opt-in)")
    compare.add_argument("--timeout", type=float, default=30, help="Per-side timeout in seconds (default: 30)")
    compare.add_argument("--limit", type=int, default=3, help="Hits per lane for question cases (default: 3)")
    compare.add_argument("--agent-reach", metavar="PATH", help="Path to an installed agent-reach CLI (default: PATH lookup)")
    compare.add_argument("--no-agent-reach", action="store_true", help="Skip the Agent Reach side (recorded as not_run)")
    compare.add_argument("--out", metavar="PATH", help="Write the JSON report to this path")
    compare.add_argument("--list-cases", action="store_true", help="List the case manifest and exit")
    compare.add_argument(
        "--sandbox",
        metavar="DIR",
        help=(
            "Reuse an existing sandbox directory to measure a warm run "
            "(default: a fresh cold sandbox under TMPDIR)"
        ),
    )
    compare.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    compare.set_defaults(func=cmd_compare)

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
    search.add_argument("--limit", type=int, default=12, help="Max hits per platform when --execute is used")
    search.add_argument("--extract", action="store_true", default=True, help="Extract page content from search hits (default: on)")
    search.add_argument("--no-extract", action="store_false", dest="extract", help="Skip extraction — return discovery links only")
    search.add_argument("--extract-limit", type=int, default=None, help="Max hits to extract per platform (defaults to --limit)")
    search.add_argument("--score", action="store_true", default=True, help="Score and rank search hits by source quality (default: on)")
    search.add_argument("--no-score", action="store_false", dest="score", help="Skip scoring — return raw summaries only")
    search.set_defaults(func=cmd_search)

    report = sub.add_parser(
        "report",
        help="Run a live search-all and emit a markdown research deliverable",
        description=(
            "Run `search all QUERY --execute --extract` and format the collected, scored "
            "evidence into a self-contained markdown report. By default writes "
            "docs/outcome-loop/deliverable-<slug>.md; use --dry-run to print without writing."
        ),
    )
    report.add_argument("query", help="Research question / topic to report on")
    report.add_argument("--title", help="Report title (default: derived from slug)")
    report.add_argument("--slug", help="Output filename slug (default: derived from query)")
    report.add_argument("--out", default="docs/outcome-loop", help="Output directory (default: docs/outcome-loop)")
    report.add_argument("--limit", type=int, default=3, help="Max hits per lane (default: 3)")
    report.add_argument("--extract-limit", type=int, default=None, help="Max hits to extract per lane (defaults to --limit)")
    report.add_argument("--dry-run", action="store_true", help="Print the markdown report instead of writing a file")
    report.add_argument("--format", choices=["text", "json"], default="text")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
