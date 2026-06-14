from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from . import __version__
from .channels import CHANNELS, Channel, CheckResult, check_all, get_channel
from .router import all_routes, route_for


STATUS_ORDER = {"fail": 0, "warn": 1, "off": 2, "ok": 3}
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


def _icon(status: str) -> str:
    return {"ok": "✅", "warn": "⚠️", "off": "⬜", "fail": "❌"}.get(status, "❔")


def _row_dict(ch: Channel, res: CheckResult) -> dict:
    data = ch.base_dict()
    data["result"] = res.to_dict()
    data["status"] = res.status
    data["detail"] = res.detail
    data["action"] = res.action
    return data


def _filter_rows(rows: list[tuple[Channel, CheckResult]], *, only: str | None = None, risk: str | None = None, channel: str | None = None, tag: str | None = None) -> list[tuple[Channel, CheckResult]]:
    out = rows
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        out = [(ch, res) for ch, res in out if res.status in wanted]
    if risk:
        wanted_risk = {s.strip() for s in risk.split(",") if s.strip()}
        out = [(ch, res) for ch, res in out if ch.risk in wanted_risk]
    if channel:
        wanted_channel = {s.strip() for s in channel.split(",") if s.strip()}
        out = [(ch, res) for ch, res in out if ch.key in wanted_channel]
    if tag:
        wanted_tag = {s.strip() for s in tag.split(",") if s.strip()}
        out = [(ch, res) for ch, res in out if wanted_tag.intersection(ch.tags)]
    return out


def _summary(rows: list[tuple[Channel, CheckResult]]) -> dict[str, int]:
    counts = {"ok": 0, "warn": 0, "off": 0, "fail": 0}
    for _, res in rows:
        counts[res.status] = counts.get(res.status, 0) + 1
    return counts


def _exit_code(rows: list[tuple[Channel, CheckResult]], strict: bool = False) -> int:
    if any(res.status == "fail" for _, res in rows):
        return 2
    if strict and any(res.status in {"warn", "off"} for _, res in rows):
        return 1
    if any(ch.required and res.status in {"warn", "off"} for ch, res in rows):
        return 1
    return 0


def _print_json(rows: list[tuple[Channel, CheckResult]]) -> None:
    print(json.dumps({"summary": _summary(rows), "channels": [_row_dict(ch, res) for ch, res in rows]}, indent=2))


def _print_markdown(rows: list[tuple[Channel, CheckResult]], title: str = "Hermes Reach doctor") -> None:
    counts = _summary(rows)
    print(f"# {title}\n")
    print(f"Summary: ✅ {counts['ok']} · ⚠️ {counts['warn']} · ⬜ {counts['off']} · ❌ {counts['fail']}\n")
    for ch, res in rows:
        print(f"## {_icon(res.status)} {ch.title} (`{ch.key}`)\n")
        print(f"- **Status:** {res.status}")
        print(f"- **Risk:** {ch.risk}")
        print(f"- **Default path:** {ch.default_path}")
        print(f"- **Purpose:** {ch.purpose}")
        print(f"- **Observed:** {res.detail}")
        if res.action:
            print(f"- **Next action:** {res.action}")
        print(f"- **Approval required:** {'yes' if (ch.approval_required or res.approval_required) else 'no'}")
        if res.evidence:
            print("- **Evidence:**")
            for ev in res.evidence:
                bits = [ev.source]
                if ev.command:
                    bits.append(f"cmd=`{ev.command}`")
                if ev.path:
                    bits.append(f"path=`{ev.path}`")
                if ev.return_code is not None:
                    bits.append(f"rc={ev.return_code}")
                print(f"  - {'; '.join(bits)} — {ev.detail}")
        print()


def _print_text(rows: list[tuple[Channel, CheckResult]], title: str = "Hermes Reach doctor") -> None:
    counts = _summary(rows)
    print(f"{title} v{__version__}")
    print(f"Summary: ok={counts['ok']} warn={counts['warn']} off={counts['off']} fail={counts['fail']}\n")
    for ch, res in rows:
        approval = " approval-required" if (ch.approval_required or res.approval_required) else ""
        print(f"{_icon(res.status)} {ch.key:16} {ch.title}{approval}")
        print(f"   path: {ch.default_path}")
        print(f"   risk: {ch.risk} · purpose: {ch.purpose}")
        print(f"   {res.detail}")
        if res.action:
            print(f"   action: {res.action}")
        if res.evidence:
            ev = res.evidence[0]
            trail = f"source={ev.source}"
            if ev.command:
                trail += f" cmd={ev.command!r}"
            if ev.path:
                trail += f" path={ev.path}"
            if ev.return_code is not None:
                trail += f" rc={ev.return_code}"
            print(f"   evidence: {trail}")
        print()


def _emit(rows: list[tuple[Channel, CheckResult]], fmt: str, title: str = "Hermes Reach doctor") -> None:
    if fmt == "json":
        _print_json(rows)
    elif fmt == "markdown":
        _print_markdown(rows, title=title)
    else:
        _print_text(rows, title=title)


def cmd_doctor(args: argparse.Namespace) -> int:
    rows = _filter_rows(check_all(), only=args.only, risk=args.risk, channel=args.channel, tag=args.tag)
    _emit(rows, args.format, title="Hermes Reach doctor")
    return _exit_code(rows, strict=args.strict)


def cmd_queue(args: argparse.Namespace) -> int:
    rows = _filter_rows(check_all(), only=args.only, risk=args.risk, channel=args.channel, tag=args.tag)
    rows = sorted(rows, key=lambda pair: (STATUS_ORDER.get(pair[1].status, 99), RISK_ORDER.get(pair[0].risk, 99), pair[0].key))
    if not args.all:
        rows = [(ch, res) for ch, res in rows if res.status != "ok"]
    if args.top:
        rows = rows[: args.top]
    if args.format == "json":
        _print_json(rows)
    elif args.format == "markdown":
        _print_markdown(rows, title="Hermes Reach queue")
    else:
        print("Hermes Reach queue\n")
        if not rows:
            print("No actionable channel gaps. All checks are green.")
        for i, (ch, res) in enumerate(rows, start=1):
            print(f"{i}. {_icon(res.status)} {ch.title} [{ch.key}] — {res.status}, risk={ch.risk}")
            print(f"   Why: {res.detail}")
            next_action = res.action or "; ".join(ch.setup_plan)
            print(f"   Next: {next_action}")
            if ch.approval_required or res.approval_required:
                print("   Approval: required before mutation")
            print()
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        ch = get_channel(args.channel)
    except KeyError:
        print(f"Unknown channel: {args.channel}", file=sys.stderr)
        print("Known channels: " + ", ".join(c.key for c in CHANNELS), file=sys.stderr)
        return 2
    res = ch.check()
    print(f"# Setup / usage plan: {ch.title} ({ch.key})\n")
    print(f"Current status: {_icon(res.status)} {res.status}")
    print(f"Current path: {ch.default_path}")
    print(f"Risk: {ch.risk}")
    print(f"Purpose: {ch.purpose}")
    print(f"Observed: {res.detail}")
    if res.action:
        print(f"Immediate action: {res.action}")
    print("\nSteps:")
    for i, step in enumerate(ch.setup_plan, start=1):
        print(f"{i}. {step}")
    if ch.approval_required or res.approval_required or ch.risk == "high":
        print("\nGuardrail: this channel may involve cookies, credentials, paid APIs, posting, or global installs. Explicit approval is required before mutating setup.")
    return 0


def cmd_capability_radar(args: argparse.Namespace) -> int:
    rows_by_key = {ch.key: (ch, res) for ch, res in check_all()}
    keys = ["hermes-upstream", "docs-watcher", "newsletter", "x-search", "agent-reach"]
    rows = [rows_by_key[k] for k in keys if k in rows_by_key]
    if args.format == "json":
        _print_json(rows)
    else:
        print("# Hermes Capability Radar\n")
        for ch, res in rows:
            print(f"- **{ch.title}:** {_icon(res.status)} {res.detail}")
            if res.action:
                print(f"  - Action: {res.action}")
    return 0


def cmd_agent_brief(args: argparse.Namespace) -> int:
    rows = check_all()
    by_key = {ch.key: (ch, res) for ch, res in rows}
    brief = {
        "use_first": {
            "current_facts": "web_search",
            "page_or_pdf_extraction": "web_extract",
            "github": "GitHub MCP first, gh CLI only when terminal/git integration is needed",
            "x_or_social_current_discussion": "x_search if credentialed; Nitter fallback; no cookie auth without approval",
            "reddit_practitioner_threads": "Redlib/reddit-search first; browser/cookie auth requires approval",
            "hermes_docs_drift": "hermes-upstream-opportunity-watch plus git fetch/log/diff",
        },
        "approval_required": [ch.key for ch, res in rows if ch.approval_required or res.approval_required],
        "warnings": [{"key": ch.key, "status": res.status, "detail": res.detail, "action": res.action} for ch, res in rows if res.status != "ok"],
        "capability_radar": {key: by_key[key][1].detail for key in ["hermes-upstream", "docs-watcher", "newsletter"] if key in by_key},
    }
    if args.format == "json":
        print(json.dumps(brief, indent=2))
    else:
        print("# Hermes Reach agent brief\n")
        print("Use this routing map before installing external internet tooling.\n")
        print("## Preferred paths\n")
        for label, path in brief["use_first"].items():
            print(f"- **{label.replace('_', ' ').title()}:** {path}")
        print("\n## Approval-required channels\n")
        for key in brief["approval_required"]:
            print(f"- {key}")
        print("\n## Current warnings\n")
        for item in brief["warnings"]:
            print(f"- **{item['key']}** ({item['status']}): {item['detail']}")
            if item["action"]:
                print(f"  - Action: {item['action']}")
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    routes = all_routes()
    if args.format == "json":
        print(json.dumps({"routes": [route.to_dict() for route in routes]}, indent=2))
        return 0
    print("# Hermes Reach task routes\n")
    for route in routes:
        print(f"## {route.key}: {route.task}\n")
        print(f"- **Primary:** {route.primary}")
        print(f"- **Fallbacks:** {', '.join(route.fallbacks)}")
        print(f"- **Avoid:** {', '.join(route.avoid)}")
        print(f"- **Approval required:** {'yes' if route.approval_required else 'no'}")
        print(f"- **Why:** {route.rationale}")
        print(f"- **Evidence needed:** {', '.join(route.evidence_needed)}")
        print(f"- **Competitor lesson:** {route.competitor_lesson}\n")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    route = route_for(args.intent)
    if args.format == "json":
        print(json.dumps(route.to_dict(), indent=2))
        return 0
    print(f"# Hermes Reach route: {route.key}\n")
    print(f"Task: {route.task}")
    print(f"Primary: {route.primary}")
    print(f"Fallbacks: {', '.join(route.fallbacks)}")
    print(f"Avoid: {', '.join(route.avoid)}")
    print(f"Approval required: {'yes' if route.approval_required else 'no'}")
    print(f"Why: {route.rationale}")
    print("\nEvidence required before claiming success:")
    for item in route.evidence_needed:
        print(f"- {item}")
    print(f"\nCompetitor lesson: {route.competitor_lesson}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-reach", description="Help Hermes search/read hard-to-reach internet sources")
    parser.add_argument("--version", action="version", version=f"hermes-reach {__version__}")
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

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
