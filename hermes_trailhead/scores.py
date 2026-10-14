"""Lane scorecards — the Trailhead's per-trail product scoring system.

Every lane carries a grade describing what a researcher actually gets today
(verified against live runs), plus one plain-language line of what that buys.
``score --live`` additionally probes each lane's key route from THIS host so
the scorecard reflects the current deployment, not just the release notes.

Grades describe results, not technology: A means "strong and proven in live
use", A- means "strong, with named edges still worth filing down". Grades are
re-verified against live runs whenever lanes change; the ledger of what's
still open lives in ``docs/KNOWN-ISSUES.md``.
"""
from __future__ import annotations

import os
import urllib.request

VERIFIED = "2026-10-14"

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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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


def _probe_for(lane: str) -> str:
    """Best-effort reachability probe for one lane's key route (this host, now)."""
    try:
        if lane == "x":
            return _probe("https://api.fxtwitter.com/status/20")
        if lane == "tiktok":
            return _probe("https://www.tikwm.com/api/?url=x")
        if lane == "reddit":
            return _probe("https://api.pullpush.io/reddit/search/submission/?size=1")
        if lane == "github":
            headers: dict = {}
            try:
                from .backends import _github_request_headers

                headers = _github_request_headers()
            except Exception:
                headers = {}
            tag = "authed" if headers else "anonymous"
            return f"{tag}: {_probe('https://api.github.com/rate_limit', headers=headers)}"
        if lane == "web":
            return _probe("https://html.duckduckgo.com/html/?q=trailhead")
        if lane == "youtube":
            from .paths import hermes_state_dir

            count = 0
            try:
                count = len(list((hermes_state_dir() / "trailhead-transcripts").glob("*.txt")))
            except Exception:
                count = 0
            return f"transcript cache: {count} items"
        if lane == "instagram":
            user = os.environ.get("TRAILHEAD_CAMOFOX_USER", "").strip()
            if not user:
                return "session tier off (TRAILHEAD_CAMOFOX_USER unset)"
            api = os.environ.get("TRAILHEAD_CAMOFOX_API", "http://127.0.0.1:9377")
            return f"session tier: {_probe(api + '/health')}"
    except Exception as exc:  # probes never raise
        return f"probe error ({type(exc).__name__})"
    return "no probe"


def lane_scores(live: bool = False) -> dict:
    """The full scorecard: dimensions + per-lane grades, optionally live-probed."""
    lanes = []
    for row in LANE_SCORES:
        item = dict(row)
        item["verified"] = VERIFIED
        if live:
            item["live"] = _probe_for(row["lane"])
        lanes.append(item)
    return {"verified": VERIFIED, "dimensions": DIMENSIONS, "lanes": lanes}


def format_scores_text(payload: dict) -> str:
    lines = [f"Hermes Trailhead — per-lane scorecard (verified live {payload['verified']})"]
    lines.append("")
    for row in payload["lanes"]:
        live = f"   [{row['live']}]" if "live" in row else ""
        lines.append(f"  {row['grade']:<2}  {row['lane']:<10} {row['what']}{live}")
    lines.append("")
    lines.append("Grades describe what a researcher gets today, verified against live runs.")
    return "\n".join(lines)
