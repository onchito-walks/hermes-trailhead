"""Hermes Trailhead CLI — source-terrain, route, and evidence commands for Hermes research."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from typing import Iterable
from typing import cast
from urllib.parse import urlparse

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
from .search import PLATFORMS, Platform, execute_search, search_run, ExecutedSearchRun, SearchRun, SearchHit
from .extract import extract_hits
from .scoring import score_hits, rank_hits, score_hit, ScoredHit
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


def _reach_text_parity(payload: dict) -> str:
    """Pinned 40-action parity table: coverage, gate, evidence — no live claims."""
    parity = payload.get("parity") or {}
    reference = parity.get("reference") or {}
    counts = parity.get("counts") or {}
    rows = parity.get("actions") or []
    lines = [
        "Parity reference: {project} {version} @ {commit} ({actions} actions / {channels} channels, "
        "measured {measured})".format(
            project=reference.get("project", "?"),
            version=reference.get("version", "?"),
            commit=(reference.get("commit") or "?")[:12],
            actions=reference.get("actions", "?"),
            channels=reference.get("channels", "?"),
            measured=reference.get("measured", "?"),
        ),
        "",
    ]
    if not rows:
        lines.append("  (inventory unavailable)")
        return "\n".join(lines)
    width = max(len(row["channel"]) for row in rows)
    awidth = max(len(row["action"]) for row in rows)
    cwidth = max(len(row["coverage"]) for row in rows)
    lines.append(f"  {'channel':<{width}}  {'action':<{awidth}}  {'coverage':<{cwidth}}  {'gate':<7}  evidence")
    for row in rows:
        gate = row.get("gate") or "?"
        evidence = ", ".join(row.get("evidence") or [])
        lines.append(
            f"  {row['channel']:<{width}}  {row['action']:<{awidth}}  "
            f"{row['coverage']:<{cwidth}}  {gate:<7}  {evidence}"
        )
    lines.append("")
    lines.append(
        "  Totals: {actions}/{actions} inventoried; native {native} (+{partial} partial), "
        "upstream-only {upstream}; public {public}, auth-gated {auth}, quota-gated {quota}.".format(
            actions=counts.get("actions", 0),
            native=counts.get("native", 0),
            partial=counts.get("native_partial", 0),
            upstream=counts.get("upstream_only", 0),
            public=counts.get("public", 0),
            auth=counts.get("gated_auth", 0),
            quota=counts.get("gated_quota", 0),
        )
    )
    surfaced = counts.get("surfaced", 0)
    total = counts.get("actions", 0)
    ratio = counts.get("surfaced_ratio")
    if ratio is None:
        ratio = (surfaced / total) if total else 0.0
    lines.append(
        "  Surfaced: {surfaced}/{total} inventoried actions (ratio {ratio:.2f}); "
        "gates are public / consent / quota.".format(
            surfaced=surfaced, total=total, ratio=ratio
        )
    )
    lines.append(
        "  Evidence: live-verified {live}; {fixture} rows are fixture/native contract tests only "
        "— not live runs. See docs/ACTION-PARITY.md.".format(
            live=counts.get("live_verified", 0),
            fixture=counts.get("fixture_only", 0),
        )
    )
    return "\n".join(lines)


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
    quota_mode = "consented" if payload.get("quota_consuming_allowed") else "not consented"
    auth_mode = "consented" if payload.get("authenticated_allowed") else "not consented"
    veto = "on" if payload.get("asr_vetoed", payload.get("asr_disabled")) else "off"
    ready = "ready" if payload.get("quota_ready") else "not ready"
    lines.append(
        f"  Quota:      {quota_mode} (--allow-quota-consuming) | "
        f"auth consent: {auth_mode} | ASR veto (TRAILHEAD_DISABLE_ASR): {veto}"
    )
    lines.append(
        f"  Quota now:  {ready} — a quota call needs quota consent AND auth consent "
        "AND no process-wide ASR veto"
    )
    caps = payload.get("capabilities") or []
    channels = sorted({row["channel"] for row in caps})
    public = sum(1 for row in caps if row.get("gate") == "public")
    auth_gated = sum(1 for row in caps if row.get("gate") == "consent")
    quota_gated = sum(1 for row in caps if row.get("gate") == "quota")
    lines.append(
        f"  Discoverable: {len(caps)} action(s) across {len(channels)} channel(s): "
        f"{len(caps) - quota_gated} read-only forwarded ({public} public, "
        f"{auth_gated} need --allow-authenticated)"
    )
    lines.append(
        f"  Quota-gated: {quota_gated} transcription action(s) — need --allow-quota-consuming "
        "AND --allow-authenticated; blocked by default"
    )
    lines.append("")
    if caps:
        width = max(len(row["channel"]) for row in caps)
        awidth = max(len(row["action"]) for row in caps)
        for row in caps:
            gate = row.get("gate") or ("public" if row["public"] else "consent")
            marker = {
                "public": "",
                "consent": "  [needs --allow-authenticated]",
                "quota": "  [needs --allow-quota-consuming + --allow-authenticated]",
            }.get(gate, "")
            backends = ", ".join(row.get("backends") or []) or "-"
            lines.append(
                f"  {row['channel']:<{width}}  {row['action']:<{awidth}}  "
                f"{row['mode']:<12} {backends}{marker}"
            )
        lines.append("")
    error = payload.get("error")
    if error:
        lines.append(f"  Error: {error.get('code')}: {error.get('message')}")
    lines.append("  Management verbs are never forwarded: setup, add, remove, login, logout,")
    lines.append("  browser, configure, update, uninstall, skill, doctor, check, version.")
    lines.append("")
    lines.append(_reach_text_parity(payload))
    return "\n".join(lines)


def cmd_reach(args: argparse.Namespace) -> int:
    """Capability inventory for the optional Agent Reach forwarding layer."""
    from .reach_backend import AgentReachBackend

    backend = AgentReachBackend(
        args.agent_reach,
        timeout=args.timeout,
        allow_authenticated=args.allow_authenticated,
        allow_quota_consuming=args.allow_quota_consuming,
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
    if prov.get("quota_consuming"):
        lines.append("  Quota:       paid/key-consuming call, run only with explicit consent")
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
    from .reach_backend import AgentReachBackend, ReachBackendError, asr_disabled

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
        # A gated quota action must not even read the registry before its gates
        # pass: that read is a subprocess.  execute() returns the precise gate
        # error (quota_required / auth_required / asr_disabled) before params.
        quota_preflight_blocked = (
            AgentReachBackend.is_quota_action(args.channel, args.action)
            and not (
                args.allow_quota_consuming
                and args.allow_authenticated
                and not asr_disabled()
            )
        )
        if not quota_preflight_blocked:
            try:
                registry = backend.registry()
                channel = registry.channels.get(args.channel)
                action = channel.actions.get(args.action) if channel else None
                if action is not None:
                    declared = [param.name for param in action.required_params]
            except ReachBackendError:
                declared = []
        extras = list(args.arguments)
        if quota_preflight_blocked:
            # Gate refusal wins over positional mapping; execute() reports it.
            pass
        elif declared:
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
        allow_quota_consuming=args.allow_quota_consuming,
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
            attribution = getattr(execution, "attribution", "")
            if attribution:
                print(f"Attribution: {attribution}")
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
        # Attribution travels with the JSON, not only the markdown: a lane fed
        # by the optional Agent Reach CLI is borrowed evidence, and a machine
        # consumer must be able to tell it apart from a native Trailhead hit.
        forwarded = [
            {"platform": c.platform, "attribution": c.attribution}
            for c in report.coverage
            if c.attribution
        ]
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
                            "attribution": c.attribution,
                        }
                        for c in report.coverage
                    ],
                    "attribution": {
                        "forwarded_lanes": forwarded,
                        "native_lanes": [
                            c.platform for c in report.coverage if not c.attribution
                        ],
                    },
                    "notable_count": len(report.notable),
                    "caveats_count": len(report.caveats),
                },
                indent=2,
            )
        )
        return 0
    print(path)
    return 0


# ── read: known-URL reading (native, public-only, no paid ASR) ──────────────
#
# Product gap (acceptance dimension 9): an agent must be able to hand Trailhead
# one URL it already has and get back evidence without a search query, without
# the optional Agent Reach CLI, and without a paid transcription call.  This
# command is a thin, honest presentation layer over the existing extractor
# (`extract_hits` → `extract_one`); it adds no new fetch connector.

READ_SCHEMA_VERSION = 1
READ_ASR_ENV = "TRAILHEAD_DISABLE_ASR"
READ_TIMEOUT_DEFAULT = 15.0
READ_TIMEOUT_MIN = 1.0
READ_TIMEOUT_MAX = 120.0
READ_MIN_USABLE_CHARS = 50
# `extract._html_to_readable_text` caps clean text here and appends "...".
_READ_READABLE_CAP_HINT = 20000

#: Fallback plan actually in force for this command.  Reported in the payload so
#: a consumer never has to guess which tiers were allowed.
_READ_POLICY: dict[str, str] = {
    "agent_reach": "not_used",
    "asr": "disabled",
    "hermes_web_extract": "disabled",
    "public_tiers": "direct/proxy HTTP, Jina Reader, native platform public APIs",
}


@contextmanager
def _asr_forced_off():
    """Force ``TRAILHEAD_DISABLE_ASR=1`` for the duration of one extraction.

    ``extract._ensure_asr_enabled`` reads the variable at call time, so both the
    YouTube and TikTok ASR tiers refuse before downloading media or contacting a
    transcription API.  The previous value is restored exactly, including the
    unset case, so `read` never changes process-wide behavior for later calls.
    """
    previous = os.environ.get(READ_ASR_ENV)
    os.environ[READ_ASR_ENV] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(READ_ASR_ENV, None)
        else:
            os.environ[READ_ASR_ENV] = previous


def _read_no_llm_extract(url: str, timeout: int = 15) -> str:
    """Disabled final tier: the model-backed Hermes ``web_extract`` subprocess.

    `read` must be deterministic and free: it never spawns ``hermes chat``.
    Raising here is caught by ``extract_one`` like any other failed tier and the
    result is reported honestly as an extraction failure rather than silently
    spending a model call.
    """
    raise RuntimeError(
        "read does not use the model-backed Hermes web_extract fallback; "
        "use 'search ... --execute --extract' when that tier is explicitly wanted"
    )


def _validate_read_url(raw: str) -> tuple[str, str]:
    """Return ``(normalized_url, error)``; error is ``""`` when valid.

    Only absolute ``http(s)`` URLs are accepted.  Whitespace, embedded
    credentials and malformed ports are rejected so a URL can never smuggle
    command/option text or leak a password into output.
    """
    url = (raw or "").strip()
    if not url:
        return "", "URL is required"
    if any(ch in url for ch in " \t\r\n"):
        return "", "URL must not contain whitespace or control characters"
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        embedded_credentials = bool(parsed.username or parsed.password)
        parsed.port  # property access validates the port
    except ValueError:
        # Never interpolate the parser's message: it can quote the input, and
        # the input can carry a password (``...:secret@host:bad/``).  A generic
        # message plus the redacted echo in ``_read_display_url`` is the whole
        # contract.
        return "", "URL could not be parsed; check the scheme, host, and port"
    if scheme not in ("http", "https"):
        return "", "URL must use http:// or https://"
    if not hostname:
        return "", "URL must include a host"
    if embedded_credentials:
        return "", "URL must not embed credentials"
    return url, ""


def _read_timeout_seconds(value: float) -> int:
    """Whole-second budget for the payload, safe for nan/inf/odd values.

    Validation rejects anything outside 1–120, but the payload still needs a
    number for the error report; NaN/Infinity must not raise before the stable
    JSON error is emitted.
    """
    try:
        if value != value or value in (float("inf"), float("-inf")):
            return 0
        return int(round(value))
    except (TypeError, ValueError, OverflowError):
        return 0


_READ_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/?#]*@"
)
# A scheme-less ``user:password@host/path`` input parses with an empty netloc,
# so ``urlparse`` never reports userinfo for it.  Match that leading shape.
_READ_SCHEMELESS_USERINFO_RE = re.compile(r"^[^/?#\s]*@")


def _strip_read_url_credentials(text: str) -> str:
    """Textually drop ``user:password@`` from a URL-shaped prefix.

    Used when :func:`urlparse` refuses the input, and as a final pass on the
    echoed value.  The authority segment is matched greedily so a password
    containing ``@`` is removed whole instead of leaving its tail behind.
    """
    stripped = _READ_URL_USERINFO_RE.sub(r"\g<scheme>", text)
    return _READ_SCHEMELESS_USERINFO_RE.sub("", stripped)


def _read_display_url(raw: str) -> str:
    """The input with any embedded credentials removed, for error output.

    A rejected URL is echoed back so the caller can see what failed, but a
    password in it must never reach stdout, stderr or an agent transcript.
    Parsing failures are the dangerous case: the parser raises *because* the
    authority is malformed, so a parsed rebuild is impossible and the raw
    string is never returned when it could hold userinfo.
    """
    url = (raw or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        port = parsed.port
        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname
    except ValueError:
        redacted = _strip_read_url_credentials(url)
        if redacted == url and "@" in url:
            # Something credential-shaped survived textual stripping; echo
            # nothing at all rather than risk a secret.
            return "[unparseable URL]"
        return redacted
    if username or password:
        host = hostname or ""
        if port is not None:
            host += f":{port}"
        url = parsed._replace(netloc=host).geturl()
    # A scheme-less ``user:password@host`` form parses with no netloc and no
    # userinfo, so strip it textually before echoing.
    return _strip_read_url_credentials(url)


def _read_base_payload(url: str, timeout_seconds: int, *, error_code: str = "", error_message: str = "") -> dict:
    """The complete, stable JSON shape shared by every `read` outcome."""
    return {
        "command": "read",
        "schema_version": READ_SCHEMA_VERSION,
        "ok": False,
        "url": url,
        "source_type": "",
        "timeout_seconds": timeout_seconds,
        "asr": {
            "enabled": False,
            "env": READ_ASR_ENV,
            "note": "read never invokes paid ASR",
        },
        "policy": dict(_READ_POLICY),
        "extraction_status": "not_attempted",
        "content_length": 0,
        "returned_chars": 0,
        "truncated": False,
        "truncation_note": "",
        "content": "",
        "error": (
            {"code": error_code, "message": error_message} if error_code else None
        ),
        "evidence": {
            "usable": False,
            "transport_ok": False,
            "relevance": "unknown",
            "reasons": [],
            "source_quality": None,
        },
        "video_evidence": None,
    }


def _read_text(payload: dict) -> str:
    """Human-readable rendering of the same facts the JSON carries."""
    quality = payload["evidence"].get("source_quality") or {}
    quality_text = quality.get("quality") or "unscored"
    if "score" in quality:
        quality_text += f" ({quality['score']}/100)"
    lines = [
        f"URL: {payload['url'] or '(none)'}",
        (
            f"Status: {payload['extraction_status']} | "
            f"source type: {payload['source_type'] or 'unknown'} | "
            f"timeout: {payload['timeout_seconds']}s"
        ),
        (
            f"Evidence: usable={'yes' if payload['evidence']['usable'] else 'no'} | "
            f"quality: {quality_text} | relevance: {payload['evidence']['relevance']}"
        ),
        (
            f"Content: {payload['returned_chars']} chars returned of "
            f"{payload['content_length']} measured"
            + (f" — {payload['truncation_note']}" if payload["truncated"] else "")
        ),
        "ASR: disabled — read never invokes paid transcription",
        "Fallbacks: agent-reach not used | hermes web_extract disabled",
    ]
    reasons = payload["evidence"].get("reasons") or []
    if reasons:
        lines.append("Reasons: " + "; ".join(reasons))
    video = payload.get("video_evidence")
    if video:
        lines.append(
            "Transcript: caption={} | caption_transcript={} | audio={}".format(
                video.get("caption_status", "not_attempted"),
                video.get("caption_transcript_status", "not_attempted"),
                video.get("audio_transcript_status", "not_configured"),
            )
        )
    error = payload.get("error")
    if error:
        lines.append(f"Error: {error['code']}: {error['message']}")
    if payload["ok"] and payload["content"]:
        lines.extend(["", payload["content"]])
    return "\n".join(lines)


def _emit_read(payload: dict, fmt: str, *, exit_code: int) -> int:
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif payload["ok"]:
        print(_read_text(payload))
    else:
        print(_read_text(payload), file=sys.stderr)
    return exit_code


def cmd_read(args: argparse.Namespace) -> int:
    """Read one known public URL and report usable evidence or a stable error."""
    timeout_seconds = _read_timeout_seconds(args.timeout)
    url, url_error = _validate_read_url(args.url)
    if url_error:
        payload = _read_base_payload(
            _read_display_url(args.url),
            timeout_seconds,
            error_code="invalid_url",
            error_message=url_error,
        )
        return _emit_read(payload, args.format, exit_code=2)
    if not (READ_TIMEOUT_MIN <= args.timeout <= READ_TIMEOUT_MAX):
        payload = _read_base_payload(
            url,
            timeout_seconds,
            error_code="invalid_timeout",
            error_message=(
                f"--timeout must be between {READ_TIMEOUT_MIN:g} and "
                f"{READ_TIMEOUT_MAX:g} seconds"
            ),
        )
        return _emit_read(payload, args.format, exit_code=2)

    try:
        with _asr_forced_off():
            extracted = extract_hits(
                (SearchHit(title="", url=url),),
                limit=1,
                timeout=timeout_seconds,
                extract=_read_no_llm_extract,
            )
    except Exception as exc:  # extraction is defensive, but never crash the CLI
        payload = _read_base_payload(
            url,
            timeout_seconds,
            error_code="internal_error",
            error_message=f"{type(exc).__name__}: {exc}",
        )
        return _emit_read(payload, args.format, exit_code=1)

    if not extracted:
        payload = _read_base_payload(
            url,
            timeout_seconds,
            error_code="internal_error",
            error_message="extractor returned no result for the URL",
        )
        return _emit_read(payload, args.format, exit_code=1)

    extracted_hit = extracted[0]
    result = extracted_hit.extraction
    scored = score_hit(ScoredHit.from_extracted_hit(extracted_hit))
    assessment = scored.assessment

    content = result.content or ""
    measured = int(result.content_length or 0)
    returned = len(content)
    cap_hit = len(content) >= _READ_READABLE_CAP_HINT and content.rstrip().endswith("...")
    truncated = measured > returned or cap_hit
    truncation_notes: list[str] = []
    if measured > returned:
        truncation_notes.append(
            f"extractor kept {returned} of {measured} measured characters"
        )
    if cap_hit:
        truncation_notes.append(
            "extractor hit its readable-text cap; the upstream page may continue"
        )

    substantial = max(measured, returned) > READ_MIN_USABLE_CHARS and bool(content.strip())
    usable = bool(result.status == "ok" and substantial and assessment.usable)
    reasons = list(assessment.reasons)
    if result.status == "ok" and not substantial:
        reasons.append(
            f"extracted text is {max(measured, returned)} chars; "
            f"usable evidence needs more than {READ_MIN_USABLE_CHARS}"
        )

    error_code = ""
    error_message = ""
    if result.status == "blocked":
        error_code = "extraction_blocked"
        error_message = result.error_message or "extraction was blocked"
    elif result.status == "error":
        error_code = "extraction_error"
        error_message = result.error_message or "extraction failed"
    elif result.status == "not_attempted":
        error_code = "extraction_not_attempted"
        error_message = result.error_message or "extraction was not attempted"
    elif not usable:
        error_code = "unusable_evidence"
        error_message = (
            result.error_message
            or "; ".join(reasons)
            or "extracted text is not usable evidence"
        )
    if "web_extract" in error_message:
        # The extractor's generic failure text names its last tier; `read`
        # disabled that tier, so say so instead of implying it was attempted.
        error_message += " (Hermes web_extract tier disabled for read)"

    # The base payload already carries command/schema/asr/policy defaults, so
    # success and failure can never drift apart in shape.
    payload = _read_base_payload(url, timeout_seconds)
    payload.update(
        {
            "ok": usable and not error_code,
            "source_type": result.source_type or "",
            "extraction_status": result.status,
            "content_length": measured,
            "returned_chars": returned,
            "truncated": truncated,
            "truncation_note": "; ".join(truncation_notes),
            "content": content,
            "error": (
                {"code": error_code, "message": error_message} if error_code else None
            ),
            "evidence": {
                "usable": usable,
                "transport_ok": assessment.transport_ok,
                "relevance": assessment.relevance,
                "reasons": reasons,
                "source_quality": scored.scoring.to_dict(),
            },
            "video_evidence": (
                result.video_evidence.to_dict()
                if result.video_evidence is not None
                else None
            ),
        }
    )
    return _emit_read(payload, args.format, exit_code=0 if payload["ok"] else 1)


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
            "authenticated with explicit consent), the pinned 40-action parity "
            "inventory, and why the rest are excluded. Paid transcription is listed "
            "but needs --allow-quota-consuming and --allow-authenticated, and "
            "TRAILHEAD_DISABLE_ASR=1 vetoes it. Discovery order: --agent-reach, "
            "TRAILHEAD_AGENT_REACH_BIN, PATH. Nothing is installed, configured, "
            "logged in to, or copied."
        ),
    )
    reach.add_argument("--agent-reach", metavar="PATH", help="Path to an installed agent-reach CLI")
    reach.add_argument("--timeout", type=float, default=30, help="Registry/diagnostic timeout in seconds")
    reach.add_argument("--allow-authenticated", action="store_true", help="Report modes as if authenticated forwarding were consented")
    reach.add_argument(
        "--allow-quota-consuming",
        action="store_true",
        help=(
            "Report the paid/key-consuming transcription actions as consented "
            "(they also need --allow-authenticated; TRAILHEAD_DISABLE_ASR=1 still vetoes)"
        ),
    )
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
            "passed explicitly. Paid transcription additionally needs "
            "--allow-quota-consuming plus --allow-authenticated and is vetoed by "
            "TRAILHEAD_DISABLE_ASR=1. Positional ARGS fill the action's required params "
            "in declared order; use --param NAME=VALUE for anything else."
        ),
    )
    reach_call.add_argument("channel", help="Channel name, e.g. github, v2ex, web")
    reach_call.add_argument("action", help="Read-only action, e.g. read, search, hot")
    reach_call.add_argument("arguments", nargs="*", help="Positional arguments for the action's required params")
    reach_call.add_argument("--param", action="append", metavar="NAME=VALUE", help="Action parameter (repeatable)")
    reach_call.add_argument("--limit", type=int, default=10, help="Max items returned (default: 10)")
    reach_call.add_argument("--timeout", type=float, default=30, help="Upstream timeout in seconds (default: 30)")
    reach_call.add_argument("--allow-authenticated", action="store_true", help="Consent to use the operator's existing Agent Reach login")
    reach_call.add_argument(
        "--allow-quota-consuming",
        action="store_true",
        help=(
            "Consent to a paid/key-consuming transcription (youtube/xiaoyuzhou "
            "transcribe); also requires --allow-authenticated and is vetoed by "
            "TRAILHEAD_DISABLE_ASR=1"
        ),
    )
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

    read_parser = sub.add_parser(
        "read",
        help="Read one known public URL as evidence (native, no Agent Reach, no paid ASR)",
        description=(
            "Read a single known http(s) URL with the native extractor and report "
            "whether the retrieved text is usable evidence. Works without an Agent "
            "Reach installation and never forwards to it. Paid ASR is force-disabled "
            "for this command (TRAILHEAD_DISABLE_ASR=1 for the extraction only) and "
            "the model-backed Hermes web_extract fallback is not used, so a read is "
            "deterministic and free. Success (usable evidence) exits 0; blocked, "
            "failed or unusable extraction exits 1; an invalid URL or timeout exits 2. "
            "The JSON payload always contains the same keys, with error.code one of "
            "invalid_url, invalid_timeout, extraction_blocked, extraction_error, "
            "extraction_not_attempted, unusable_evidence, internal_error."
        ),
    )
    read_parser.add_argument("url", help="Absolute http(s) URL to read")
    read_parser.add_argument("--format", choices=["text", "json"], default="text")
    read_parser.add_argument(
        "--timeout",
        type=float,
        default=READ_TIMEOUT_DEFAULT,
        metavar="SECONDS",
        help=(
            "Network timeout per extractor attempt, 1-120s (default: 15). "
            "The extractor's finite public tier ladder bounds total wall time."
        ),
    )
    read_parser.set_defaults(func=cmd_read)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
