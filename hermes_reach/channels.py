from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import shutil
import subprocess
import urllib.request
from typing import Callable, Literal


ROOT = Path.home()
HERMES_HOME = ROOT / ".hermes"
HERMES_AGENT_REPO = HERMES_HOME / "hermes-agent"
CONFIG = HERMES_HOME / "config.yaml"
CRON = HERMES_HOME / "cron" / "jobs.json"
NEWSLETTER = HERMES_HOME / "scripts" / "hermes-morning-brief-v3.py"
WATCHER = HERMES_HOME / "scripts" / "hermes-upstream-opportunity-watch.py"
VALIDATOR = HERMES_HOME / "scripts" / "validate-hermes-newsletter.py"

Status = Literal["ok", "warn", "off", "fail"]
Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Evidence:
    source: str
    detail: str
    command: str = ""
    path: str = ""
    return_code: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CheckResult:
    status: Status
    detail: str
    action: str = ""
    evidence: tuple[Evidence, ...] = ()
    confidence: float = 1.0
    approval_required: bool = False
    category: str = "capability"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = [e.to_dict() for e in self.evidence]
        return data


@dataclass(frozen=True)
class Channel:
    key: str
    title: str
    purpose: str
    default_path: str
    risk: Risk
    check: Callable[[], CheckResult]
    setup_plan: tuple[str, ...]
    required: bool = False
    approval_required: bool = False
    tags: tuple[str, ...] = ()
    hermes_native: bool = True

    def base_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "purpose": self.purpose,
            "default_path": self.default_path,
            "risk": self.risk,
            "required": self.required,
            "approval_required": self.approval_required,
            "tags": list(self.tags),
            "hermes_native": self.hermes_native,
            "setup_plan": list(self.setup_plan),
        }


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(errors="replace")
    except Exception:
        return False


def _cron_jobs() -> list[dict]:
    try:
        data = json.loads(CRON.read_text(errors="replace"))
        return list(data.get("jobs", []))
    except Exception:
        return []


def _git_default_remote_branch(repo: Path) -> str:
    rc, out = _run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo, timeout=10)
    if rc == 0 and out.strip():
        return out.strip().rsplit("/", 1)[-1]
    return "main"


def _result(
    status: Status,
    detail: str,
    *,
    action: str = "",
    evidence: tuple[Evidence, ...] = (),
    confidence: float = 1.0,
    approval_required: bool = False,
    category: str = "capability",
) -> CheckResult:
    return CheckResult(
        status=status,
        detail=detail,
        action=action,
        evidence=evidence,
        confidence=confidence,
        approval_required=approval_required,
        category=category,
    )


def check_web_search() -> CheckResult:
    if CONFIG.exists():
        return _result(
            "ok",
            "Hermes config present; use native web_search tool when available.",
            evidence=(Evidence("file", "Hermes config exists", path=str(CONFIG)),),
        )
    return _result(
        "warn",
        "Hermes config missing; web_search availability depends on active toolset.",
        evidence=(Evidence("file", "Hermes config not found", path=str(CONFIG)),),
    )


def check_web_extract() -> CheckResult:
    return _result(
        "ok",
        "Use native web_extract; fallback recipe is Jina Reader: https://r.jina.ai/http://example.com",
        evidence=(Evidence("policy", "Native Hermes tool preferred over custom scraper"),),
    )


def check_github() -> CheckResult:
    if _cmd("gh"):
        rc, out = _run(["gh", "auth", "status"], timeout=10)
        evidence = (Evidence("command", out[:500] or "gh auth status returned no output", command="gh auth status", return_code=rc),)
        if rc == 0:
            return _result("ok", "gh authenticated; GitHub MCP can also be used from Hermes.", evidence=evidence)
        return _result("warn", "gh installed but auth status is not clean.", action="Run `gh auth status`; authenticate only if needed.", evidence=evidence)
    return _result("warn", "gh CLI not installed or not on PATH.", action="Use GitHub MCP first; install gh only if terminal workflow needs it.", evidence=(Evidence("command", "gh not found on PATH", command="which gh", return_code=127),))


def check_x_search(live: bool = False) -> CheckResult:
    if os.environ.get("XAI_API_KEY"):
        return _result("ok", "XAI_API_KEY present; prefer Hermes x_search for current X discussion.", evidence=(Evidence("env", "XAI_API_KEY is present"),))

    if live:
        try:
            req = urllib.request.Request("http://localhost:8788", method="HEAD")
            resp = urllib.request.urlopen(req, timeout=5)
            return _result(
                "ok",
                f"Local Nitter instance reachable at localhost:8788 (HTTP {resp.status}); live X search fallback available.",
                evidence=(
                    Evidence("http", f"Nitter responded HTTP {resp.status}", command="HEAD http://localhost:8788", return_code=resp.status),
                    Evidence("policy", "Cookie auth and posting are high-risk actions"),
                ),
                approval_required=True,
            )
        except Exception as exc:
            return _result(
                "warn",
                f"Local Nitter at localhost:8788 not reachable ({exc}); no XAI_API_KEY in environment.",
                action="Do not scrape cookies automatically; ask before configuring X auth.",
                evidence=(
                    Evidence("env", "XAI_API_KEY absent"),
                    Evidence("http", f"Nitter probe failed: {exc}", command="HEAD http://localhost:8788"),
                    Evidence("policy", "Cookie auth and posting are high-risk actions"),
                ),
                approval_required=True,
            )

    nitter_hint = "local Nitter expected at localhost:8788 per Hermes memory; use fallback extraction if reachable."
    return _result(
        "warn",
        "No XAI_API_KEY in environment; x_search may be unavailable or credit-limited. " + nitter_hint,
        action="Do not scrape cookies automatically; ask before configuring X auth.",
        evidence=(Evidence("env", "XAI_API_KEY absent"), Evidence("policy", "Cookie auth and posting are high-risk actions")),
        approval_required=True,
    )


def check_reddit(live: bool = False) -> CheckResult:
    redlib = "https://redlib.perennialte.ch"

    if live:
        try:
            req = urllib.request.Request(redlib, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            body_preview = resp.read(512).decode("utf-8", errors="replace")[:100]
            return _result(
                "ok",
                f"Redlib frontend is live and responding at {redlib} (HTTP {resp.status}).",
                evidence=(
                    Evidence("http", f"Redlib responded HTTP {resp.status}, body preview: {body_preview}", command=f"GET {redlib}", return_code=resp.status),
                ),
            )
        except Exception as exc:
            return _result(
                "warn",
                f"Redlib frontend at {redlib} not reachable ({exc}); fall back to existing reddit-search tooling.",
                evidence=(
                    Evidence("http", f"Redlib probe failed: {exc}", command=f"GET {redlib}"),
                    Evidence("memory", "Configured Redlib frontend", path=redlib),
                ),
            )

    return _result("ok", f"Prefer Redlib/privacy frontend or existing reddit-search tooling. Known Redlib: {redlib}", evidence=(Evidence("memory", "Configured Redlib frontend", path=redlib),))


def check_youtube() -> CheckResult:
    if _cmd("yt-dlp"):
        return _result("ok", "yt-dlp installed; use for transcripts/metadata when native media tools are not enough.", evidence=(Evidence("command", "yt-dlp found on PATH", command="which yt-dlp"),))
    return _result("off", "yt-dlp not installed globally.", action="Install in a project venv only when a YouTube task needs it.", evidence=(Evidence("command", "yt-dlp not found", command="which yt-dlp", return_code=127),))


def check_tiktok() -> CheckResult:
    if _cmd("proxitok") or _cmd("yt-dlp"):
        return _result("warn", "TikTok can be probed through available media/frontends, but coverage should be verified per query.", action="For TikTok research, run a platform-specific probe and report retrieved-count + dead-link count.", evidence=(Evidence("command", "TikTok-capable helper candidate found", command="which proxitok || which yt-dlp"),))
    return _result(
        "off",
        "No dedicated TikTok reader/frontend is configured. Use web_search site:tiktok.com or supervised browser as fallback.",
        action="Add a loginless TikTok frontend/search path before claiming broad TikTok coverage.",
        evidence=(Evidence("policy", "TikTok coverage is not assumed without a configured reader/frontend"),),
        approval_required=True,
    )


def check_instagram() -> CheckResult:
    if _cmd("gallery-dl"):
        return _result("warn", "gallery-dl is available, but Instagram often needs account/session handling; use only with explicit scope.", evidence=(Evidence("command", "gallery-dl found on PATH", command="which gallery-dl"),), approval_required=True)
    return _result(
        "off",
        "No dedicated Instagram reader/frontend is configured. Use web_search site:instagram.com or supervised browser as fallback.",
        action="Add a loginless Instagram frontend/search path before claiming broad Instagram coverage; account/session work needs approval.",
        evidence=(Evidence("policy", "Instagram coverage is not assumed without a configured reader/frontend"),),
        approval_required=True,
    )


def check_hermes_upstream() -> CheckResult:
    if not HERMES_AGENT_REPO.exists():
        return _result("off", f"Hermes repo missing at {HERMES_AGENT_REPO}", evidence=(Evidence("file", "Repo directory missing", path=str(HERMES_AGENT_REPO)),))
    branch = _git_default_remote_branch(HERMES_AGENT_REPO)
    remote = f"origin/{branch}"
    rc, out = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...{remote}"], cwd=HERMES_AGENT_REPO)
    evidence = (Evidence("command", out, command=f"git rev-list --left-right --count HEAD...{remote}", path=str(HERMES_AGENT_REPO), return_code=rc),)
    if rc != 0:
        return _result("warn", f"Could not compare Hermes repo to {remote}.", action="Run git fetch in the Hermes repo.", evidence=evidence)
    ahead, behind = out.split()[:2]
    if behind == "0":
        return _result("ok", f"Hermes repo current with {remote} (ahead {ahead}, behind {behind}).", evidence=evidence)
    return _result("warn", f"Hermes repo is {behind} commits behind {remote}.", action="Run `hermes update` after checking local changes.", evidence=evidence)


def check_newsletter() -> CheckResult:
    missing = [str(p) for p in (NEWSLETTER, VALIDATOR) if not p.exists()]
    if missing:
        return _result("warn", "Newsletter gate files missing: " + ", ".join(missing), evidence=tuple(Evidence("file", "missing", path=p) for p in missing))
    radar = _contains(NEWSLETTER, "HERMES CAPABILITY RADAR")
    validator = _contains(NEWSLETTER, "VALIDATOR")
    evidence = (
        Evidence("file_contains", f"HERMES CAPABILITY RADAR={radar}", path=str(NEWSLETTER)),
        Evidence("file_contains", f"VALIDATOR={validator}", path=str(NEWSLETTER)),
    )
    if radar and validator:
        return _result("ok", "Daily briefing has acceptance gate and Hermes Capability Radar.", evidence=evidence)
    return _result("warn", "Daily briefing exists but capability radar/gate is not verified.", evidence=evidence)


def check_docs_watcher() -> CheckResult:
    if not WATCHER.exists():
        return _result("off", "Upstream docs/opportunity watcher script missing.", evidence=(Evidence("file", "watcher missing", path=str(WATCHER)),))
    jobs = _cron_jobs()
    matches = [job for job in jobs if job.get("name") == "hermes-upstream-opportunity-watch" or job.get("script") == "hermes-upstream-opportunity-watch.py"]
    evidence = (Evidence("file", f"matched_jobs={len(matches)} total_jobs={len(jobs)}", path=str(CRON)),)
    if matches:
        job = matches[0]
        status = job.get("last_status") or "unknown"
        next_run = job.get("next_run_at") or "unknown"
        return _result("ok", f"Docs opportunity watcher scheduled in Hermes cron (last_status={status}, next_run={next_run}).", evidence=evidence)
    if not CRON.exists():
        return _result("warn", "Cron registry missing; watcher may not be scheduled.", evidence=evidence)
    return _result("warn", "Watcher script exists but cron registration not found.", evidence=evidence)


def check_agent_reach_upstream() -> CheckResult:
    return _result(
        "warn",
        "Agent-Reach is a plausible MIT scaffold, but cookie/global-install flows should stay sandboxed.",
        action="Use Hermes Reach first; sandbox Agent-Reach separately before installing anything into main Hermes.",
        evidence=(Evidence("upstream_review", "MIT repo inspected; broad cookie/global-install surfaces found", path="https://github.com/Panniantong/Agent-Reach"),),
        approval_required=True,
        category="external_tooling",
    )


CHANNELS: tuple[Channel, ...] = (
    Channel("web-search", "Web search", "Current broad discovery", "Hermes web_search", "low", check_web_search, ("Use native web_search.", "For deep research, triangulate primary sources and social sources."), required=True, tags=("research", "native")),
    Channel("web-extract", "Web/page extraction", "Read pages/PDFs as markdown", "Hermes web_extract", "low", check_web_extract, ("Use native web_extract first.", "Fallback to Jina Reader only for raw URL conversion."), required=True, tags=("research", "native")),
    Channel("github", "GitHub", "Repos, issues, PRs", "GitHub MCP / gh", "medium", check_github, ("Use GitHub MCP tools first.", "Use gh CLI for workflows that need terminal/git integration."), tags=("code", "mcp")),
    Channel("x-search", "X/Twitter", "Current maintainer/community signal", "x_search / Nitter", "high", check_x_search, ("Use x_search if credentialed.", "Fallback to Nitter extraction.", "Do not configure cookies or posting without explicit approval."), approval_required=True, tags=("social", "current")),
    Channel("reddit", "Reddit", "Practitioner threads", "Redlib / reddit-search", "medium", check_reddit, ("Use Redlib/privacy frontend.", "Avoid brittle anonymous scraping; browser/cookie auth requires approval."), tags=("social", "current")),
    Channel("tiktok", "TikTok", "Short-form creator/current signal", "site:tiktok.com search / supervised browser / TikTok frontend", "high", check_tiktok, ("Start with loginless site:tiktok.com discovery.", "Use a TikTok privacy frontend or media helper only when configured.", "Account/session/browser work requires explicit approval."), approval_required=True, tags=("social", "current", "video")),
    Channel("instagram", "Instagram", "Creator/profile/current signal", "site:instagram.com search / supervised browser / Instagram frontend", "high", check_instagram, ("Start with loginless site:instagram.com discovery.", "Use a privacy frontend or media helper only when configured.", "Account/session/browser work requires explicit approval."), approval_required=True, tags=("social", "current", "image")),
    Channel("youtube", "YouTube", "Video metadata/transcripts", "yt-dlp / media tools", "medium", check_youtube, ("Install yt-dlp only in a project venv when needed.", "Prefer transcript APIs/tools when already available."), tags=("media",)),
    Channel("hermes-upstream", "Hermes upstream", "Docs/commit capability drift", "git fetch/log/diff", "low", check_hermes_upstream, ("Use git fetch/log/diff in /home/hermes/.hermes/hermes-agent.", "Feed actionable deltas to newsletter capability radar."), required=True, tags=("hermes", "upstream")),
    Channel("newsletter", "Daily newsletter", "AI/Hermes intelligence report", "morning brief v3", "low", check_newsletter, ("Keep acceptance gate mandatory.", "Keep Capability Radar frontloaded."), required=True, tags=("hermes", "reporting")),
    Channel("docs-watcher", "Docs watcher", "Silent upstream opportunity alerts", "no-agent cron", "low", check_docs_watcher, ("Keep no_agent=true.", "Silent stdout means healthy/no-change."), required=True, tags=("hermes", "cron")),
    Channel("agent-reach", "Agent-Reach upstream", "External broad internet scaffold", "sandbox only", "high", check_agent_reach_upstream, ("Do not install into main Hermes by default.", "Clone/test in /tmp or a venv.", "Adopt individual safe backends only after doctor proof."), approval_required=True, hermes_native=False, tags=("external", "sandbox")),
)


def get_channel(key: str) -> Channel:
    for channel in CHANNELS:
        if channel.key == key:
            return channel
    raise KeyError(key)


def check_all() -> list[tuple[Channel, CheckResult]]:
    return [(channel, channel.check()) for channel in CHANNELS]


def check_all_live() -> list[tuple[Channel, CheckResult]]:
    results: list[tuple[Channel, CheckResult]] = []
    for channel in CHANNELS:
        if channel.key == "x-search":
            results.append((channel, check_x_search(live=True)))
        elif channel.key == "reddit":
            results.append((channel, check_reddit(live=True)))
        else:
            results.append((channel, channel.check()))
    return results
