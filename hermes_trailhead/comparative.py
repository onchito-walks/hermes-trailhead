"""Honest head-to-head comparative benchmark: Trailhead vs an optional Agent Reach CLI.

Methodology (corrected after review)
------------------------------------
1. **Matched outcomes, not matched commands.** Each case declares *the outcome
   requested* and how each tool is asked for that same outcome. A video
   *transcript* case asks Agent Reach for `youtube subtitle`, not `read`
   (metadata). A V2EX *node listing* case asks Agent Reach for `v2ex node`,
   not `read` (which upstream rejects for node URLs). If no equivalent exists,
   the case is reported `not_comparable` instead of being compared anyway.
2. **Evidence, not character counts.** Raw length proves nothing: 600 KB of
   HTML markup is not evidence, and a 158-byte login wall is not a successful
   read. Every result is assessed for markup ratio, login-wall phrases, cleaned
   text length, and (for transcript cases) whether transcript material was
   actually returned. `evidence_ok` is the only success signal. It says
   readable, non-wall text came back at the requested scope — not that the
   text is relevant or high quality.
3. **No aggregate winner.** Cases differ in scope, corpus, and access path, so
   the report publishes per-case outcomes and explicitly refuses a ranking.
4. **Environment-isolated, one wall budget, both sides.** Both tools run as
   killable subprocesses with the *same* wall-clock timeout. Each gets the same
   explicitly built environment: a throwaway `HOME`/`HERMES_HOME`, and every
   credential-, session-, cookie-, and proxy-shaped variable removed (Agent
   Reach sees no inherited config, browser profile, or hidden session). This is
   *environment* isolation only — not a filesystem or OS sandbox: a process can
   still open absolute paths outside the sandbox, so it is not credential-proof.
   Billable media ASR is off for the run (`TRAILHEAD_DISABLE_ASR=1`), so a
   public comparison never buys a transcription. A fresh sandbox also means a
   cold cache; reusing a sandbox is a separate, labeled warm run.
   The default Trailhead side is a stdlib `python -m` worker with JSON over
   stdin/stdout (no shell); the parent kills the whole process group when the
   budget expires. In-process runners can still be injected for tests, and the
   report labels that mode `injected` (no wall timeout) so it is never mistaken
   for a measured subprocess run.
5. **No grading.** There is no A/A- scale here. Every field is an observation:
   status, duration, raw and cleaned characters, error code, and the argv used.

Agent Reach contract (verified against its 1.6.0 source)
--------------------------------------------------------
Unified entry points are ``agent-reach <channel> <action> [args]``,
``agent-reach read <url>``, and ``agent-reach channels``. Exactly one JSON
object is printed to stdout::

    {schema_version, ok, channel, action, backend, items, meta, error}

``items[].text`` carries readable content; ``error.code`` is one of
NEED_SETUP, NEED_LOGIN, PLATFORM_BLOCKED, TIMEOUT, RATE_LIMITED, ...
"""
from __future__ import annotations

import contextlib
import html
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

REPORT_SCHEMA = "trailhead.comparative/2"

#: Wire format for the killable Trailhead worker subprocess.
WORKER_SCHEMA = "trailhead.comparative.worker/1"
WORKER_MODULE = "hermes_trailhead.comparative"
WORKER_FLAG = "--worker"

#: Existing extract.py switch: disables media-download ASR for this process.
#: A public comparison sets it so a case can never bill a transcription.
ASR_DISABLE_ENV = "TRAILHEAD_DISABLE_ASR"

#: Characters of *cleaned* text required before a case counts as evidence.
DEFAULT_MIN_CHARS = 200

#: Default per-side timeout in seconds.
DEFAULT_TIMEOUT = 30

#: Hits pulled for question-shaped cases (both sides search, same scope).
DEFAULT_SEARCH_LIMIT = 3

CaseKind = Literal["url", "question"]
EvidenceRequirement = Literal["page_text", "transcript"]
CaseStatus = Literal[
    "ok",
    "empty",
    "blocked",
    "error",
    "timeout",
    "unavailable",
    "not_run",
]
EvidenceVerdict = Literal[
    "evidence", "thin", "login_wall", "markup_heavy", "chrome_heavy", "empty"
]

#: Statuses that mean the tool was never actually exercised on that case.
NOT_EXERCISED = frozenset({"unavailable", "not_run"})


@dataclass(frozen=True)
class Case:
    """One explicit, repeatable benchmark case.

    ``prompt`` is the URL or question. ``agent_reach_command`` is the argv
    template (after the executable) that requests the *same outcome* from Agent
    Reach; ``{prompt}`` is substituted. ``trailhead_lane`` scopes question cases
    so both tools search the same surface.
    """

    id: str
    kind: CaseKind
    family: str
    prompt: str
    agent_reach_command: tuple[str, ...]
    evidence_requirement: EvidenceRequirement = "page_text"
    trailhead_lane: str = "web"
    requires_auth: bool = False
    auth_note: str = ""
    min_chars: int = DEFAULT_MIN_CHARS
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def ar_argv(self) -> list[str]:
        """Rendered Agent Reach arguments (without executable/timeout)."""
        return [part.replace("{prompt}", self.prompt) for part in self.agent_reach_command]


#: Fixture manifest. Public cases need no login, cookie, token, or account.
#: Auth-shaped cases are disclosed and skipped unless explicitly enabled.
CASES: tuple[Case, ...] = (
    Case(
        id="docs-python-typing",
        kind="url",
        family="docs",
        prompt="https://docs.python.org/3/library/typing.html",
        agent_reach_command=("read", "{prompt}"),
        notes="Canonical documentation page; both tools asked for page text.",
    ),
    Case(
        id="github-requests-readme",
        kind="url",
        family="github",
        prompt="https://github.com/psf/requests",
        agent_reach_command=("github", "read", "{prompt}"),
        notes="Repository page; both tools asked for the repository README/facts.",
    ),
    Case(
        id="web-wikipedia-http",
        kind="url",
        family="web",
        prompt="https://en.wikipedia.org/wiki/HTTP",
        agent_reach_command=("read", "{prompt}"),
        notes="Plain public article; the low-drama baseline.",
    ),
    Case(
        id="forum-v2ex-topic",
        kind="url",
        family="v2ex",
        prompt="https://www.v2ex.com/t/1252479",
        agent_reach_command=("v2ex", "read", "{prompt}"),
        notes="Public forum topic; both tools asked for the topic and replies.",
    ),
    Case(
        id="forum-v2ex-node",
        kind="url",
        family="v2ex",
        prompt="https://www.v2ex.com/go/python",
        agent_reach_command=("v2ex", "node", "python"),
        notes=(
            "Node listing. Agent Reach is asked for `v2ex node python` (its node "
            "action), not `read`, which upstream rejects for node URLs. Trailhead "
            "reads the node page and the cleaned listing is assessed as evidence."
        ),
    ),
    Case(
        id="video-youtube-transcript",
        kind="url",
        family="youtube",
        prompt="https://www.youtube.com/watch?v=aircAruvnKk",
        agent_reach_command=("youtube", "subtitle", "{prompt}"),
        evidence_requirement="transcript",
        min_chars=200,
        notes=(
            "Requested outcome is spoken subtitle text. Agent Reach is asked for "
            "`youtube subtitle`; a metadata-only `read` would not satisfy this case."
        ),
    ),
    Case(
        id="question-typing-protocol",
        kind="question",
        family="web",
        prompt="What does typing.Protocol require for structural subtyping?",
        agent_reach_command=("web", "search", "{prompt}"),
        trailhead_lane="web",
        min_chars=200,
        notes=(
            "Both sides search the open web only (Trailhead lane=web, Agent Reach "
            "web search). An all-lane Trailhead sweep would be a different scope "
            "and is deliberately not used."
        ),
    ),
    Case(
        id="instagram-profile-session-tier",
        kind="url",
        family="instagram",
        prompt="https://www.instagram.com/nasa/",
        agent_reach_command=("instagram", "profile", "nasa"),
        requires_auth=True,
        auth_note=(
            "Instagram profile metadata needs a login upstream; Trailhead needs its "
            "session tier and Agent Reach needs `agent-reach login instagram`."
        ),
        notes="Skipped by default; explicit --include-auth only.",
    ),
    Case(
        id="facebook-page-session-tier",
        kind="url",
        family="facebook",
        prompt="https://www.facebook.com/nasa",
        agent_reach_command=("facebook", "profile", "nasa"),
        requires_auth=True,
        auth_note=(
            "Facebook page reads go through Trailhead's session tier; Agent Reach "
            "needs `agent-reach login facebook`."
        ),
        notes="Skipped by default; no session tier is configured on the reference host.",
    ),
)

CASES_BY_ID: dict[str, Case] = {case.id: case for case in CASES}


# ── evidence assessment ──────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]{1,400}>")
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_CUE_RE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->", re.M)

#: Nav/shell phrases that indicate chrome rather than content.
_CHROME_PHRASES = (
    "skip to content",
    "skip to main content",
    "cookie policy",
    "privacy policy",
    "terms of service",
    "sign up",
    "sign in",
    "log in",
    "all rights reserved",
    "menu",
    "breadcrumb",
    "advertisement",
)

#: Phrases that indicate a wall rather than content. Checked only near the start.
_WALL_PHRASES = (
    "enable javascript",
    "javascript is disabled",
    "log in to continue",
    "sign in to continue",
    "you must be logged in",
    "verify you are human",
    "are you a robot",
    "subscribe to continue",
    "create an account to continue",
    "access denied",
    "captcha",
)


def cleaned_text(raw: str) -> str:
    """Strip scripts/styles/tags and collapse whitespace. No length games."""
    if not raw:
        return ""
    text = _SCRIPT_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def assess_evidence(
    raw: str,
    *,
    requirement: EvidenceRequirement = "page_text",
    min_chars: int = DEFAULT_MIN_CHARS,
    transcript_supplied: bool = False,
) -> dict:
    """Decide whether a response is evidence for the requested outcome.

    Returns raw length, cleaned length, markup ratio, wall flag, transcript
    detection, and one verdict. ``evidence_ok`` is true only for ``evidence``.
    """
    raw_chars = len(raw or "")
    cleaned = cleaned_text(raw)
    cleaned_chars = len(cleaned)
    markup_ratio = 0.0 if raw_chars == 0 else max(0.0, (raw_chars - cleaned_chars) / raw_chars)

    head = cleaned[:4000].lower()
    wall_hit = next((phrase for phrase in _WALL_PHRASES if phrase in head), "")
    # Chrome/nav detection: count distinct shell phrases in the opening text.
    chrome_signals = sum(1 for phrase in _CHROME_PHRASES if phrase in head[:1200])
    # A wall phrase inside otherwise substantial text (a docs page quoting
    # "access denied") is not a wall; require the page to be mostly wall.
    login_wall = bool(wall_hit) and cleaned_chars < max(4 * min_chars, 2000)

    cue_lines = len(_CUE_RE.findall(raw or ""))
    transcript_detected = transcript_supplied or cue_lines >= 3 or "webvtt" in (raw or "")[:500].lower()

    if requirement == "transcript":
        if not transcript_detected:
            verdict: EvidenceVerdict = "thin" if cleaned_chars >= min_chars else "empty"
            note = "no transcript material (cue markers or transcript payload) in the response"
        elif cleaned_chars < min_chars:
            verdict, note = "thin", f"transcript shorter than {min_chars} cleaned chars"
        else:
            verdict, note = "evidence", f"transcript material, {cleaned_chars} cleaned chars"
    elif cleaned_chars == 0:
        verdict, note = "empty", "no readable text after markup stripping"
    elif login_wall:
        verdict, note = "login_wall", f"login/verification wall ({wall_hit!r})"
    elif cleaned_chars < min_chars:
        verdict, note = "thin", f"{cleaned_chars} cleaned chars < {min_chars} required"
    elif chrome_signals >= 3 and cleaned_chars < 4 * min_chars:
        verdict = "chrome_heavy"
        note = f"{chrome_signals} nav/shell phrases dominate a short page ({cleaned_chars} cleaned chars)"
    elif markup_ratio > 0.5 and cleaned_chars < 4 * min_chars:
        # Only a *short* payload is rejected for being markup-heavy. A long page
        # whose cleaned text clears 4x the floor is accepted on cleaned length
        # alone; that says readable text came back, not that it is high quality.
        verdict = "markup_heavy"
        note = (
            f"{markup_ratio:.0%} of the payload was markup while cleaned text "
            f"stayed under {4 * min_chars} chars"
        )
    else:
        verdict, note = "evidence", f"{cleaned_chars} cleaned chars"

    return {
        "raw_chars": raw_chars,
        "cleaned_chars": cleaned_chars,
        "markup_ratio": round(markup_ratio, 3),
        "login_wall": login_wall,
        "chrome_signals": chrome_signals,
        "transcript_detected": transcript_detected,
        "cue_lines": cue_lines,
        "verdict": verdict,
        "note": note,
        "evidence_ok": verdict == "evidence",
    }


# ── sandbox ──────────────────────────────────────────────────────────────────

#: Any parent variable whose name contains one of these is not forwarded.
_SENSITIVE_MARKERS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "COOKIE",
    "SESSION",
    "CAMOFOX",
    "AUTH",
    "PROXY",
)

#: Variables needed for a subprocess to run at all.
_KEEP_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "PYTHONIOENCODING")


def package_root() -> Path:
    """Directory that must be importable for ``python -m hermes_trailhead``."""
    return Path(__file__).resolve().parents[1]


def build_sandbox(directory: str | Path | None = None) -> dict:
    """Create a throwaway HOME for both tools and the environment they may see.

    This is *environment* isolation, not a filesystem sandbox: nothing stops a
    subprocess from opening absolute paths outside ``root``, and a credential
    readable on disk elsewhere is not magically hidden. What it does guarantee
    is that no credential/session/cookie/proxy variable is inherited, and that
    both tools resolve their home/config/cache state inside the throwaway tree.
    """
    root = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="trailhead-compare-"))
    home = root / "home"
    agent_reach_home = root / "agent-reach-home"
    tmp = root / "tmp"
    for path in (home, agent_reach_home, tmp):
        path.mkdir(parents=True, exist_ok=True)
    env = {name: os.environ[name] for name in _KEEP_ENV if name in os.environ}
    env.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(home / ".hermes"),
            "TMPDIR": str(tmp),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "TRAILHEAD_AGENT_REACH_HOME": str(agent_reach_home),
            # A public comparison never bills an ASR call. This is extract.py's
            # existing switch, not a new mechanism.
            ASR_DISABLE_ENV: "1",
            # Keep the worker importable without inheriting the parent's path.
            "PYTHONPATH": str(package_root()),
        }
    )
    Path(env["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
    return {
        "root": str(root),
        "home": str(home),
        "agent_reach_home": str(agent_reach_home),
        "env": env,
        "reused": bool(directory),
        "quiet_environment": True,
    }


def is_sensitive_env(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in _SENSITIVE_MARKERS)


# ── killable subprocess execution ────────────────────────────────────────────


@dataclass(frozen=True)
class Completed:
    """Outcome of one wall-clock-bounded subprocess."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    wall_ms: int


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the child and anything it spawned; fall back to ``kill``."""
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    with contextlib.suppress(OSError):
        proc.kill()


def run_killable(
    argv: Sequence[str],
    *,
    timeout_s: float,
    env: Mapping[str, str] | None,
    cwd: str | Path | None = None,
    stdin_data: str | None = None,
) -> Completed:
    """Run ``argv`` with exactly one wall-clock budget, then kill it.

    Both benchmark sides go through this helper, so the timeout is the same
    observable rule for Trailhead and Agent Reach. ``shell=False`` always.
    """
    started = time.monotonic()
    kwargs: dict = {
        "stdin": subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": False,
        "env": dict(env) if env is not None else None,
        "cwd": str(cwd) if cwd is not None else None,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(list(argv), **kwargs)
    out = err = ""
    timed_out = False
    try:
        out, err = proc.communicate(stdin_data, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        with contextlib.suppress(subprocess.TimeoutExpired, ValueError, OSError):
            out, err = proc.communicate(timeout=5)
    return Completed(
        returncode=None if timed_out else proc.returncode,
        stdout=out or "",
        stderr=err or "",
        timed_out=timed_out,
        wall_ms=_ms(started),
    )


# ── result model ─────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    """One tool's measured attempt at one case. Observations only."""

    tool: str
    case_id: str
    status: CaseStatus
    duration_ms: int | None = None
    raw_chars: int = 0
    cleaned_chars: int = 0
    markup_ratio: float = 0.0
    evidence_verdict: EvidenceVerdict = "empty"
    evidence_note: str = ""
    chrome_signals: int = 0
    transcript_detected: bool = False
    item_count: int = 0
    backend: str = ""
    error: str = ""
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    preview: str = ""
    detail: str = ""
    freshness: str = "fresh"

    @property
    def exercised(self) -> bool:
        return self.status not in NOT_EXERCISED

    @property
    def evidence_ok(self) -> bool:
        return self.status == "ok" and self.evidence_verdict == "evidence"

    #: Backwards-compatible alias used by earlier callers/tests.
    @property
    def content_ok(self) -> bool:
        return self.evidence_ok

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["exercised"] = self.exercised
        payload["evidence_ok"] = self.evidence_ok
        payload["content_ok"] = self.content_ok
        return payload


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preview(text: str, limit: int = 240) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def _ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))


def _result_from_text(
    *,
    tool: str,
    case: Case,
    status: CaseStatus,
    text: str,
    duration_ms: int | None,
    transcript_supplied: bool = False,
    **extra,
) -> CaseResult:
    assessment = assess_evidence(
        text,
        requirement=case.evidence_requirement,
        min_chars=case.min_chars,
        transcript_supplied=transcript_supplied,
    )
    return CaseResult(
        tool=tool,
        case_id=case.id,
        status=status,
        duration_ms=duration_ms,
        raw_chars=assessment["raw_chars"],
        cleaned_chars=assessment["cleaned_chars"],
        markup_ratio=assessment["markup_ratio"],
        evidence_verdict=assessment["verdict"],
        evidence_note=assessment["note"],
        chrome_signals=assessment["chrome_signals"],
        transcript_detected=assessment["transcript_detected"],
        preview=_preview(text),
        **extra,
    )


# ── Trailhead side ───────────────────────────────────────────────────────────

#: Families whose extraction path may serve a locally cached transcript.
_CACHEABLE_FAMILIES = frozenset({"youtube", "tiktok", "instagram"})

#: Below this duration a cached transcript is the most likely explanation.
_CACHE_SUSPICIOUS_MS = 500


def transcript_cache_state() -> tuple[int, float]:
    """(file count, newest mtime) for Trailhead's local transcript cache."""
    try:
        from .paths import hermes_state_dir

        files = list((hermes_state_dir() / "trailhead-transcripts").glob("*.txt"))
    except Exception:
        return 0, 0.0
    newest = max((path.stat().st_mtime for path in files), default=0.0)
    return len(files), newest


def classify_freshness(
    family: str,
    status: str,
    duration_ms: int | None,
    before: tuple[int, float],
    after: tuple[int, float],
) -> tuple[str, str]:
    """Label a video-family read as fresh or possibly served from cache."""
    if family not in _CACHEABLE_FAMILIES or status != "ok" or duration_ms is None:
        return "fresh", ""
    if duration_ms < _CACHE_SUSPICIOUS_MS and after[1] <= before[1]:
        return (
            "possibly_cached",
            f"returned in {duration_ms}ms with no new transcript cache write "
            f"(files before={before[0]}, after={after[0]}); Trailhead caches transcripts "
            "in its state dir, so this may be a cached read rather than a fresh fetch",
        )
    return "fresh", ""


def _trailhead_transcript_chars(result) -> tuple[int, str]:
    """Transcript characters carried by an ExtractionResult, when present."""
    evidence = getattr(result, "video_evidence", None)
    if evidence is None:
        return 0, ""
    total = 0
    for attr in ("caption_transcript", "audio_transcript"):
        total += len(getattr(evidence, attr, "") or "")
    status = getattr(evidence, "caption_transcript_status", "") or ""
    return total, str(status)


def trailhead_worker_case(
    case: Case,
    timeout_s: float,
    *,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
) -> CaseResult:
    """In-process body of the Trailhead side; executed inside the worker process.

    This function is never called directly by ``run_compare``: the default path
    runs it in a killable subprocess (see ``trailhead_case_runner``) so a slow
    fetch cannot outlive the case budget. It is public because tests exercise it
    directly and because a caller that already owns a sandboxed process may use
    it. It performs no environment mutation of its own.
    """
    from .extract import extract_hits, extract_one
    from .search import execute_search

    started = time.monotonic()
    cache_before = (
        transcript_cache_state() if case.family in _CACHEABLE_FAMILIES else (0, 0.0)
    )
    if case.kind == "url":
        try:
            result = extract_one(case.prompt, timeout=int(max(1, timeout_s)))
        except Exception as exc:  # noqa: BLE001 - measured, never raised
            return CaseResult(
                tool="trailhead",
                case_id=case.id,
                status="error",
                duration_ms=_ms(started),
                error=f"{type(exc).__name__}: {exc}",
            )
        text = result.content or ""
        if result.status == "ok":
            status: CaseStatus = "ok" if text.strip() else "empty"
        elif result.status == "blocked":
            status = "blocked"
        elif result.status == "not_attempted":
            status = "not_run"
        else:
            status = "error"
        transcript_chars, transcript_status = _trailhead_transcript_chars(result)
        duration = _ms(started)
        freshness, freshness_note = classify_freshness(
            case.family, status, duration, cache_before, transcript_cache_state()
        )
        return _result_from_text(
            tool="trailhead",
            case=case,
            status=status,
            text=text,
            duration_ms=duration,
            transcript_supplied=transcript_chars >= case.min_chars,
            item_count=1 if text else 0,
            backend=result.source_type or "extract_one",
            error=result.error_message or "",
            detail="; ".join(
                part
                for part in (
                    freshness_note,
                    f"transcript_status={transcript_status}" if transcript_status else "",
                )
                if part
            ),
            freshness=freshness,
        )

    # Question case: search ONLY the declared lane so both tools share scope.
    try:
        run = execute_search(case.trailhead_lane, case.prompt, live=False, limit=search_limit)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="error",
            duration_ms=_ms(started),
            error=f"{type(exc).__name__}: {exc}",
        )

    hits = tuple(hit for execution in run.executions for hit in execution.hits)
    errors = [
        f"{execution.platform}: {execution.error}"
        for execution in run.executions
        if execution.error
    ]
    texts: list[str] = []
    if hits:
        for extracted in extract_hits(hits, limit=search_limit, timeout=int(max(1, timeout_s))):
            if extracted.extraction.status == "ok" and extracted.extraction.content:
                texts.append(extracted.extraction.content)
    joined = "\n\n".join(texts)
    status = "ok" if texts else ("empty" if hits else "error")
    return _result_from_text(
        tool="trailhead",
        case=case,
        status=status,
        text=joined,
        duration_ms=_ms(started),
        item_count=len(hits),
        backend=f"search:{case.trailhead_lane}+extract",
        error="; ".join(errors[:3]),
        detail=f"{len(texts)} of {len(hits)} hits produced readable text" if hits else "",
    )


# ── Trailhead worker subprocess (killable, JSON in/out) ─────────────────────


def trailhead_worker_argv() -> list[str]:
    """argv for the stdlib worker: ``<python> -m hermes_trailhead.comparative``.

    No shell, no string interpolation: the case travels as JSON on stdin.
    """
    return [sys.executable or "python3", "-m", WORKER_MODULE, WORKER_FLAG]


def worker_request(case: Case, *, timeout_s: float, search_limit: int) -> dict:
    """One case, serialized for the worker process."""
    return {
        "schema": WORKER_SCHEMA,
        "case": case.to_dict(),
        "timeout_s": float(timeout_s),
        "search_limit": int(search_limit),
    }


_RESULT_FIELDS = {item.name for item in fields(CaseResult)}


def case_from_dict(data: Mapping) -> Case:
    """Rebuild a ``Case`` from its manifest dict (worker side)."""
    missing = {"id", "kind", "family", "prompt", "agent_reach_command"} - set(data)
    if missing:
        raise ValueError("missing case fields: " + ", ".join(sorted(missing)))
    return Case(
        id=str(data["id"]),
        kind=data["kind"],  # type: ignore[arg-type]
        family=str(data["family"]),
        prompt=str(data["prompt"]),
        agent_reach_command=tuple(str(part) for part in data["agent_reach_command"]),
        evidence_requirement=data.get("evidence_requirement", "page_text"),  # type: ignore[arg-type]
        trailhead_lane=str(data.get("trailhead_lane", "web")),
        requires_auth=bool(data.get("requires_auth", False)),
        auth_note=str(data.get("auth_note", "")),
        min_chars=int(data.get("min_chars", DEFAULT_MIN_CHARS)),
        notes=str(data.get("notes", "")),
    )


def case_result_from_dict(
    data: Mapping,
    *,
    tool: str = "trailhead",
    case_id: str = "",
) -> CaseResult:
    """Rebuild a ``CaseResult`` from the worker's JSON payload.

    ``tool``/``case_id`` are forced by the parent: a worker cannot relabel
    itself or claim a different case.
    """
    if not isinstance(data, Mapping):
        raise ValueError("worker result is not an object")
    payload = {name: data[name] for name in _RESULT_FIELDS if name in data}
    payload["tool"] = tool
    if case_id:
        payload["case_id"] = case_id
    return CaseResult(**payload)


def worker_payload(request: Mapping) -> dict:
    """Body of the worker process: one request dict in, one response dict out.

    Stdout is redirected while the case runs so an import-time print or a
    third-party warning cannot corrupt the JSON contract.
    """
    if not isinstance(request, Mapping):
        return {"schema": WORKER_SCHEMA, "ok": False, "error": "request is not a JSON object"}
    try:
        case = case_from_dict(request.get("case") or {})
        timeout_s = float(request.get("timeout_s", DEFAULT_TIMEOUT))
        search_limit = int(request.get("search_limit", DEFAULT_SEARCH_LIMIT))
    except (TypeError, ValueError, KeyError) as exc:
        return {
            "schema": WORKER_SCHEMA,
            "ok": False,
            "error": f"bad worker request: {type(exc).__name__}: {exc}",
        }
    noise = io.StringIO()
    try:
        with contextlib.redirect_stdout(noise):
            result = trailhead_worker_case(case, timeout_s, search_limit=search_limit)
    except Exception as exc:  # noqa: BLE001 - reported across the wire, never raised
        return {"schema": WORKER_SCHEMA, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"schema": WORKER_SCHEMA, "ok": True, "result": result.to_dict()}


def _last_json_object(text: str) -> dict | None:
    """Last JSON object in ``text`` (whole payload first, then line by line)."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    for candidate in (stripped, *reversed(stripped.splitlines())):
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def parse_worker_output(stdout: str) -> tuple[dict, str]:
    """Parse the worker's single JSON response."""
    text = (stdout or "").strip()
    if not text:
        return {}, "worker produced no output"
    payload = _last_json_object(text)
    if payload is None:
        return {}, f"worker stdout is not JSON: {_preview(text, 120)}"
    if payload.get("schema") != WORKER_SCHEMA:
        return {}, f"unexpected worker schema {payload.get('schema')!r}"
    return payload, ""


def trailhead_case_runner(
    case: Case,
    timeout_s: float,
    *,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
    env: Mapping[str, str] | None = None,
    worker_argv: Sequence[str] | None = None,
) -> CaseResult:
    """Run one case in a killable Trailhead worker subprocess.

    The worker is the stdlib interpreter running
    ``python -m hermes_trailhead.comparative --worker``: one JSON request on
    stdin, one JSON response on stdout, ``shell=False``. If the case budget
    expires the parent kills the whole process group, which is exactly the
    wall-clock rule Agent Reach gets.
    """
    argv = list(worker_argv) if worker_argv else trailhead_worker_argv()
    if env is None:
        # Direct callers get the same isolation as run_compare; a bare call must
        # not hand the worker the operator's real environment.
        env = build_sandbox()["env"]
    request = worker_request(case, timeout_s=timeout_s, search_limit=search_limit)
    try:
        completed = run_killable(
            argv,
            timeout_s=timeout_s,
            env=env,
            cwd=package_root(),
            stdin_data=json.dumps(request),
        )
    except FileNotFoundError:
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="unavailable",
            error=f"worker interpreter not found: {argv[0]}",
            command=argv,
        )
    except OSError as exc:
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            command=argv,
        )

    if completed.timed_out:
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="timeout",
            duration_ms=completed.wall_ms,
            error=(
                f"worker killed after {int(timeout_s)}s wall timeout "
                "(same budget as Agent Reach)"
            ),
            command=argv,
        )

    payload, parse_error = parse_worker_output(completed.stdout)
    if parse_error:
        stderr_tail = _preview(completed.stderr.strip(), 200)
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="error",
            duration_ms=completed.wall_ms,
            exit_code=completed.returncode,
            error=parse_error + (f" (stderr: {stderr_tail})" if stderr_tail else ""),
            command=argv,
        )
    if not payload.get("ok", False):
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="error",
            duration_ms=completed.wall_ms,
            exit_code=completed.returncode,
            error=f"worker error: {payload.get('error') or 'unknown'}",
            command=argv,
        )

    try:
        result = case_result_from_dict(
            payload.get("result") or {}, tool="trailhead", case_id=case.id
        )
    except (TypeError, ValueError) as exc:
        return CaseResult(
            tool="trailhead",
            case_id=case.id,
            status="error",
            duration_ms=completed.wall_ms,
            exit_code=completed.returncode,
            error=f"malformed worker result: {type(exc).__name__}: {exc}",
            command=argv,
        )

    internal = result.duration_ms
    # Parent wall clock is the comparable number for both sides; the worker's
    # in-process measurement is kept as context.
    result.duration_ms = completed.wall_ms
    wall_note = f"worker wall {completed.wall_ms}ms"
    if internal is not None:
        wall_note += f" (in-process {internal}ms)"
    result.detail = "; ".join(part for part in (result.detail, wall_note) if part)
    result.command = argv
    result.exit_code = completed.returncode
    return result


def _worker_cli(argv: Sequence[str] | None = None) -> int:
    """``python -m hermes_trailhead.comparative --worker`` entry point."""
    args = list(sys.argv[1:] if argv is None else argv)
    if WORKER_FLAG not in args:
        sys.stderr.write(f"usage: python -m {WORKER_MODULE} {WORKER_FLAG} < request.json\n")
        return 2
    raw = sys.stdin.read()
    try:
        request = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        sys.stdout.write(
            json.dumps({"schema": WORKER_SCHEMA, "ok": False, "error": f"invalid JSON request: {exc}"})
            + "\n"
        )
        return 2
    sys.stdout.write(json.dumps(worker_payload(request)) + "\n")
    return 0


# ── Agent Reach side ─────────────────────────────────────────────────────────


def resolve_agent_reach(executable: str | None = None) -> str | None:
    """Return the Agent Reach executable path, or ``None`` when unavailable.

    Resolution order: explicit path, ``TRAILHEAD_AGENT_REACH_BIN``, then PATH.
    This only looks for an installed CLI; nothing is installed or configured.
    """
    if executable:
        return executable if Path(executable).exists() else None
    pinned = (os.environ.get("TRAILHEAD_AGENT_REACH_BIN") or "").strip()
    if pinned:
        try:
            from .reach_backend import discover_agent_reach

            availability = discover_agent_reach()
            if availability.found and availability.path:
                return availability.path
        except Exception:
            pass
        return pinned if Path(pinned).exists() else None
    return shutil.which("agent-reach")


def agent_reach_command(case: Case, executable: str, *, timeout_s: float = DEFAULT_TIMEOUT) -> list[str]:
    """Build the argv array requesting the SAME outcome from Agent Reach.

    Kept as a list so the call can never go through a shell. Case templates are
    validated to contain no option-like token, so no ``--`` terminator is
    needed and the upstream CLI sees plain positionals.
    """
    rendered = case.ar_argv()
    flag_like = [part for part in rendered if part.startswith("-")]
    if flag_like:
        raise ValueError(
            f"case {case.id} has option-like arguments {flag_like}; "
            "declare them explicitly instead of smuggling flags through positionals"
        )
    return [executable, *rendered, "--timeout", str(int(timeout_s))]


def parse_agent_reach_output(stdout: str, returncode: int) -> tuple[dict, str]:
    """Parse Agent Reach's single-JSON-object stdout."""
    text = (stdout or "").strip()
    if not text:
        return {}, f"no output (exit {returncode})"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return {}, f"stdout is not JSON (exit {returncode}): {_preview(text, 120)}"
    if not isinstance(payload, dict):
        return {}, "stdout JSON is not an object"
    return payload, ""


_STATUS_BY_CODE = {
    "NEED_SETUP": "unavailable",
    "NEED_LOGIN": "blocked",
    "PLATFORM_BLOCKED": "blocked",
    "TIMEOUT": "timeout",
    "RATE_LIMITED": "error",
    "UPSTREAM_BROKEN": "error",
    "NOT_FOUND": "error",
    "BAD_INPUT": "error",
}


def agent_reach_case_runner(
    case: Case,
    timeout_s: float,
    executable: str,
    *,
    env: Mapping[str, str] | None = None,
) -> CaseResult:
    """Run one case by invoking the installed Agent Reach CLI as a subprocess."""
    argv = agent_reach_command(case, executable, timeout_s=timeout_s)
    if env is None:
        env = build_sandbox()["env"]
    try:
        completed = run_killable(argv, timeout_s=timeout_s, env=env)
    except FileNotFoundError:
        return CaseResult(
            tool="agent_reach",
            case_id=case.id,
            status="unavailable",
            error=f"executable not found: {executable}",
            command=argv,
        )
    except OSError as exc:
        return CaseResult(
            tool="agent_reach",
            case_id=case.id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            command=argv,
        )

    if completed.timed_out:
        return CaseResult(
            tool="agent_reach",
            case_id=case.id,
            status="timeout",
            duration_ms=completed.wall_ms,
            error=f"no result within {int(timeout_s)}s",
            command=argv,
        )

    duration = completed.wall_ms
    returncode = completed.returncode or 0
    payload, parse_error = parse_agent_reach_output(completed.stdout, returncode)
    if parse_error:
        return CaseResult(
            tool="agent_reach",
            case_id=case.id,
            status="error",
            duration_ms=duration,
            exit_code=completed.returncode,
            error=parse_error,
            command=argv,
        )

    error_block = payload.get("error") or {}
    code = str(error_block.get("code") or "").upper()
    if not payload.get("ok", False):
        status: CaseStatus = _STATUS_BY_CODE.get(code, "error")  # type: ignore[assignment]
        return CaseResult(
            tool="agent_reach",
            case_id=case.id,
            status=status,
            duration_ms=duration,
            exit_code=completed.returncode,
            backend=str(payload.get("backend") or ""),
            error=f"{code or 'ERROR'}: {error_block.get('message') or 'no message'}",
            command=argv,
        )

    items = payload.get("items") or []
    texts = [
        str(item["text"])
        for item in items
        if isinstance(item, dict) and item.get("text")
    ]
    joined = "\n\n".join(texts)
    action = payload.get("action") or (case.ar_argv()[1] if len(case.ar_argv()) > 1 else "")
    return _result_from_text(
        tool="agent_reach",
        case=case,
        status="ok" if joined.strip() else "empty",
        text=joined,
        duration_ms=duration,
        transcript_supplied=bool(case.evidence_requirement == "transcript" and action == "subtitle"),
        item_count=len(items),
        exit_code=completed.returncode,
        backend=str(payload.get("backend") or ""),
        command=argv,
        detail=f"{len(texts)} of {len(items)} items carried text" if items else "",
    )


def agent_reach_version(
    executable: str, *, timeout_s: float = 10, env: Mapping[str, str] | None = None
) -> str:
    """Best-effort version string for the report header (never raises)."""
    try:
        completed = run_killable([executable, "version"], timeout_s=timeout_s, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.timed_out:
        return ""
    payload, _ = parse_agent_reach_output(completed.stdout, completed.returncode or 0)
    result = payload.get("result")
    if isinstance(result, dict) and result.get("version"):
        return str(result["version"])
    return ""


# ── Comparison ───────────────────────────────────────────────────────────────


@dataclass
class CaseComparison:
    case_id: str
    verdict: str
    reason: str
    trailhead: CaseResult
    agent_reach: CaseResult

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "trailhead": self.trailhead.to_dict(),
            "agent_reach": self.agent_reach.to_dict(),
        }


def compare_case(case: Case, trailhead: CaseResult, agent_reach: CaseResult) -> CaseComparison:
    """Describe the observed per-case outcome. No ranking, no grading.

    Verdicts:
      - ``both_evidence``: both returned evidence for the requested outcome.
      - ``trailhead_only_evidence`` / ``agent_reach_only_evidence``.
      - ``neither_evidence``: both exercised, neither produced evidence.
      - ``not_comparable``: a side was never exercised.
    """
    if not trailhead.exercised or not agent_reach.exercised:
        missing = [
            f"{res.tool}={res.status}"
            for res in (trailhead, agent_reach)
            if not res.exercised
        ]
        return CaseComparison(
            case_id=case.id,
            verdict="not_comparable",
            reason="tool not exercised: " + ", ".join(missing),
            trailhead=trailhead,
            agent_reach=agent_reach,
        )
    t_ok = trailhead.evidence_ok
    a_ok = agent_reach.evidence_ok
    if t_ok and a_ok:
        verdict = "both_evidence"
        reason = "both returned evidence for the requested outcome"
    elif t_ok:
        verdict = "trailhead_only_evidence"
        reason = f"trailhead evidence; agent_reach={agent_reach.evidence_verdict} ({agent_reach.status})"
    elif a_ok:
        verdict = "agent_reach_only_evidence"
        reason = f"agent_reach evidence; trailhead={trailhead.evidence_verdict} ({trailhead.status})"
    else:
        verdict = "neither_evidence"
        reason = (
            f"neither produced evidence "
            f"(trailhead={trailhead.evidence_verdict}/{trailhead.cleaned_chars} cleaned chars, "
            f"agent_reach={agent_reach.evidence_verdict}/{agent_reach.cleaned_chars})"
        )
    return CaseComparison(case.id, verdict, reason, trailhead, agent_reach)


def _select_cases(
    case_ids: Sequence[str] | None,
    *,
    include_auth: bool,
) -> tuple[list[Case], list[Case]]:
    if case_ids:
        unknown = [cid for cid in case_ids if cid not in CASES_BY_ID]
        if unknown:
            raise KeyError("unknown case ids: " + ", ".join(sorted(unknown)))
        wanted = [CASES_BY_ID[cid] for cid in case_ids]
    else:
        wanted = list(CASES)
    selected: list[Case] = []
    skipped: list[Case] = []
    for case in wanted:
        if case.requires_auth and not include_auth:
            skipped.append(case)
        else:
            selected.append(case)
    return selected, skipped


def _auth_block(case: Case, *, skipped: bool) -> dict | None:
    """Explicit disclosure for auth-shaped cases.

    Neither branch ever claims an authenticated comparison: an ``--include-auth``
    case runs in the empty sandbox HOME, so it is an unauthenticated *attempt*
    with no stored session, cookie, or consent config.
    """
    if not case.requires_auth:
        return None
    if skipped:
        return {
            "mode": "skipped",
            "configured": False,
            "note": (
                "auth-shaped case not run; --include-auth would only make an "
                "unauthenticated attempt, never an authenticated comparison"
            ),
        }
    return {
        "mode": "unauthenticated_attempt",
        "configured": False,
        "note": (
            "attempted in the empty sandbox HOME: no stored session, cookie, or consent "
            "config is used, so this is NOT an authenticated comparison; a blocked result "
            "is expected and says nothing about Trailhead's session tier"
        ),
    }


def run_compare(
    *,
    case_ids: Sequence[str] | None = None,
    include_auth: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT,
    agent_reach: str | None = None,
    with_agent_reach: bool = True,
    trailhead_runner: Callable[..., CaseResult] | None = None,
    agent_reach_runner: Callable[..., CaseResult] | None = None,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
    sandbox_dir: str | None = None,
    trailhead_worker: Sequence[str] | None = None,
) -> dict:
    """Run the selected cases against both sides with one shared wall budget.

    Both sides are killable subprocesses by default: the Trailhead worker runs
    ``python -m hermes_trailhead.comparative --worker`` and Agent Reach runs its
    CLI, each with ``timeout_s`` as a hard wall limit enforced by killing the
    process group. The environment is built explicitly and passed to both — no
    global ``os.environ`` mutation, and no operator credential/session/proxy
    variable is inherited. This is environment isolation, not a filesystem or
    OS sandbox.

    ``sandbox_dir`` reuses an existing environment tree (a labeled warm run).
    Injected runners are test-only and are labeled ``injected`` in the report.
    No aggregate winner is computed — see ``summary["aggregate_ranking"]``.
    """
    selected, skipped = _select_cases(case_ids, include_auth=include_auth)
    trailhead_injected = trailhead_runner is not None
    agent_reach_injected = agent_reach_runner is not None
    trailhead_runner = trailhead_runner or trailhead_case_runner
    agent_reach_runner = agent_reach_runner or agent_reach_case_runner

    sandbox = build_sandbox(sandbox_dir)
    env = sandbox["env"]
    executable = resolve_agent_reach(agent_reach) if with_agent_reach else None
    unavailable_reason = ""
    if with_agent_reach and executable is None:
        unavailable_reason = (
            f"agent-reach not found ({agent_reach or 'PATH lookup'}); "
            "no comparison is possible on this host"
        )

    cases_out: list[dict] = []
    comparisons: list[CaseComparison] = []

    for case in selected:
        runner_kwargs: dict = {"search_limit": search_limit, "env": env}
        if trailhead_worker is not None and not trailhead_injected:
            runner_kwargs["worker_argv"] = trailhead_worker
        t_result = trailhead_runner(case, timeout_s, **runner_kwargs)
        if not with_agent_reach:
            a_result = CaseResult(
                tool="agent_reach",
                case_id=case.id,
                status="not_run",
                detail="Agent Reach side disabled for this run (--no-agent-reach)",
            )
        elif executable is None:
            a_result = CaseResult(
                tool="agent_reach",
                case_id=case.id,
                status="unavailable",
                detail=unavailable_reason,
            )
        else:
            a_result = agent_reach_runner(case, timeout_s, executable, env=env)

        comparison = compare_case(case, t_result, a_result)
        comparisons.append(comparison)
        cases_out.append(
            {
                "case": case.to_dict(),
                "auth": _auth_block(case, skipped=False),
                "comparison": comparison.to_dict(),
            }
        )

    version = agent_reach_version(executable, env=env) if executable else ""

    for case in skipped:
        cases_out.append(
            {
                "case": case.to_dict(),
                "auth": _auth_block(case, skipped=True),
                "comparison": None,
                "skip": {
                    "status": "not_run",
                    "reason": "auth case skipped; enable explicitly with --include-auth",
                },
            }
        )

    auth_attempts = sum(
        1 for comparison in comparisons if CASES_BY_ID[comparison.case_id].requires_auth
    )
    summary = _summarize(
        comparisons,
        skipped,
        executable,
        unavailable_reason,
        with_agent_reach,
        auth_attempts=auth_attempts,
    )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": _now(),
        "environment": {
            "host_timeout_s": timeout_s,
            "wall_timeout_s": timeout_s,
            "wall_timeout_scope": (
                "one wall-clock budget per case for each side; a side that exceeds it is "
                "killed (whole process group) and reported status=timeout"
            ),
            "search_limit": search_limit,
            "execution": {
                "trailhead": "injected" if trailhead_injected else "subprocess",
                "agent_reach": (
                    "not_run"
                    if not with_agent_reach
                    else ("injected" if agent_reach_injected else "subprocess")
                ),
                "trailhead_worker": (
                    ""
                    if trailhead_injected
                    else " ".join(trailhead_worker or trailhead_worker_argv())
                ),
                "note": (
                    "subprocess = killable process with the shared wall timeout; "
                    "injected = test-only in-process runner, no wall timeout"
                ),
            },
            "isolation": {
                "kind": "environment-only",
                "temp_home": True,
                "env_credentials_dropped": True,
                "filesystem_sandbox": False,
                "credential_proof": False,
                "note": (
                    "both tools get a throwaway HOME/HERMES_HOME/TMPDIR plus an environment "
                    "with credential-, session-, cookie-, and proxy-shaped variables removed; "
                    "this is not a filesystem or OS sandbox — a process can still read "
                    "absolute paths outside the sandbox, so it is not credential-proof"
                ),
            },
            "billable_asr": {
                "disabled": True,
                "env": f"{ASR_DISABLE_ENV}=1",
                "note": (
                    "extract.py's existing switch; a public comparison never invokes "
                    "paid/key-consuming transcription"
                ),
            },
            "sandbox": {
                "root": sandbox["root"],
                "home": sandbox["home"],
                "agent_reach_home": sandbox["agent_reach_home"],
                "reused": sandbox["reused"],
                "run_kind": "warm" if sandbox["reused"] else "cold",
                "credentials_forwarded": False,
                "session_vars_forwarded": False,
                "filesystem_sandbox": False,
            },
            "agent_reach": {
                "requested": with_agent_reach,
                "available": executable is not None,
                "path": executable or "",
                "version": version,
            },
        },
        "methodology": {
            "matched_outcomes": True,
            "case_command_mapping": {
                "trailhead_url": (
                    "killable worker subprocess (python -m hermes_trailhead.comparative "
                    "--worker) -> extract.extract_one"
                ),
                "trailhead_question": (
                    "killable worker subprocess -> search.execute_search(<case lane>) + "
                    "extract.extract_hits"
                ),
                "agent_reach": "killable subprocess: case.agent_reach_command, e.g. youtube subtitle / v2ex node",
            },
            "timeout_rule": (
                "both sides get the same wall-clock budget per case and are killed with "
                "their process group when it expires; per-fetch overrides inside a tool "
                "cannot extend the case budget"
            ),
            "evidence_rule": (
                "evidence_ok requires status=ok and cleaned (markup-stripped) text at or "
                "above the case floor. A login/verification wall or a nav-shell page is "
                "rejected. A payload that is more than half markup is rejected only while "
                "its cleaned text stays under 4x the floor; above that threshold a long "
                "page is accepted on cleaned text length alone, which measures that "
                "readable text came back — not relevance or content quality. Transcript "
                "cases additionally require transcript material"
            ),
            "aggregate_ranking": None,
            "ranking_note": (
                "No aggregate winner is computed. Cases differ in scope, corpus, and "
                "access path; per-case outcomes are the only output."
            ),
            "cache_rule": (
                "each run uses a throwaway HOME/HERMES_HOME (cold); reuse a sandbox to "
                "measure a warm run, reported as run_kind=warm"
            ),
            "limitations": [
                "One host, one moment: network conditions differ between runs and hosts.",
                "Cleaned length is not quality; a long page can beat a short canonical answer.",
                "Markup-heavy verdicts apply only to short payloads; a long page with heavy markup is still 'evidence' if its cleaned text clears the floor.",
                "Question cases search the same lane on both sides, but result ranking still differs by engine.",
                "Agent Reach cases run through its own backends (gh, yt-dlp, exa, ...), so upstream drift affects only that side.",
                "Both sides get a throwaway HOME/config and a stripped environment, which is not a filesystem or OS sandbox and not proof that a readable credential outside the sandbox was unused.",
                "Auth-shaped cases are skipped by default; with --include-auth they are unauthenticated attempts in an empty HOME, not authenticated comparisons, and no session or consent config is used.",
                "A blocked/errored side is a real outcome for this case, not proof of general failure.",
                "Markup stripping is heuristic; a page whose readable text is embedded in scripts may be undercounted.",
            ],
        },
        "summary": summary,
        "cases": cases_out,
    }


def _summarize(
    comparisons: Sequence[CaseComparison],
    skipped: Sequence[Case],
    executable: str | None,
    unavailable_reason: str,
    with_agent_reach: bool,
    *,
    auth_attempts: int = 0,
) -> dict:
    counts: dict[str, int] = {}
    for comparison in comparisons:
        counts[comparison.verdict] = counts.get(comparison.verdict, 0) + 1

    both_exercised = [
        c for c in comparisons if c.trailhead.exercised and c.agent_reach.exercised
    ]
    trailhead_evidence = sum(1 for c in comparisons if c.trailhead.evidence_ok)
    agent_reach_evidence = sum(1 for c in comparisons if c.agent_reach.evidence_ok)
    possibly_cached = sum(
        1 for c in comparisons if c.trailhead.freshness == "possibly_cached"
    )

    if not with_agent_reach:
        note = "Agent Reach side disabled (not_run); nothing is compared."
    elif executable is None:
        note = unavailable_reason or "Agent Reach unavailable; nothing is compared."
    else:
        note = (
            "per-case outcomes only; no aggregate winner is computed from case counts, "
            "content length, or scope-mixed cases"
        )

    return {
        "cases_run": len(comparisons),
        "cases_skipped_auth": len(skipped),
        "cases_auth_unauthenticated": auth_attempts,
        "cases_both_exercised": len(both_exercised),
        "verdict_counts": counts,
        "trailhead_evidence_cases": trailhead_evidence,
        "agent_reach_evidence_cases": agent_reach_evidence,
        "trailhead_possibly_cached_cases": possibly_cached,
        "aggregate_ranking": None,
        "ranking_note": note,
    }


# ── Report writing and formatting ─────────────────────────────────────────────


def write_report(report: dict, path: str | Path) -> str:
    """Write the report JSON to ``path`` (caller chooses the target)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return str(target)


def _fmt_side(row: dict) -> str:
    bits = [str(row.get("status"))]
    if row.get("duration_ms") is not None:
        bits.append(f"{row['duration_ms']}ms")
    if row.get("cleaned_chars"):
        bits.append(f"{row['cleaned_chars']} cleaned chars")
    if row.get("raw_chars") and row.get("raw_chars") != row.get("cleaned_chars"):
        bits.append(f"raw {row['raw_chars']}")
    bits.append(str(row.get("evidence_verdict")))
    if row.get("error"):
        bits.append(str(row["error"])[:90])
    if row.get("freshness") == "possibly_cached":
        bits.append("possibly cached")
    return " | ".join(bits)


def format_compare_text(report: dict) -> str:
    summary = report["summary"]
    env = report["environment"]
    sandbox = env.get("sandbox") or {}
    execution = env.get("execution") or {}
    isolation = env.get("isolation") or {}
    billable = env.get("billable_asr") or {}
    lines = ["Hermes Trailhead — head-to-head case benchmark (measured, not graded)", ""]
    lines.append(f"Generated: {report['generated_at']}")
    lines.append(
        f"Sandbox: {sandbox.get('root')} ({sandbox.get('run_kind')}; "
        "credentials not forwarded)"
    )
    lines.append(
        "Execution: "
        f"trailhead={execution.get('trailhead', '?')} "
        f"agent_reach={execution.get('agent_reach', '?')} "
        f"(one wall budget per case: {env.get('wall_timeout_s', '?')}s)"
    )
    lines.append(
        f"Isolation: {isolation.get('kind', 'environment-only')} — temp HOME/config, "
        "credential vars dropped; not a filesystem or OS sandbox"
    )
    if billable.get("disabled"):
        lines.append(f"Billable ASR: disabled ({billable.get('env')})")
    ar = env["agent_reach"]
    if ar["available"]:
        lines.append(f"Agent Reach: {ar['path']} {ar['version']}".rstrip())
    elif ar["requested"]:
        lines.append("Agent Reach: unavailable (CLI not installed; no comparison possible)")
    else:
        lines.append("Agent Reach: not run (--no-agent-reach)")
    lines.append("")

    for entry in report["cases"]:
        case = entry["case"]
        auth = " [auth-gated]" if case["requires_auth"] else ""
        lines.append(f"{case['id']} ({case['kind']}, {case['family']}){auth}")
        auth_block = entry.get("auth") or {}
        if auth_block:
            lines.append(f"  auth: {auth_block.get('mode')} — {auth_block.get('note')}")
        lines.append(f"  prompt: {case['prompt']}")
        lines.append(f"  requested: {' / '.join(case['agent_reach_command'])}")
        comparison = entry.get("comparison")
        if comparison is None:
            skip = entry.get("skip") or {}
            lines.append(f"  skipped: {skip.get('reason', 'not run')}")
            lines.append("")
            continue
        lines.append(f"  trailhead   : {_fmt_side(comparison['trailhead'])}")
        lines.append(f"  agent_reach : {_fmt_side(comparison['agent_reach'])}")
        if comparison["trailhead"].get("evidence_note"):
            lines.append(f"    trailhead evidence: {comparison['trailhead']['evidence_note']}")
        if comparison["agent_reach"].get("evidence_note"):
            lines.append(f"    agent_reach evidence: {comparison['agent_reach']['evidence_note']}")
        lines.append(f"  -> {comparison['verdict']}: {comparison['reason']}")
        lines.append("")

    lines.append("Summary")
    lines.append(
        f"  cases run={summary['cases_run']} both exercised={summary['cases_both_exercised']} "
        f"skipped(auth)={summary['cases_skipped_auth']}"
    )
    lines.append(
        "  cases with evidence: "
        f"trailhead={summary['trailhead_evidence_cases']} "
        f"agent_reach={summary['agent_reach_evidence_cases']}"
    )
    if summary.get("trailhead_possibly_cached_cases"):
        lines.append(
            "  trailhead reads that may have been served from cache: "
            f"{summary['trailhead_possibly_cached_cases']}"
        )
    if summary["verdict_counts"]:
        lines.append(
            "  verdicts: "
            + ", ".join(f"{k}={v}" for k, v in sorted(summary["verdict_counts"].items()))
        )
    lines.append(f"  aggregate ranking: none — {summary['ranking_note']}")
    lines.append("")
    lines.append("Limitations")
    for item in report["methodology"]["limitations"]:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def format_compare_markdown(report: dict) -> str:
    summary = report["summary"]
    env = report["environment"]
    ar = env["agent_reach"]
    sandbox = env.get("sandbox") or {}
    lines = [
        "# Head-to-head case benchmark (measured)",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- Agent Reach: {'available at ' + ar['path'] if ar['available'] else ('not installed' if ar['requested'] else 'not run')}"
        + (f" (version {ar['version']})" if ar.get("version") else ""),
        f"- Sandbox: `{sandbox.get('root')}` ({sandbox.get('run_kind')}, credentials not forwarded)",
        f"- Execution: trailhead={env.get('execution', {}).get('trailhead', '?')}, "
        f"agent_reach={env.get('execution', {}).get('agent_reach', '?')} — "
        f"one wall budget per case ({env.get('wall_timeout_s', '?')}s)",
        "- Isolation: environment-only (temp HOME/config, credential vars dropped); "
        "not a filesystem or OS sandbox",
        f"- Billable ASR: {'disabled' if env.get('billable_asr', {}).get('disabled') else 'not disabled'}"
        + (f" ({env['billable_asr'].get('env')})" if env.get("billable_asr", {}).get("env") else ""),
        "",
        "| Case | Requested from Agent Reach | Trailhead | Agent Reach | Outcome |",
        "|---|---|---|---|---|",
    ]
    for entry in report["cases"]:
        case = entry["case"]
        comparison = entry.get("comparison")
        requested = " ".join(case["agent_reach_command"])
        if comparison is None:
            lines.append(
                f"| `{case['id']}` | `{requested}` | skipped | skipped | not_run (auth case) |"
            )
            continue
        t = comparison["trailhead"]
        a = comparison["agent_reach"]
        lines.append(
            "| `{}` | `{}` | {} ({} cleaned, {}ms) | {} ({} cleaned, {}ms) | {} |".format(
                case["id"],
                requested,
                t["status"] + "/" + t["evidence_verdict"],
                t["cleaned_chars"],
                t["duration_ms"] if t["duration_ms"] is not None else "-",
                a["status"] + "/" + a["evidence_verdict"],
                a["cleaned_chars"],
                a["duration_ms"] if a["duration_ms"] is not None else "-",
                comparison["verdict"],
            )
        )
    auth_notes = [
        f"- `{entry['case']['id']}`: {(entry.get('auth') or {}).get('mode')} — "
        f"{(entry.get('auth') or {}).get('note')}"
        for entry in report["cases"]
        if entry.get("auth")
    ]
    if auth_notes:
        lines += ["", "Auth-shaped cases:", ""] + auth_notes
    lines += [
        "",
        f"**Aggregate ranking:** none — {summary['ranking_note']}",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in report["methodology"]["limitations"]]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(_worker_cli())
