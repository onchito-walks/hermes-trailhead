"""Formatters for SourceScout output: text, markdown, JSON."""
from __future__ import annotations

import json
import sys

from . import __version__
from .channels import Channel, CheckResult

STATUS_ORDER = {"fail": 0, "warn": 1, "off": 2, "ok": 3}
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


def icon(status: str) -> str:
    return {"ok": "✅", "warn": "⚠️", "off": "⬜", "fail": "❌"}.get(status, "❔")


def row_dict(ch: Channel, res: CheckResult) -> dict:
    data = ch.base_dict()
    data["result"] = res.to_dict()
    data["status"] = res.status
    data["detail"] = res.detail
    data["action"] = res.action
    return data


def filter_rows(
    rows: list[tuple[Channel, CheckResult]],
    *,
    only: str | None = None,
    risk: str | None = None,
    channel: str | None = None,
    tag: str | None = None,
) -> list[tuple[Channel, CheckResult]]:
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


def summary(rows: list[tuple[Channel, CheckResult]]) -> dict[str, int]:
    counts = {"ok": 0, "warn": 0, "off": 0, "fail": 0}
    for _, res in rows:
        counts[res.status] = counts.get(res.status, 0) + 1
    return counts


def exit_code(rows: list[tuple[Channel, CheckResult]], strict: bool = False) -> int:
    if any(res.status == "fail" for _, res in rows):
        return 2
    if strict and any(res.status in {"warn", "off"} for _, res in rows):
        return 1
    if any(ch.required and res.status in {"warn", "off"} for ch, res in rows):
        return 1
    return 0


def format_json(rows: list[tuple[Channel, CheckResult]]) -> str:
    return json.dumps(
        {"summary": summary(rows), "channels": [row_dict(ch, res) for ch, res in rows]},
        indent=2,
    )


def format_markdown(rows: list[tuple[Channel, CheckResult]], title: str = "SourceScout doctor") -> str:
    counts = summary(rows)
    lines = [f"# {title}", ""]
    lines.append(f"Summary: ✅ {counts['ok']} · ⚠️ {counts['warn']} · ⬜ {counts['off']} · ❌ {counts['fail']}")
    lines.append("")
    for ch, res in rows:
        lines.append(f"## {icon(res.status)} {ch.title} (`{ch.key}`)")
        lines.append("")
        lines.append(f"- **Status:** {res.status}")
        lines.append(f"- **Risk:** {ch.risk}")
        lines.append(f"- **Default path:** {ch.default_path}")
        lines.append(f"- **Purpose:** {ch.purpose}")
        lines.append(f"- **Observed:** {res.detail}")
        if res.action:
            lines.append(f"- **Next action:** {res.action}")
        lines.append(f"- **Approval required:** {'yes' if (ch.approval_required or res.approval_required) else 'no'}")
        if res.evidence:
            lines.append("- **Evidence:**")
            for ev in res.evidence:
                d = ev.to_dict()
                bits = [d.get("source", "?")]
                cmd = d.get("command") or d.get("url", "")
                if cmd:
                    bits.append(f"cmd=`{cmd}`")
                path = d.get("path", "")
                if path:
                    bits.append(f"path=`{path}`")
                rc = d.get("return_code") or d.get("status_code")
                if rc is not None:
                    bits.append(f"rc={rc}")
                lines.append(f"  - {'; '.join(bits)} — {ev.detail}")
        lines.append("")
    return "\n".join(lines)


def format_text(rows: list[tuple[Channel, CheckResult]], title: str = "SourceScout doctor") -> str:
    counts = summary(rows)
    lines = [
        f"{title} v{__version__}",
        f"Summary: ok={counts['ok']} warn={counts['warn']} off={counts['off']} fail={counts['fail']}",
        "",
    ]
    for ch, res in rows:
        approval = " approval-required" if (ch.approval_required or res.approval_required) else ""
        lines.append(f"{icon(res.status)} {ch.key:16} {ch.title}{approval}")
        lines.append(f"   path: {ch.default_path}")
        lines.append(f"   risk: {ch.risk} · purpose: {ch.purpose}")
        lines.append(f"   {res.detail}")
        if res.action:
            lines.append(f"   action: {res.action}")
        if res.evidence:
            ev = res.evidence[0]
            d = ev.to_dict()
            trail = f"source={d.get('source', '?')}"
            cmd = d.get("command") or d.get("url", "")
            if cmd:
                trail += f" cmd={cmd!r}"
            path = d.get("path", "")
            if path:
                trail += f" path={path}"
            rc = d.get("return_code") or d.get("status_code")
            if rc is not None:
                trail += f" rc={rc}"
            lines.append(f"   evidence: {trail}")
        lines.append("")
    return "\n".join(lines)


def emit(rows: list[tuple[Channel, CheckResult]], fmt: str, title: str = "SourceScout doctor") -> str:
    if fmt == "json":
        return format_json(rows)
    elif fmt == "markdown":
        return format_markdown(rows, title=title)
    else:
        return format_text(rows, title=title)


def format_queue_text(rows: list[tuple[Channel, CheckResult]]) -> str:
    lines = ["SourceScout queue", ""]
    if not rows:
        lines.append("No actionable channel gaps. All checks are green.")
        return "\n".join(lines)
    for i, (ch, res) in enumerate(rows, start=1):
        lines.append(f"{i}. {icon(res.status)} {ch.title} [{ch.key}] — {res.status}, risk={ch.risk}")
        lines.append(f"   Why: {res.detail}")
        next_action = res.action or "; ".join(ch.setup_plan)
        lines.append(f"   Next: {next_action}")
        if ch.approval_required or res.approval_required:
            lines.append("   Approval: required before mutation")
        lines.append("")
    return "\n".join(lines)


def format_plan_text(ch: Channel, res: CheckResult) -> str:
    lines = [f"# Setup / usage plan: {ch.title} ({ch.key})", ""]
    lines.append(f"Current status: {icon(res.status)} {res.status}")
    lines.append(f"Current path: {ch.default_path}")
    lines.append(f"Risk: {ch.risk}")
    lines.append(f"Purpose: {ch.purpose}")
    lines.append(f"Observed: {res.detail}")
    if res.action:
        lines.append(f"Immediate action: {res.action}")
    lines.append("")
    lines.append("Steps:")
    for i, step in enumerate(ch.setup_plan, start=1):
        lines.append(f"{i}. {step}")
    if ch.approval_required or res.approval_required or ch.risk == "high":
        lines.append("")
        lines.append("Guardrail: this channel may involve cookies, credentials, paid APIs, posting, or global installs. Explicit approval is required before mutating setup.")
    return "\n".join(lines)


def format_brief_json(rows: list[tuple[Channel, CheckResult]], radar_keys: list[str]) -> str:
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
        "capability_radar": {key: by_key[key][1].detail for key in radar_keys if key in by_key},
    }
    return json.dumps(brief, indent=2)


def format_brief_text(rows: list[tuple[Channel, CheckResult]], radar_keys: list[str]) -> str:
    by_key = {ch.key: (ch, res) for ch, res in rows}
    lines = ["# SourceScout agent brief", "", "Use this routing map before installing external internet tooling.", ""]
    lines.append("## Preferred paths")
    lines.append("")
    paths = {
        "current_facts": "web_search",
        "page_or_pdf_extraction": "web_extract",
        "github": "GitHub MCP first, gh CLI only when terminal/git integration is needed",
        "x_or_social_current_discussion": "x_search if credentialed; Nitter fallback; no cookie auth without approval",
        "reddit_practitioner_threads": "Redlib/reddit-search first; browser/cookie auth requires approval",
        "hermes_docs_drift": "hermes-upstream-opportunity-watch plus git fetch/log/diff",
    }
    for label, path in paths.items():
        lines.append(f"- **{label.replace('_', ' ').title()}:** {path}")
    lines.append("")
    lines.append("## Approval-required channels")
    lines.append("")
    for ch, res in rows:
        if ch.approval_required or res.approval_required:
            lines.append(f"- {ch.key}")
    lines.append("")
    lines.append("## Current warnings")
    lines.append("")
    for ch, res in rows:
        if res.status != "ok":
            lines.append(f"- **{ch.key}** ({res.status}): {res.detail}")
            if res.action:
                lines.append(f"  - Action: {res.action}")
    return "\n".join(lines)


def format_routes_json(routes) -> str:
    return json.dumps({"routes": [r.to_dict() for r in routes]}, indent=2)


def format_routes_text(routes) -> str:
    lines = ["# SourceScout task routes", ""]
    for route in routes:
        lines.append(f"## {route.key}: {route.task}")
        lines.append("")
        lines.append(f"- **Primary:** {route.primary}")
        lines.append(f"- **Fallbacks:** {', '.join(route.fallbacks)}")
        lines.append(f"- **Avoid:** {', '.join(route.avoid)}")
        lines.append(f"- **Approval required:** {'yes' if route.approval_required else 'no'}")
        lines.append(f"- **Why:** {route.rationale}")
        lines.append(f"- **Evidence needed:** {', '.join(route.evidence_needed)}")
        lines.append(f"- **Competitor lesson:** {route.competitor_lesson}")
        lines.append("")
    return "\n".join(lines)


def format_route_json(route) -> str:
    return json.dumps(route.to_dict(), indent=2)


def format_route_text(route) -> str:
    lines = [f"# SourceScout route: {route.key}", ""]
    lines.append(f"Task: {route.task}")
    lines.append(f"Primary: {route.primary}")
    lines.append(f"Fallbacks: {', '.join(route.fallbacks)}")
    lines.append(f"Avoid: {', '.join(route.avoid)}")
    lines.append(f"Approval required: {'yes' if route.approval_required else 'no'}")
    lines.append(f"Why: {route.rationale}")
    lines.append("")
    lines.append("Evidence required before claiming success:")
    for item in route.evidence_needed:
        lines.append(f"- {item}")
    lines.append(f"\nCompetitor lesson: {route.competitor_lesson}")
    return "\n".join(lines)


def format_radar_text(rows: list[tuple[Channel, CheckResult]]) -> str:
    lines = ["# Hermes Capability Radar", ""]
    for ch, res in rows:
        lines.append(f"- **{ch.title}:** {icon(res.status)} {res.detail}")
        if res.action:
            lines.append(f"  - Action: {res.action}")
    return "\n".join(lines)
