#!/usr/bin/env python3
"""Full 40-action public sweep with artifact-unit evaluation.

What this script is
-------------------
A *harness* for the pinned Agent Reach 1.6.0 action surface. It does not score,
rank, or grade, and it makes no superiority claim. It:

1. Freezes, **before any call**, a manifest of what each action's artifact is
   supposed to contain. The requested outcome is taken from the pinned
   upstream registry help text (``agent-reach channels``), not invented here;
   the units are structural (identity, URL, body text, structured fields, a
   shell-page check) and never a character threshold.
2. Builds the full 40-row ledger from ``reach_backend.PARITY_ACTIONS``. The 26
   ``public`` rows are executed with no auth consent, no quota consent, an
   empty throwaway HOME, forced public routes, and ``TRAILHEAD_DISABLE_ASR=1``.
   The 12 ``consent`` and 2 ``quota`` rows are **gated_not_run**: their gate is
   exercised with a spy runner and the run is refused before an action process
   exists (the spy proves zero action spawns).
3. Inspects the *actual* returned artifact per row: body text vs title/metadata
   vs structured ``raw`` fields, a frozen error-shell marker scan over the first
   400 characters of body text, truncation flags, and the documented output
   caps. A returned-item count never satisfies a unit.
4. Records, per row, what is *known* (item counts, body character counts,
   truncation flags, backend route) and what is *unknown* (matches beyond the
   requested limit, end of page/topic/reply set, comment/transcript
   completeness). ``whole_artifact_proven`` stays ``false`` unless a
   continuation state were known to be exhausted; no such proof exists here.
5. Preserves upstream errors verbatim (code, upstream code, message, attempts,
   timeout flag) instead of reclassifying them as absences.
6. Keeps raw payloads in the scratch directory and writes one sanitized,
   machine-readable record. Absolute host paths never enter the record.

What this script is NOT
-----------------------
- Not a performance, reliability, freshness, or cross-tool comparison.
- Not authenticated, not paid, not ASR: ``allow_authenticated`` and
  ``allow_quota_consuming`` are always ``False`` and no account/session
  material is read or imported. The 12 consent rows and 2 quota rows are
  recorded as not run, not as failures and not as passes.
- Not a completeness proof. Marker presence is not "the complete artifact".

Usage
-----
    python3 scripts/evaluate_action_artifacts.py \
        --agent-reach /path/to/pinned/venv/bin/agent-reach \
        --scratch /path/to/scratch/action-artifacts \
        --out docs/evidence/action-artifacts-live.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_trailhead.reach_backend import (  # noqa: E402
    AgentReachBackend,
    PARITY_ACTIONS,
    PINNED_UPSTREAM,
    asr_disabled,
    parity_inventory,
    redact_secrets,
    validate_parity_inventory,
)

SCHEMA = "trailhead.action-artifacts/1"
MANIFEST_VERSION = 1

#: The documented forwarding bound in ``reach_backend`` (MAX_TEXT_CHARS). An
#: artifact at this length was clipped by Trailhead, not by the page.
MAX_TEXT_CHARS = 4000

#: Frozen generic "this is an error/anti-bot/empty shell page, not the
#: requested artifact" markers. Deliberately multilingual and generic; each
#: match is reported with its snippet so a reviewer can reject a false
#: positive. Only the first SHELL_WINDOW characters of body text are scanned.
SHELL_MARKERS: tuple[str, ...] = (
    "you've been blocked by network security",
    "blocked by network security",
    "access denied",
    "page not found",
    "page could not be found",
    "not found",
    "404",
    "页面不存在",
    "你访问的页面不见了",
    "页面已被删除",
    "لم يتم العثور على الصفحة",
    "siden blev ikke fundet",
    "seite nicht gefunden",
    "ページが見つかりません",
    "sign in to continue",
    "log in to continue",
    "verify you are human",
    "captcha",
)
SHELL_WINDOW = 400

#: Targets frozen from the prior action-sweep raw record
#: (``trailhead-40-action-live.json``, 2026-10-28T12:31Z). They are reused
#: verbatim so a failure this run is comparable to that record; none is
#: invented for this run.
TARGET_ORIGIN = "prior action-sweep raw (2026-10-28T12:31Z)"
FROZEN_TARGETS: dict[tuple[str, str], dict[str, Any]] = {
    ("github", "search"): {"query": "Panniantong Agent-Reach", "limit": 2},
    ("github", "read"): {"target": "Panniantong/Agent-Reach"},
    ("twitter", "search"): {"query": "NousResearch Hermes", "limit": 2},
    ("youtube", "read"): {"target": "https://www.youtube.com/watch?v=jNQXAC9IVRw"},
    ("youtube", "search"): {"query": "Python asyncio tutorial", "limit": 2},
    ("youtube", "subtitle"): {"target": "https://www.youtube.com/watch?v=jNQXAC9IVRw"},
    ("reddit", "search"): {"query": "Python asyncio", "limit": 2},
    ("reddit", "read"): {
        "target": "https://www.reddit.com/r/Python/comments/1aqm0ht/"
                  "handling_tasks_in_asyncio_like_a_pro_jacob_padilla/"
    },
    ("facebook", "search"): {"query": "Python programming", "limit": 2},
    ("bilibili", "search"): {"query": "Python 异步编程", "limit": 2},
    ("bilibili", "read"): {"target": "https://www.bilibili.com/video/BV1chxT6xEyo"},
    ("bilibili", "hot"): {"limit": 2},
    ("xiaohongshu", "search"): {"query": "咖啡", "limit": 2},
    ("xiaohongshu", "read"): {"target": "https://xhslink.com/m/AJp68XgYriT"},
    ("linkedin", "jobs"): {"query": "Python developer", "limit": 2},
    ("linkedin", "read"): {
        "target": "https://www.linkedin.com/jobs/view/"
                  "senior-python-developer-remote-at-hired-4447811252"
    },
    ("boss", "search"): {"query": "Python", "limit": 2},
    ("boss", "read"): {
        "target": "https://www.zhipin.com/job_detail/"
                  "c1039e39ba83b73e0nd639i_FFJR.html?_security_check=1_1783322651289"
    },
    ("v2ex", "hot"): {"limit": 2},
    ("v2ex", "node"): {"node_name": "python", "limit": 2},
    ("v2ex", "read"): {"target": "https://www.v2ex.com/t/1252479"},
    ("v2ex", "user"): {"username": "Livid"},
    ("xueqiu", "quote"): {"symbol": "SH600519"},
    ("xueqiu", "search"): {"query": "茅台", "limit": 2},
    ("web", "search"): {"query": "Python asyncio documentation", "limit": 2},
    ("web", "read"): {"target": "https://docs.python.org/3/library/asyncio.html"},
}


# ── frozen artifact units ────────────────────────────────────────────────────
# Requested outcomes below are paraphrases of the pinned registry's own help
# text for each action (``agent-reach channels``), so a unit is what the action
# promises, not what one earlier response happened to contain.


def _list_units(*, snippet: bool = False, raw: Iterable[str] = ()) -> list[dict]:
    units: list[dict] = [
        {"id": "item_list", "kind": "items_min", "min": 1, "required": True},
        {"id": "item_identity", "kind": "item_field_all", "field": "title", "required": True},
        {"id": "item_url", "kind": "item_field_all", "field": "url", "required": True},
    ]
    if snippet:
        units.append({"id": "snippet_text", "kind": "body_text", "required": False})
    if tuple(raw):
        units.append(
            {"id": "structured_fields", "kind": "raw_fields", "fields": list(raw), "required": True}
        )
    return units


def _read_units(
    *,
    target: bool = True,
    author: bool = False,
    body_required: bool = True,
    raw: Iterable[str] = (),
) -> list[dict]:
    units: list[dict] = []
    if target:
        units.append({"id": "requested_target", "kind": "target_match", "required": True})
    units.append({"id": "item_identity", "kind": "item_field_all", "field": "title", "required": True})
    if author:
        units.append(
            {"id": "author_or_uploader", "kind": "item_field_all", "field": "author", "required": True}
        )
    units.append({"id": "body_text", "kind": "body_text", "required": body_required})
    units.append({"id": "body_not_error_shell", "kind": "no_shell_marker", "required": True})
    if tuple(raw):
        units.append(
            {"id": "structured_fields", "kind": "raw_fields", "fields": list(raw), "required": True}
        )
    return units


def _spec(outcome: str, units: list[dict], *, whole: bool, scope: str,
          unknown: list[str], caps: dict | None = None) -> dict:
    return {
        "requested_outcome": outcome,
        "units": units,
        "whole_artifact": whole,
        "scope": scope,
        "unknown": list(unknown),
        "caps": dict(caps or {}),
    }


_BOUNDED = ["matches_beyond_requested_limit_not_known"]
_WHOLE = ["end_of_artifact_not_proven", "omitted_sections_not_inspected"]

ACTION_SPECS: dict[tuple[str, str], dict] = {
    # github
    ("github", "search"): _spec(
        "Search repositories: up to 2 repository hits, each with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("github", "read"): _spec(
        "Read a repository (with README): repo-root target, so README text plus repository metadata",
        _read_units(raw=("license",)), whole=True, scope="whole_artifact",
        unknown=["readme_end_not_proven", "issue_or_pr_comments_not_requested_for_repo_root"]),
    # twitter
    ("twitter", "search"): _spec(
        "Search tweets: up to 2 tweet hits, each with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("twitter", "profile"): _spec(
        "A user's profile: profile fields for one account",
        _list_units(), whole=True, scope="whole_artifact", unknown=["profile_fields_not_assessed"]),
    ("twitter", "tweets"): _spec(
        "A user's recent tweets: up to 2 tweet rows",
        _list_units(), whole=False, scope="bounded_request", unknown=["timeline_truncation_not_known"]),
    ("twitter", "thread"): _spec(
        "A tweet with its replies: tweet body and the reply set",
        _list_units(raw=()), whole=True, scope="whole_artifact", unknown=["reply_set_not_exhausted"]),
    # youtube
    ("youtube", "read"): _spec(
        "Video title, channel, date and description: metadata artifact with description body optional",
        _read_units(author=True, body_required=False), whole=False, scope="bounded_request",
        unknown=["description_absence_not_distinguished_from_empty_description"]),
    ("youtube", "search"): _spec(
        "Search videos: up to 2 video hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("youtube", "subtitle"): _spec(
        "Full subtitle text of a video (manual or auto captions)",
        _read_units(), whole=True, scope="whole_artifact",
        unknown=["caption_track_end_not_proven", "auto_caption_quality_not_assessed"]),
    ("youtube", "transcribe"): _spec(
        "Speech-to-text of a video's audio (quota): full transcript",
        _read_units(), whole=True, scope="whole_artifact", unknown=["transcript_end_not_proven"]),
    # reddit
    ("reddit", "search"): _spec(
        "Search public posts: up to 2 post hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("reddit", "read"): _spec(
        "Read public page text first (upstream's public route): page text for one post",
        _read_units(body_required=True), whole=False, scope="bounded_request",
        unknown=["comment_thread_not_requested_on_public_route",
                 "page_text_end_not_proven"]),
    ("reddit", "subreddit"): _spec(
        "Latest posts in a subreddit: bounded post listing",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    # facebook
    ("facebook", "search"): _spec(
        "Search Facebook: up to 2 hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("facebook", "profile"): _spec(
        "A user's or page's profile: profile fields",
        _list_units(), whole=True, scope="whole_artifact", unknown=["profile_fields_not_assessed"]),
    # instagram
    ("instagram", "search"): _spec(
        "Search users (not posts): up to 2 user hits",
        _list_units(), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("instagram", "profile"): _spec(
        "A user's profile: profile fields",
        _list_units(), whole=True, scope="whole_artifact", unknown=["profile_fields_not_assessed"]),
    ("instagram", "posts"): _spec(
        "A user's recent posts: bounded post listing",
        _list_units(), whole=False, scope="bounded_request", unknown=["timeline_truncation_not_known"]),
    # bilibili
    ("bilibili", "search"): _spec(
        "Search videos: up to 2 video hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("bilibili", "read"): _spec(
        "Video title, uploader, description and stats",
        _read_units(author=True, body_required=False, raw=("stat",)), whole=False,
        scope="bounded_request",
        unknown=["description_absence_not_distinguished_from_empty_description"]),
    ("bilibili", "hot"): _spec(
        "Trending videos: up to 2 rows with identity, URL and video id",
        _list_units(raw=("bvid",)), whole=False, scope="bounded_request",
        unknown=["trending_list_beyond_limit_not_known"]),
    ("bilibili", "subtitle"): _spec(
        "Subtitle text of the first video part, when available",
        _read_units(), whole=True, scope="whole_artifact",
        unknown=["first_part_only", "caption_track_end_not_proven"]),
    # xiaohongshu
    ("xiaohongshu", "search"): _spec(
        "Search notes: up to 2 note hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("xiaohongshu", "read"): _spec(
        "Read a note (full link including xsec_token, as returned by search)",
        _read_units(), whole=True, scope="whole_artifact",
        unknown=["note_end_not_proven", "media_and_comments_not_inspected"]),
    ("xiaohongshu", "comments"): _spec(
        "Read loaded comments and replies from a note (upstream: not an exhaustive export)",
        _list_units(), whole=True, scope="whole_artifact",
        unknown=["loaded_comments_only_not_exhaustive"]),
    # linkedin
    ("linkedin", "jobs"): _spec(
        "Search LinkedIn jobs: up to 2 job hits with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("linkedin", "read"): _spec(
        "Read a LinkedIn job description: full description text",
        _read_units(), whole=True, scope="whole_artifact", unknown=["description_end_not_proven"]),
    # boss
    ("boss", "search"): _spec(
        "Search jobs using a configured browser session: up to 2 job hits",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("boss", "read"): _spec(
        "Read a direct BOSS job URL: full job description text",
        _read_units(), whole=True, scope="whole_artifact", unknown=["description_end_not_proven"]),
    # v2ex
    ("v2ex", "hot"): _spec(
        "Today's hot topics: up to 2 topic rows with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request",
        unknown=["hot_list_beyond_limit_not_known"]),
    ("v2ex", "node"): _spec(
        "Latest topics in a node: up to 2 topic rows with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("v2ex", "read"): _spec(
        "Read a topic and its replies: topic body plus the reply set",
        _read_units(author=True), whole=True, scope="whole_artifact",
        unknown=["reply_set_not_exhausted", "reply_count_not_recorded"]),
    ("v2ex", "user"): _spec(
        "A member's profile: identity fields",
        [
            {"id": "item_list", "kind": "items_min", "min": 1, "required": True},
            {"id": "member_username", "kind": "raw_fields", "fields": ["username"], "required": True},
            {"id": "profile_detail", "kind": "raw_fields_any",
             "fields": ["bio", "tagline", "location", "website"], "required": False},
        ], whole=False, scope="bounded_request", unknown=["profile_completeness_not_assessed"]),
    # xueqiu
    ("xueqiu", "quote"): _spec(
        "Real-time stock quote (A-share, HK, US): symbol, current price and quote time",
        [
            {"id": "item_list", "kind": "items_min", "min": 1, "required": True},
            {"id": "quote_fields", "kind": "raw_fields",
             "fields": ["symbol", "current", "time"], "required": True},
        ], whole=False, scope="bounded_request", unknown=["quote_freshness_not_assessed"]),
    ("xueqiu", "search"): _spec(
        "Find stocks by name or code: symbol and name rows",
        [
            {"id": "item_list", "kind": "items_min", "min": 1, "required": True},
            {"id": "symbol_fields", "kind": "raw_fields",
             "fields": ["symbol", "name"], "required": True},
        ], whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("xueqiu", "hot_posts"): _spec(
        "Trending Xueqiu community posts: bounded listing",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("xueqiu", "hot_stocks"): _spec(
        "Most-watched stocks on Xueqiu: bounded listing",
        _list_units(), whole=False, scope="bounded_request", unknown=_BOUNDED),
    # xiaoyuzhou
    ("xiaoyuzhou", "transcribe"): _spec(
        "Full transcript of a podcast episode (quota)",
        _read_units(), whole=True, scope="whole_artifact", unknown=["transcript_end_not_proven"]),
    # web
    ("web", "search"): _spec(
        "Search the web: up to 2 results with identity and URL",
        _list_units(snippet=True), whole=False, scope="bounded_request", unknown=_BOUNDED),
    ("web", "read"): _spec(
        "Read a web page as clean text: page body text",
        _read_units(), whole=True, scope="whole_artifact",
        unknown=["page_end_not_proven", "dynamic_or_collapsed_sections_not_inspected"]),
}


# ── manifest ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(limit: int = 2) -> dict[str, Any]:
    """The frozen manifest. Pure: no network, no subprocess, no clock in the body."""
    rows = []
    for parity in PARITY_ACTIONS:
        pair = parity.pair
        spec = ACTION_SPECS[pair]
        gate = parity.gate
        if gate == "public":
            params = dict(FROZEN_TARGETS[pair])
            if "limit" in params:
                params["limit"] = limit
            origin: Any = {"source": TARGET_ORIGIN,
                           "discovered_from": _discovered_from(pair)}
        else:
            params = {}
            origin = {"source": "gated: no target frozen; the gate must refuse the run"}
        rows.append({
            "channel": pair[0],
            "action": pair[1],
            "gate": gate,
            "coverage": parity.coverage,
            "requested_outcome": spec["requested_outcome"],
            "params": params,
            "target_origin": origin,
            "units": spec["units"],
            "whole_artifact": spec["whole_artifact"],
            "scope": spec["scope"],
            "unknown": spec["unknown"],
            "caps": spec["caps"],
        })

    pairs = {tuple((r["channel"], r["action"])) for r in rows}
    expected = {p.pair for p in PARITY_ACTIONS}
    if pairs != expected or len(rows) != len(PARITY_ACTIONS):
        raise AssertionError("frozen manifest does not cover the parity inventory exactly")
    gates = Counter(r["gate"] for r in rows)
    counts = parity_inventory()["counts"]
    if (gates["public"], gates["consent"], gates["quota"]) != (
            counts["public"], counts["gated_auth"], counts["gated_quota"]):
        raise AssertionError(f"gate counts drifted from parity inventory: {dict(gates)} vs {counts}")
    for row in rows:
        if row["gate"] == "public" and not row["params"]:
            raise AssertionError(f"public row without a frozen target: {row['channel']} {row['action']}")
        if row["gate"] != "public" and row["params"]:
            raise AssertionError(f"gated row carries params: {row['channel']} {row['action']}")

    return {
        "manifest_version": MANIFEST_VERSION,
        "reference_commit": PINNED_UPSTREAM["commit"],
        "requested_limit": limit,
        "shell_markers": list(SHELL_MARKERS),
        "shell_window_chars": SHELL_WINDOW,
        "rows": rows,
    }


def _discovered_from(pair: tuple[str, str]) -> str:
    """Where the prior sweep got a detail-read target (documented provenance)."""
    return {
        ("reddit", "read"): "reddit search result",
        ("bilibili", "read"): "bilibili hot result",
        ("xiaohongshu", "read"): "xiaohongshu search result",
        ("linkedin", "read"): "linkedin jobs result",
        ("boss", "read"): "boss search result",
        ("v2ex", "read"): "v2ex hot result",
    }.get(pair, "provided directly in the prior sweep params")


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluator_identity() -> dict[str, Any]:
    """Which evaluator produced a record, kept outside the frozen manifest.

    The manifest hash covers what was requested, not the code that judged it; a
    campaign run across several rounds can therefore share one manifest hash
    while the evaluator changed underneath it. Recording the evaluator's own
    digest makes that visible without re-freezing the manifest.
    """
    path = Path(__file__).resolve()
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:  # pragma: no cover - the script itself is readable
        digest = ""
    return {
        "script": "scripts/" + path.name,
        "sha256": digest,
        "manifest_version": MANIFEST_VERSION,
        "shell_window_chars": SHELL_WINDOW,
        "unit_kinds": sorted({unit["kind"] for spec in ACTION_SPECS.values()
                              for unit in spec["units"]}),
    }


# ── small helpers ───────────────────────────────────────────────────────────

_ABS_PATH = re.compile(r"/(?:srv|home|tmp|var|opt)/[^\s\"'<>)]+")


def _scrub(text: str) -> str:
    """Remove absolute host paths and likely secrets from a published string."""
    cleaned = _ABS_PATH.sub("<path>", text or "")
    return redact_secrets(cleaned)


def _clip(text: Any, limit: int = 200) -> str:
    value = text if isinstance(text, str) else ("" if text is None else str(text))
    value = value.replace("\r", " ").replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _sanitize(value: Any) -> Any:
    """Recursively scrub strings; keep JSON-native shapes (no str/dict mixing)."""
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _scrub(str(value))


def _norm_url(value: Any) -> str:
    text = (value or "").strip()
    text = re.sub(r"^https?://", "", text, flags=re.I)
    text = re.sub(r"^www\.", "", text, flags=re.I)
    return text.rstrip("/").lower()


def _target_matches(target: Any, url: Any) -> bool:
    """True when ``url`` is the frozen target (scheme- or slug-form)."""
    if not isinstance(target, str) or not isinstance(url, str):
        return False
    t, u = _norm_url(target), _norm_url(url)
    if not t or not u:
        return False
    if "://" in target or target.lower().startswith("www."):
        return u == t or u.startswith(t + "/") or u.startswith(t + "?") or t.startswith(u + "/")
    return t in u


_REGION_BY_KIND = {
    "items_min": "list",
    "item_field_all": "metadata",
    "target_match": "metadata",
    "body_text": "body",
    "no_shell_marker": "body",
    "raw_fields": "structured_field",
    "raw_fields_any": "structured_field",
}


def _body_texts(items: list[dict]) -> list[str]:
    return [
        item["text"] for item in items
        if isinstance(item.get("text"), str) and item["text"].strip()
    ]


def _shell_hit(text: str) -> dict | None:
    window = text[:SHELL_WINDOW].casefold()
    for marker in SHELL_MARKERS:
        pos = window.find(marker.casefold())
        if pos >= 0:
            start = max(0, pos - 40)
            return {
                "marker": marker,
                "offset_in_body": pos,
                "context": _clip(text[start:pos + len(marker) + 40], 160),
            }
    return None


def _unrun_status(status: str) -> str:
    return "not_run" if status in ("gated_not_run", "deadline_exhausted") else "unverified"


def evaluate_units(items: list[dict], units: list[dict], *, status: str) -> list[dict]:
    """Per-unit status from the actual artifact. A count never satisfies a unit."""
    results: list[dict] = []
    bodies = _body_texts(items)
    longest_body = max(bodies, key=len) if bodies else ""
    for unit in units:
        kind = unit["kind"]
        out = {
            "id": unit["id"],
            "kind": kind,
            "required": bool(unit.get("required", True)),
            "region": _REGION_BY_KIND.get(kind, "unknown"),
            "status": "unverified",
            "evidence": "",
            "note": "",
        }
        if status != "inspected":
            out["status"] = _unrun_status(status)
            if unit.get("fields"):
                out["expected"] = list(unit["fields"])
            results.append(out)
            continue

        if kind == "items_min":
            out["expected"] = {"min_items": unit.get("min", 1)}
            if len(items) >= unit.get("min", 1):
                out["status"] = "present"
                out["evidence"] = f"{len(items)} item(s)"
            else:
                out["status"] = "absent"
                out["evidence"] = f"{len(items)} item(s)"
        elif kind == "item_field_all":
            field = unit["field"]
            out["expected"] = {"field": field, "all_items": True}
            if not items:
                out["status"] = "absent"
                out["evidence"] = "no items"
            else:
                missing = [
                    index for index, item in enumerate(items)
                    if not isinstance(item.get(field), str) or not item[field].strip()
                ]
                out["status"] = "absent" if missing else "present"
                first = next(
                    (item[field] for item in items
                     if isinstance(item.get(field), str) and item[field].strip()), "")
                out["evidence"] = _clip(f"{len(items) - len(missing)}/{len(items)} items; first={first!r}", 200)
                if missing:
                    out["note"] = f"field empty on item index(es) {missing}"
        elif kind == "body_text":
            out["expected"] = {"non_empty_body": True}
            if longest_body:
                out["status"] = "present"
                out["evidence"] = f"{len(longest_body)} chars in longest item body"
            else:
                out["status"] = "absent"
                out["evidence"] = "no item carried body text (metadata-only artifact)"
        elif kind == "no_shell_marker":
            out["expected"] = {"markers": list(SHELL_MARKERS), "window": SHELL_WINDOW}
            if not bodies:
                out["status"] = "unverified"
                out["note"] = "no body text to inspect"
            else:
                hits = [hit for hit in (_shell_hit(body) for body in bodies) if hit]
                if hits:
                    out["status"] = "absent"
                    out["evidence"] = _clip(f"shell marker {hits[0]['marker']!r}: {hits[0]['context']}", 220)
                    out["note"] = "body matches a frozen error/anti-bot/empty-shell marker"
                else:
                    out["status"] = "present"
                    out["evidence"] = f"no marker in first {SHELL_WINDOW} chars of {len(bodies)} body item(s)"
        elif kind == "target_match":
            target = unit.get("target")  # injected by caller when needed
            out["expected"] = {"target": _clip(target, 120)}
            urls = [item.get("url") for item in items if isinstance(item.get("url"), str)]
            if not urls:
                out["status"] = "absent"
                out["evidence"] = "no item URL"
            elif target and any(_target_matches(target, url) for url in urls):
                out["status"] = "present"
                out["evidence"] = _clip(next(url for url in urls if _target_matches(target, url)), 160)
            else:
                out["status"] = "absent"
                out["evidence"] = _clip(f"returned {urls[0]!r} differs from requested target", 200)
                out["note"] = "returned URL is not the requested target"
        elif kind in ("raw_fields", "raw_fields_any"):
            fields = list(unit.get("fields") or [])
            out["expected"] = {"fields": fields,
                               "mode": "all" if kind == "raw_fields" else "any"}
            raws: list[dict] = []
            for item in items:
                raw = item.get("raw")
                if isinstance(raw, dict):
                    raws.append(raw)
            if not raws:
                out["status"] = "absent"
                out["evidence"] = "no structured raw payload forwarded"
            else:
                best = max(
                    raws,
                    key=lambda raw: sum(1 for field in fields if raw.get(field) is not None),
                )
                found = [field for field in fields if best.get(field) is not None]
                ok = len(found) == len(fields) if kind == "raw_fields" else bool(found)
                out["status"] = "present" if ok else "absent"
                out["evidence"] = _clip(f"found {found} of {fields}", 200)
        else:  # pragma: no cover - manifest is fixed
            out["status"] = "unverified"
            out["note"] = f"unknown unit kind {kind!r}"
        results.append(out)
    return results


def row_verdict(row: Mapping[str, Any]) -> tuple[str, str]:
    """(verdict, reason) from the frozen scope and the inspected units."""
    status = row["status"]
    if status == "gated_not_run":
        return "not_run", "gate refused the run; no action process existed"
    if status == "deadline_exhausted":
        return "not_run", "bounded wall deadline reached before this action started"
    if status == "failed":
        code = ((row.get("error") or {}).get("code")) or "error"
        return "unverified", f"no artifact: upstream/harness error {code}"
    # A required unit that could not be inspected is not the same observation as
    # a required unit that was inspected and missing: report them separately so
    # no reader has to guess which one a row's reason describes.
    absent = [u["id"] for u in row["units"] if u["required"] and u["status"] == "absent"]
    unproven = [u["id"] for u in row["units"]
                if u["required"] and u["status"] not in ("present", "absent")]
    if absent or unproven:
        reasons = []
        if absent:
            reasons.append("required_unit_not_present:" + ",".join(absent))
        if unproven:
            reasons.append("required_unit_unverified:" + ",".join(unproven))
        return "incomplete", "; ".join(reasons)
    if row.get("whole_artifact"):
        truncated = (row.get("artifact") or {}).get("text_truncated_items") or 0
        if truncated:
            return "incomplete", "artifact_truncated_at_output_bound"
        return "incomplete", "end_of_artifact_not_proven"
    return "complete", "bounded_request_units_present"


def artifact_kind(items: list[dict], units: list[dict]) -> str:
    if not items:
        return "none"
    shell = next((u for u in units if u["id"] == "body_not_error_shell"), None)
    if shell is not None and shell["status"] == "absent":
        return "unusable_shell"
    if _body_texts(items):
        return "body"
    return "metadata_only"


# ── reference verification ──────────────────────────────────────────────────

def verify_reference(executable: str) -> dict[str, Any]:
    """Prove the executable is the pinned 1.6.0 tree from its own dist-info."""
    path = Path(executable)
    if not path.exists():
        raise SystemExit(f"agent-reach executable not found: {path}")
    if not os.access(path, os.X_OK):
        raise SystemExit(f"agent-reach executable is not executable: {path}")
    python = path.with_name("python")
    if not python.exists():
        raise SystemExit("expected the pinned eval virtualenv interpreter next to the executable")
    probe = (
        "import importlib.metadata as m, json\n"
        "d = m.distribution('agent-reach')\n"
        "print(json.dumps({'version': d.version,"
        " 'direct_url': d.read_text('direct_url.json')}))\n"
    )
    completed = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, timeout=60)
    if completed.returncode != 0:
        raise SystemExit(f"could not read agent-reach distribution metadata: {completed.stderr[:300]}")
    meta = json.loads(completed.stdout)
    direct = meta.get("direct_url") or "{}"
    commit = PINNED_UPSTREAM["commit"]
    if not meta.get("version", "").startswith("1.6."):
        raise SystemExit(f"unexpected agent-reach version: {meta.get('version')!r}")
    if commit not in direct:
        raise SystemExit("the executable's direct_url does not record the pinned commit")
    return {
        "version": meta["version"],
        "pinned_commit_recorded": True,
        "direct_url_is_pinned_archive": commit in direct,
        "executable_kind": "pinned eval virtualenv (absolute path withheld)",
        "interpreter": python.name,
    }


# ── execution ───────────────────────────────────────────────────────────────

class _SpyRunner:
    """Runner that records argv and never touches the network."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, timeout=None, env=None):
        self.calls.append(list(argv))
        payload = {
            "schema_version": 1, "ok": True, "channel": None, "action": None,
            "backend": "spy", "items": [],
            "meta": {"elapsed_ms": 0, "attempts": []},
        }
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")


class _GatedProbe(AgentReachBackend):
    """Backend whose registry is the already-validated real one.

    The gate decision (auth / quota / ASR veto) is the thing under test, so the
    probe must not spend a discovery subprocess and must not re-derive the
    inventory from a fake payload.  Only an action call may reach the spy
    runner; if it does, the gate leaked.
    """

    def __init__(self, *args, registry, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._validated_registry = registry

    def registry(self, *, refresh: bool = False):  # type: ignore[override]
        return self._validated_registry


def _action_calls(calls: list[list[str]]) -> list[list[str]]:
    """Spy calls that would be an *action* spawn, not registry discovery.

    Discovery is ``<exe> channels [flags…]``, so any argv whose first argument
    is ``channels`` is discovery however it is spelled. Treating only the exact
    ``["channels"]`` shape as discovery would misreport a flagged discovery call
    as an action process.
    """
    return [call for call in calls if not (len(call) > 1 and call[1] == "channels")]


def check_gate(channel: str, action: str, executable: str, env: Mapping[str, str],
               registry) -> dict:
    """Exercise a gated row's refusal with a spy runner; prove no action spawn."""
    spy = _SpyRunner()
    backend = _GatedProbe(
        executable, env=dict(env), timeout=5.0, registry=registry,
        allow_authenticated=False, allow_quota_consuming=False, runner=spy,
    )
    result = backend.execute(channel, action, {})
    action_calls = _action_calls(spy.calls)
    return {
        "error_code": (result.error or {}).get("code"),
        "result_ok": result.ok,
        "runner_calls": len(spy.calls),
        "spawned_action_process": bool(action_calls),
        "action_argv": action_calls,
        "asr_veto": asr_disabled(env),
    }


def _raw_path(raw_dir: Path, channel: str, action: str) -> Path:
    return raw_dir / f"{channel}-{action}.json"


def run_public(row: dict, backend: AgentReachBackend, *, limit: int, timeout: float,
               raw_dir: Path) -> dict:
    started = time.monotonic()
    try:
        result = backend.execute(
            row["channel"], row["action"], row["params"],
            timeout=timeout, allow_authenticated=False, allow_quota_consuming=False,
            max_items=limit,
        ).to_dict()
        error = None
    except Exception as exc:  # harness failure, recorded rather than hidden
        result = None
        error = {"code": "harness_error", "message": _clip(f"{type(exc).__name__}: {exc}", 300)}
    wall_ms = int((time.monotonic() - started) * 1000)
    raw_file = _raw_path(raw_dir, row["channel"], row["action"])
    raw_file.write_text(json.dumps(result if result is not None else {"harness_error": error},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return {"result": result, "error": error, "wall_ms": wall_ms, "raw_file": raw_file.name}


def build_row(frozen: dict, *, status: str, result: Mapping[str, Any] | None,
              error: Mapping[str, Any] | None, wall_ms: int | None,
              raw_file: str | None, gate_probe: Mapping[str, Any] | None) -> dict:
    items = list((result or {}).get("items") or [])
    units = [dict(unit) for unit in frozen["units"]]
    for unit in units:
        if unit["kind"] == "target_match":
            unit["target"] = frozen["params"].get("target", "")

    upstream_error = dict((result or {}).get("error") or {})
    if error:
        upstream_error = dict(error)
    preserved_error = None
    if upstream_error:
        # Everything the forwarding layer reported is kept: dropping a field
        # (e.g. ``reasons`` or ``withheld_items``) would silently weaken the
        # error record the row is supposed to preserve.
        details = {
            key: value for key, value in upstream_error.items()
            if key not in {"code", "upstream_code", "message", "hint"}
        }
        preserved_error = {
            "code": upstream_error.get("code"),
            "upstream_code": upstream_error.get("upstream_code"),
            "message": _clip(_scrub(upstream_error.get("message") or ""), 300),
            "hint": _clip(_scrub(upstream_error.get("hint") or ""), 200),
            "timed_out": bool((result or {}).get("timed_out")),
            "attempts": list((result or {}).get("attempts") or []),
            "exit_code": (result or {}).get("exit_code"),
            "details": _sanitize(details),
        }

    unit_results = evaluate_units(items, units, status=status)

    bodies = _body_texts(items)
    longest = max(bodies, key=len) if bodies else ""
    artifact = {
        "items": len(items),
        "items_with_body": len(bodies),
        "items_with_raw": sum(1 for item in items if isinstance(item.get("raw"), dict)),
        "body_chars": [len(body) for body in bodies][:5],
        "max_body_chars": len(longest),
        "body_sha256": hashlib.sha256(longest.encode("utf-8")).hexdigest() if longest else None,
        "body_preview": _clip(_scrub(longest), 160) if longest else "",
        "text_truncated_items": sum(1 for item in items if item.get("text_truncated")),
        "returned_url": _clip(items[0].get("url") or "", 200) if items else "",
    }

    row = {
        "channel": frozen["channel"],
        "action": frozen["action"],
        "gate": frozen["gate"],
        "coverage": frozen["coverage"],
        "whole_artifact": bool(frozen["whole_artifact"]),
        "requested_outcome": frozen["requested_outcome"],
        "params": frozen["params"],
        "target_origin": frozen["target_origin"],
        "status": status,
        "classification": status,  # replaced below for inspected rows
        "backend": (result or {}).get("backend"),
        "route": ((result or {}).get("provenance") or {}).get("route"),
        "home_mode": ((result or {}).get("provenance") or {}).get("home_mode"),
        "wall_ms": wall_ms,
        "elapsed_ms": (result or {}).get("elapsed_ms"),
        "error": preserved_error,
        "items": len(items),
        "artifact": artifact,
        "units": unit_results,
        "artifact_kind": artifact_kind(items, unit_results),
        "raw_payload": raw_file,
        "limitations": [_clip(_scrub(line), 220) for line in ((result or {}).get("limitations") or [])],
    }
    if gate_probe is not None:
        row["gate_probe"] = dict(gate_probe)

    completeness = {
        "scope": frozen["scope"],
        "whole_artifact_requested": bool(frozen["whole_artifact"]),
        "whole_artifact_proven": False if frozen["whole_artifact"] else None,
        "known": [
            f"items_returned={len(items)}",
            f"items_with_body={len(bodies)}",
            f"text_truncated_items={artifact['text_truncated_items']}",
            f"max_body_chars={artifact['max_body_chars']}",
            f"backend={row['backend']}",
            f"route={row['route']}",
        ],
        "unknown": list(frozen["unknown"]),
        "caps": {
            "requested_limit": (frozen["params"].get("limit")
                                if isinstance(frozen["params"], dict) else None),
            "items_returned": len(items),
            "max_text_chars_per_item": MAX_TEXT_CHARS,
            "text_truncated_items": artifact["text_truncated_items"],
        },
        **frozen["caps"],
    }
    row["completeness"] = completeness

    verdict, reason = row_verdict(row)
    row["verdict"] = verdict
    row["verdict_reason"] = reason
    if status == "inspected":
        row["classification"] = {
            "unusable_shell": "inspected_unusable",
            "metadata_only": "inspected_metadata_only",
            "body": "inspected_body",
            "none": "inspected_empty",
        }[row["artifact_kind"]]
    return row


# ── summary ─────────────────────────────────────────────────────────────────

def summarize(rows: list[dict], *, frozen_at: str, manifest_sha: str,
              reference: Mapping[str, Any], conditions: Mapping[str, Any]) -> dict:
    ledger = {
        "actions_total": len(rows),
        "channels": len({row["channel"] for row in rows}),
        "public": sum(1 for row in rows if row["gate"] == "public"),
        "consent": sum(1 for row in rows if row["gate"] == "consent"),
        "quota": sum(1 for row in rows if row["gate"] == "quota"),
        "executed_public": sum(
            1 for row in rows if row["gate"] == "public"
            and row["status"] in ("inspected", "failed")
        ),
        "gated_not_run": sum(1 for row in rows if row["status"] == "gated_not_run"),
        "deadline_exhausted": sum(1 for row in rows if row["status"] == "deadline_exhausted"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "inspected": sum(1 for row in rows if row["status"] == "inspected"),
    }
    statuses = Counter(row["status"] for row in rows)
    verdicts = Counter(row["verdict"] for row in rows)
    kinds = Counter(row["artifact_kind"] for row in rows)
    units = [unit for row in rows for unit in row["units"]]
    by_status = Counter(unit["status"] for unit in units)
    regions: dict[str, Counter] = {}
    for unit in units:
        regions.setdefault(unit["region"], Counter())[unit["status"]] += 1
    failure_codes = Counter(
        (row["error"] or {}).get("upstream_code") or (row["error"] or {}).get("code")
        for row in rows if row["status"] == "failed" and row.get("error")
    )
    whole_rows = [
        row for row in rows
        if row["completeness"]["whole_artifact_requested"] and row["status"] == "inspected"
    ]
    gated_whole_rows = [
        row for row in rows
        if row["completeness"]["whole_artifact_requested"] and row["status"] != "inspected"
    ]
    truncated = [
        {"channel": row["channel"], "action": row["action"],
         "items": row["artifact"]["items"],
         "max_body_chars": row["artifact"]["max_body_chars"]}
        for row in rows if row["artifact"]["text_truncated_items"]
    ]
    gated_probes = [row for row in rows if row["gate"] != "public" and "gate_probe" in row]
    gated_verified = [
        row for row in gated_probes
        if not row["gate_probe"]["spawned_action_process"] and not row["gate_probe"]["result_ok"]
    ]
    required_units = [unit for unit in units if unit["required"]]
    present_required = sum(1 for unit in required_units if unit["status"] == "present")
    # A denominator that includes gated/unrun rows would overstate what was
    # assessed, so the headline counts are scoped to inspected artifacts.
    inspected_rows = [row for row in rows if row["status"] == "inspected"]
    inspected_required = [
        unit for row in inspected_rows for unit in row["units"] if unit["required"]
    ]
    inspected_present = sum(1 for unit in inspected_required if unit["status"] == "present")

    summary = {
        "ledger": {**ledger, "status_counts": dict(sorted(statuses.items()))},
        "artifact_summary": {
            "rows_with_artifact": sum(1 for row in rows if row["artifact_kind"] != "none"),
            "artifact_kinds": dict(sorted(kinds.items())),
            "verdicts": dict(sorted(verdicts.items())),
            "units_total": len(units),
            "units_required": len(required_units),
            "units_present_required": present_required,
            "rows_inspected": len(inspected_rows),
            "units_required_inspected": len(inspected_required),
            "units_present_required_inspected": inspected_present,
            "units_by_status": dict(sorted(by_status.items())),
            "units_by_region": {
                region: dict(sorted(counter.items())) for region, counter in sorted(regions.items())
            },
            "whole_artifact_rows_inspected": len(whole_rows),
            "whole_artifact_rows_not_run_or_failed": len(gated_whole_rows),
            "whole_artifact_proven": sum(
                1 for row in whole_rows if row["completeness"]["whole_artifact_proven"]
            ),
            "truncated_rows": truncated,
            "failure_codes": dict(sorted(failure_codes.items())),
            "gated_rows_probed": len(gated_probes),
            "gated_rows_refused_without_action_process": len(gated_verified),
        },
        "attempt_accounting": {
            "authenticated_calls": 0,
            "quota_consuming_calls": 0,
            "asr_calls": 0,
            "account_or_session_imports": 0,
        },
    }

    claim = (
        f"On {ledger['actions_total']} pinned actions ({ledger['public']} public, "
        f"{ledger['consent']} auth-gated, {ledger['quota']} quota-gated): "
        f"{ledger['executed_public']} public actions were executed, "
        f"{ledger['gated_not_run']} gated actions were not run, "
        f"{inspected_present}/{len(inspected_required)} required artifact units on inspected "
        "rows were present, "
        f"{summary['artifact_summary']['verdicts'].get('complete', 0)} rows were complete "
        "for their bounded/requested units, "
        f"{summary['artifact_summary']['verdicts'].get('incomplete', 0)} were incomplete, "
        f"{summary['artifact_summary']['verdicts'].get('unverified', 0)} were unverified, and "
        f"whole-artifact completeness was proven for "
        f"{summary['artifact_summary']['whole_artifact_proven']} of {len(whole_rows)} "
        "inspected read-type rows."
    )

    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "evaluator": evaluator_identity(),
        "reference": dict(reference),
        "conditions": dict(conditions),
        "manifest": {
            "version": MANIFEST_VERSION,
            "sha256": manifest_sha,
            "frozen_at": frozen_at,
            "frozen_before_calls": True,
            "rows": len(rows),
            "source": "scripts/evaluate_action_artifacts.py:build_manifest()",
        },
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        **summary,
        "rows": rows,
        "errors_preserved": True,
        "claims": {
            "claim": claim,
            "complete_rows_are_bounded_or_requested_units_only": True,
            "returned_item_counts_are_not_evidence_of_artifact_completeness": True,
            "superiority_claim": (
                "not established: no cross-tool comparison was run and coverage of the "
                "same 40 action names is not superiority"
            ),
            "not_established": [
                "authenticated parity: the 12 consent actions were not run",
                "quota/transcription parity: the 2 quota actions were not run; zero spend",
                "whole-artifact completeness: no read proved its end/reply set was exhausted",
                "reliability, freshness, latency and resource parity",
                "content quality or human relevance of returned bodies",
                "multi-day or multi-host stability",
            ],
        },
    }


# ── main ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Full 40-action ledger with frozen artifact-unit evaluation (no auth/quota)"
    )
    parser.add_argument("--agent-reach", required=True,
                        help="Pinned agent-reach 1.6.0 executable from a verified tree")
    parser.add_argument("--scratch", required=True, help="Directory for raw payloads")
    parser.add_argument("--out", help="Sanitized JSON evidence path")
    parser.add_argument("--limit", type=int, default=2, help="Per-action item limit (frozen)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-action wall deadline (s)")
    parser.add_argument("--deadline", type=float, default=720.0, help="Whole-run wall deadline (s)")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent public calls (bounded)")
    parser.add_argument("--freeze-only", action="store_true",
                        help="Write the frozen manifest and exit; no calls are made")
    args = parser.parse_args(argv)

    scratch = Path(args.scratch)
    raw_dir = scratch / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    os.environ["TRAILHEAD_DISABLE_ASR"] = "1"
    env = dict(os.environ)
    reference = verify_reference(args.agent_reach)

    # ── freeze before any call ──────────────────────────────────────────
    manifest = build_manifest(limit=args.limit)
    digest = manifest_digest(manifest)
    frozen_at = _now()
    frozen_path = scratch / "manifest-frozen.json"
    frozen_path.write_text(json.dumps(
        {"digest": digest, "frozen_at": frozen_at, "manifest": manifest},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"frozen manifest {digest[:16]}… ({len(manifest['rows'])} rows) at {frozen_at}", flush=True)
    if args.freeze_only:
        return 0

    # Registry validation happens after the freeze, against the pinned tree.
    backend = AgentReachBackend(args.agent_reach, env=env, timeout=args.timeout,
                                allow_authenticated=False, allow_quota_consuming=False,
                                max_items=args.limit)
    registry = backend.registry(refresh=True)
    validate_parity_inventory(registry)
    reference = {
        **reference,
        "project": PINNED_UPSTREAM["project"],
        "commit": PINNED_UPSTREAM["commit"],
        "registry_schema_version": registry.schema_version,
        "registry_channels": len(registry.channels),
        "registry_actions": sum(len(channel.actions) for channel in registry.channels.values()),
        "registry_validated_against_pinned_inventory": True,
    }
    print(f"registry validated: {reference['registry_channels']} channels / "
          f"{reference['registry_actions']} actions", flush=True)

    conditions = {
        "auth_consent": False,
        "quota_consent": False,
        "asr_disabled": asr_disabled(env),
        "home": "isolated-temp (empty throwaway HOME, redirected XDG/APPDATA)",
        "forced_public_routes": True,
        "sandbox": False,
        "per_action_timeout_seconds": args.timeout,
        "whole_run_deadline_seconds": args.deadline,
        "concurrency": args.workers,
        "limit": args.limit,
        "started_at": _now(),
        "isolation_note": "environment isolation only, not a filesystem or process sandbox",
    }

    deadline_at = time.monotonic() + args.deadline
    rows: list[dict] = []

    gated = [row for row in manifest["rows"] if row["gate"] != "public"]
    public = [row for row in manifest["rows"] if row["gate"] == "public"]

    # Gated rows: gate exercised with a spy runner; no action process may exist.
    for frozen in gated:
        probe = check_gate(frozen["channel"], frozen["action"], args.agent_reach, env, registry)
        row = build_row(frozen, status="gated_not_run", result=None, error=None,
                        wall_ms=None, raw_file=None, gate_probe=probe)
        row["error"] = {
            "code": probe["error_code"],
            "upstream_code": None,
            "message": "gate refused the run before an action process existed",
            "timed_out": False,
            "attempts": [],
            "exit_code": None,
        }
        rows.append(row)
        print(f"{frozen['channel']:12s} {frozen['action']:11s} gated_not_run "
              f"{probe['error_code']} spawned_action={probe['spawned_action_process']}", flush=True)

    # Public rows: real public calls under the frozen wall clock.
    def _task(frozen: dict) -> dict:
        if time.monotonic() >= deadline_at:
            row = build_row(frozen, status="deadline_exhausted", result=None, error=None,
                            wall_ms=None, raw_file=None, gate_probe=None)
            return row
        outcome = run_public(frozen, backend, limit=args.limit,
                             timeout=args.timeout, raw_dir=raw_dir)
        result = outcome["result"]
        if outcome["error"] is not None:
            status = "failed"
        elif result and result.get("ok"):
            status = "inspected"
        else:
            status = "failed"
        row = build_row(frozen, status=status, result=result, error=outcome["error"],
                        wall_ms=outcome["wall_ms"], raw_file=outcome["raw_file"],
                        gate_probe=None)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for row in pool.map(_task, public):
            rows.append(row)
            print(f"{row['channel']:12s} {row['action']:11s} {row['status']:18s} "
                  f"{row['verdict']:11s} items={row['items']} "
                  f"err={(row['error'] or {}).get('upstream_code') or (row['error'] or {}).get('code') or '-'}",
                  flush=True)

    order = {(row["channel"], row["action"]): index for index, row in enumerate(manifest["rows"])}
    rows.sort(key=lambda row: order[(row["channel"], row["action"])])

    evidence = summarize(rows, frozen_at=frozen_at, manifest_sha=digest,
                         reference=reference, conditions=conditions)
    evidence["conditions"]["finished_at"] = _now()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        print(f"wrote {out_path}", flush=True)

    print(json.dumps({"ledger": evidence["ledger"],
                      "artifact_summary": {key: value for key, value in
                                           evidence["artifact_summary"].items()
                                           if key != "truncated_rows"}},
                     ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
