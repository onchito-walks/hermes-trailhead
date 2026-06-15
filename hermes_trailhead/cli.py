"""Hermes Trailhead CLI — thin argparse layer over formatters, channels, router, and search."""
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
from .search import PLATFORMS, Platform, execute_search, search_run, ExecutedSearchRun, SearchRun


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


def cmd_search(args: argparse.Namespace) -> int:
    if args.execute:
        executed = search_execute_data(args.platform, args.query, live=args.live, limit=args.limit)
        if args.format == "json":
            print(json.dumps(executed.to_dict(), indent=2))
            return 0
        print(f"# Hermes Trailhead executed search: {args.platform}\n")
        print(f"Query: {executed.plan.query}")
        print(f"Paid API required: {'yes' if executed.plan.paid_api_required else 'no'}")
        print()
        for execution in executed.executions:
            print(f"## {execution.platform} — {execution.status} ({execution.result_count} results)\n")
            print(f"Executed query: {execution.executed_query}")
            print(f"Engine: {execution.engine}")
            if execution.error:
                print(f"Error: {execution.error}")
            for i, hit in enumerate(execution.hits, start=1):
                print(f"{i}. {hit.title}")
                print(f"   {hit.url}")
                if hit.snippet:
                    print(f"   {hit.snippet}")
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
    parser = argparse.ArgumentParser(prog="hermes-trailhead", description="Help command-line agents search/read hard-to-reach sources without requiring paid APIs")
    parser.add_argument("--version", action="version", version=f"hermes-trailhead {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--format", choices=["text", "json", "markdown"], default="text")
        p.add_argument("--only", help="Comma-separated statuses: ok,warn,off,fail")
        p.add_argument("--risk", help="Comma-separated risks: low,medium,high")
        p.add_argument("--channel", help="Comma-separated channel keys")
        p.add_argument("--tag", help="Comma-separated tags")

    doctor = sub.add_parser("doctor", help="Check all reach channels")
    add_common(doctor)
    doctor.add_argument("--strict", action="store_true", help="Return nonzero on any warn/off result")
    doctor.add_argument("--live", action="store_true", help="Probe live endpoints for reachability evidence")
    doctor.set_defaults(func=cmd_doctor)

    queue = sub.add_parser("queue", help="Show prioritized reach/setup gaps")
    add_common(queue)
    queue.add_argument("--all", action="store_true", help="Include green checks too")
    queue.add_argument("--top", type=int, help="Limit queue length")
    queue.set_defaults(func=cmd_queue)

    plan = sub.add_parser("plan", help="Print safe setup/usage plan for one channel")
    plan.add_argument("channel")
    plan.set_defaults(func=cmd_plan)

    radar = sub.add_parser("capability-radar", help="Summarize install-vs-reach state")
    radar.add_argument("--format", choices=["text", "json"], default="text")
    radar.set_defaults(func=cmd_capability_radar)

    brief = sub.add_parser("agent-brief", help="Emit Hermes-agent routing brief for internet tasks")
    brief.add_argument("--format", choices=["text", "json"], default="text")
    brief.set_defaults(func=cmd_agent_brief)

    routes = sub.add_parser("routes", help="List task routes for web, social, browser, and extraction sources")
    routes.add_argument("--format", choices=["text", "json"], default="text")
    routes.set_defaults(func=cmd_routes)

    route = sub.add_parser("route", help="Choose a route for a natural-language internet/research task")
    route.add_argument("intent", help="Task intent, e.g. 'extract schema from pages' or 'login browser work'")
    route.add_argument("--format", choices=["text", "json"], default="text")
    route.set_defaults(func=cmd_route)

    search = sub.add_parser(
        "search",
        help="Build or execute a agent-usable search for hard-to-reach sources",
        description="Build an action plan, or execute it via loginless public search paths with --execute.",
    )
    search.add_argument("platform", choices=["all", *PLATFORMS], help="Source family to search")
    search.add_argument("query", help="Search query / topic")
    search.add_argument("--format", choices=["text", "json"], default="text")
    search.add_argument("--live", action="store_true", help="Probe configured live frontends where supported")
    search.add_argument("--execute", action="store_true", help="Execute search using loginless public search paths and return real hits")
    search.add_argument("--limit", type=int, default=5, help="Max hits per platform when --execute is used")
    search.set_defaults(func=cmd_search)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
