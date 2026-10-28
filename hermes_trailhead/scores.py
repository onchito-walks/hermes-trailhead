"""Lane scorecards — historical claims plus explicitly separate live probes.

The grades in this module are a **static snapshot** written from live runs on
``VERIFIED`` (2026-10-14).  They are release-note claims, not measurements.
``score --live`` deliberately does *not* re-derive them: it runs one
reachability probe per lane from the current host and reports the result next
to the historical claim, in a separate section, with a machine-readable
``counts_as_evidence`` flag on every probe.

Two honesty rules this module enforces:

1. ``grades_measured`` is always ``False``.  A probed route is not a grade.
2. A cached transcript file is a local artifact.  YouTube's probe reports the
   cache count but marks it as *not* a fresh transcript success, because
   counting yesterday's files says nothing about today's extraction.

For measured per-case comparisons against another tool, use
``hermes-trailhead compare`` (``hermes_trailhead.comparative``), not this
scorecard.
"""
from __future__ import annotations

import os
import urllib.request
from datetime import datetime, timezone

#: Date the static grades below were written from live runs.  Historical.
VERIFIED = "2026-10-14"

#: Marker for "this number came from a document, not from a measurement now".
GRADE_SOURCE = "static_snapshot"

SNAPSHOT_STATEMENT = (
    "Grades were written from live runs on 2026-10-14. They are historical "
    "claims about that date; --live does not re-derive them."
)

DIMENSIONS = [
    {
        "dimension": "Breadth",
        "grade": "A",
        "detail": "One question fans out across seven platform families at once — video, social, forum, code, and open web.",
    },
    {
        "dimension": "Depth",
        "grade": "A-",
        "detail": "Not links — content: captions, full threads, spoken transcripts, top comments, profile pages, repository facts.",
    },
    {
        "dimension": "Freshness",
        "grade": "A",
        "detail": "Platforms are read live — this hour's threads, today's posts — not a stale index.",
    },
    {
        "dimension": "Authenticated reach",
        "grade": "A-",
        "detail": "What sits behind a login is reachable too — mailbox access plus persistent browser sessions (bring your own).",
    },
    {
        "dimension": "Honesty",
        "grade": "A",
        "detail": "Blocked is reported blocked, with the reason. Failure is a first-class output, never painted green.",
    },
    {
        "dimension": "Reliability",
        "grade": "B+",
        "detail": "Lanes are watched and self-healing; single-route fallbacks are the named weak spot.",
    },
    {
        "dimension": "Effort & cost",
        "grade": "A",
        "detail": "One command — or just ask your agent. Free-first by default; the entire cache weighs kilobytes.",
    },
]

LANE_SCORES = [
    {"lane": "youtube", "grade": "A", "what": "Full spoken transcripts — captionless videos included"},
    {"lane": "github", "grade": "A", "what": "Repository facts, READMEs, releases, file trees"},
    {"lane": "web", "grade": "A-", "what": "Clean deep content — docs, forums, PDFs"},
    {"lane": "reddit", "grade": "A-", "what": "Full threads with comment context"},
    {"lane": "x", "grade": "A-", "what": "Structured posts and practitioner discussions"},
    {"lane": "tiktok", "grade": "A-", "what": "Metadata, top comments, and the video's actual spoken words"},
    {"lane": "instagram", "grade": "A-", "what": "Reel/post captions plus full profile pages"},
]

LIMITATIONS = [
    "Grades are static claims from the snapshot date; --live never re-derives them.",
    "Each probe checks one route's reachability from this host at this moment — not content quality, depth, or coverage.",
    "A cached transcript file is a local artifact; it is not evidence that a transcript can be fetched now.",
    "Per-lane probes are not a head-to-head comparison; use `hermes-trailhead compare` for measured case results.",
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: A public, stable video used only to test whether the metadata endpoint answers.
_YOUTUBE_OEMBED = (
    "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com"
    "%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe(url: str, timeout: int = 8, headers: dict | None = None) -> str:
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return f"http {resp.status}"
    except Exception as exc:
        code = getattr(exc, "code", None)
        return f"http {code}" if code else f"unreachable ({type(exc).__name__})"


def _probe_payload(
    lane: str,
    probe: str,
    result: str,
    counts_as_evidence: bool,
    *,
    note: str = "",
    details: dict | None = None,
) -> dict:
    """One probe observation.  ``counts_as_evidence`` is a deliberate judgment."""
    return {
        "lane": lane,
        "probe": probe,
        "result": result,
        "counts_as_evidence": bool(counts_as_evidence),
        "note": note,
        "details": details or {},
        "checked_at": _now(),
    }


def _transcript_cache_count() -> int:
    try:
        from .paths import hermes_state_dir

        return len(list((hermes_state_dir() / "trailhead-transcripts").glob("*.txt")))
    except Exception:
        return 0


def _probe_for(lane: str) -> dict:
    """Best-effort reachability probe for one lane's key route (this host, now)."""
    try:
        if lane == "x":
            result = _probe("https://api.fxtwitter.com/status/20")
            return _probe_payload(lane, "fxtwitter_status", result, result.startswith("http 200"))
        if lane == "tiktok":
            result = _probe("https://www.tikwm.com/api/?url=x")
            return _probe_payload(lane, "tikwm_api", result, result.startswith("http 200"))
        if lane == "reddit":
            result = _probe("https://api.pullpush.io/reddit/search/submission/?size=1")
            return _probe_payload(lane, "pullpush_api", result, result.startswith("http 200"))
        if lane == "github":
            headers: dict = {}
            try:
                from .backends import _github_request_headers

                headers = _github_request_headers()
            except Exception:
                headers = {}
            tag = "authed" if headers else "anonymous"
            result = _probe("https://api.github.com/rate_limit", headers=headers)
            return _probe_payload(
                lane,
                "github_rate_limit",
                f"{tag}: {result}",
                result.startswith("http 200"),
                note="Shows the GitHub API answered; not proof of repo/issue coverage.",
            )
        if lane == "web":
            result = _probe("https://html.duckduckgo.com/html/?q=trailhead")
            return _probe_payload(
                lane,
                "duckduckgo_html",
                result,
                result.startswith("http 200"),
                note="Shows the search entry page answered; result parsing is not exercised.",
            )
        if lane == "youtube":
            cache = _transcript_cache_count()
            result = _probe(_YOUTUBE_OEMBED)
            return _probe_payload(
                lane,
                "youtube_oembed",
                f"video metadata: {result}",
                result.startswith("http 200"),
                note=(
                    "Public video metadata reachability only. Cached transcript files "
                    "are local artifacts and are NOT counted as a fresh transcript success."
                ),
                details={
                    "cached_transcripts": cache,
                    "cached_transcripts_counts_as_success": False,
                },
            )
        if lane == "instagram":
            user = os.environ.get("TRAILHEAD_CAMOFOX_USER", "").strip()
            if not user:
                return _probe_payload(
                    lane,
                    "camofox_session",
                    "session tier not configured (TRAILHEAD_CAMOFOX_USER unset)",
                    False,
                    note="Not measured: the authenticated tier is off on this host.",
                )
            api = os.environ.get("TRAILHEAD_CAMOFOX_API", "http://127.0.0.1:9377")
            result = _probe(api + "/health")
            return _probe_payload(
                lane,
                "camofox_session",
                f"session tier: {result}",
                result.startswith("http 200"),
                note="Local session service reachability only; no page was read.",
            )
    except Exception as exc:  # probes never raise
        return _probe_payload(lane, "probe", f"probe error ({type(exc).__name__})", False)
    return _probe_payload(lane, "none", "no probe defined", False)


def lane_scores(live: bool = False) -> dict:
    """The full scorecard: static claims, plus measured probes when ``live``.

    Backwards compatibility: ``verified`` stays the snapshot date, each lane
    keeps ``grade`` / ``what`` / ``verified``, and ``live`` stays a short
    human-readable probe string when probes run.  New, explicit fields are
    ``grade_source``, ``grade_snapshot``, ``grades_measured``,
    ``measured_probes``, and per-lane ``live_probe``.
    """
    lanes = []
    probes: list[dict] = []
    for row in LANE_SCORES:
        item: dict = dict(row)
        item["verified"] = VERIFIED
        item["grade_source"] = GRADE_SOURCE
        if live:
            probe = _probe_for(row["lane"])
            probes.append(probe)
            item["live"] = str(probe["result"])
            item["live_probe"] = probe
        lanes.append(item)

    return {
        "verified": VERIFIED,
        "grade_source": GRADE_SOURCE,
        "grade_snapshot": {
            "date": VERIFIED,
            "statement": SNAPSHOT_STATEMENT,
            "measured_by_live": False,
        },
        "grades_measured": False,
        "probes_run_at": probes[0]["checked_at"] if probes else None,
        "dimensions": [
            {**row, "verified": VERIFIED, "grade_source": GRADE_SOURCE} for row in DIMENSIONS
        ],
        "lanes": lanes,
        "measured_probes": probes,
        "limitations": list(LIMITATIONS),
    }


def format_scores_text(payload: dict) -> str:
    snapshot = payload.get("grade_snapshot") or {}
    date = snapshot.get("date") or payload["verified"]
    lines = [
        "Hermes Trailhead — per-lane scorecard",
        "",
        f"Static claims snapshot: {date} (historical, not measured now)",
        f"  {snapshot.get('statement', SNAPSHOT_STATEMENT)}",
        "",
    ]
    for row in payload["lanes"]:
        lines.append(f"  {row['grade']:<2}  {row['lane']:<10} {row['what']}")

    probes = payload.get("measured_probes") or []
    if probes:
        lines.append("")
        lines.append(f"Measured probes (this host, {payload.get('probes_run_at')})")
        lines.append(
            "  Reachability only: a passing probe is not a quality grade, and a cached"
        )
        lines.append("  transcript file is not evidence of a fresh transcript fetch.")
        lines.append("")
        for probe in probes:
            mark = "counts as evidence" if probe["counts_as_evidence"] else "not measured"
            lines.append(f"  {probe['lane']:<10} {probe['result']}  [{mark}]")
            details = probe.get("details") or {}
            if "cached_transcripts" in details:
                lines.append(
                    f"             cached transcript files: {details['cached_transcripts']} "
                    "(local artifact; not a transcript success)"
                )
            if probe.get("note"):
                lines.append(f"             note: {probe['note']}")
    else:
        lines.append("")
        lines.append("Measured probes: none (run with --live to probe route reachability).")

    lines.append("")
    lines.append("Limitations")
    for item in payload.get("limitations", LIMITATIONS):
        lines.append(f"  - {item}")
    return "\n".join(lines)
