from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
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
ErrorKind = Literal[
    "missing_file",
    "auth_failure",
    "network_timeout",
    "network_error",
    "permission_denied",
    "unknown_tool",
    "config_missing",
    "none",
]

# ── Discriminated Evidence types ──────────────────────────────────────────

class Evidence:
    """Base evidence type. Use the subclasses directly."""
    source: str
    detail: str

    def to_dict(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class FileEvidence(Evidence):
    source: str
    detail: str
    path: str

    def to_dict(self) -> dict:
        return {"source": self.source, "detail": self.detail, "path": self.path}


@dataclass(frozen=True)
class EnvEvidence(Evidence):
    source: str
    detail: str
    var_name: str = ""

    def to_dict(self) -> dict:
        return {"source": self.source, "detail": self.detail, "var_name": self.var_name}


@dataclass(frozen=True)
class CommandEvidence(Evidence):
    source: str
    detail: str
    command: str = ""
    return_code: int | None = None

    def to_dict(self) -> dict:
        return {"source": self.source, "detail": self.detail, "command": self.command, "return_code": self.return_code}


@dataclass(frozen=True)
class HttpEvidence(Evidence):
    source: str
    detail: str
    url: str = ""
    status_code: int | None = None

    def to_dict(self) -> dict:
        return {"source": self.source, "detail": self.detail, "url": self.url, "status_code": self.status_code}


@dataclass(frozen=True)
class PolicyEvidence(Evidence):
    source: str
    detail: str

    def to_dict(self) -> dict:
        return {"source": self.source, "detail": self.detail}


# ── CheckResult with error taxonomy ───────────────────────────────────────

@dataclass(frozen=True)
class CheckResult:
    status: Status
    detail: str
    action: str = ""
    evidence: tuple[Evidence, ...] = ()
    confidence: float = 1.0
    approval_required: bool = False
    category: str = "capability"
    error_kind: ErrorKind | None = None

    def to_dict(self) -> dict:
        data = {
            "status": self.status,
            "detail": self.detail,
            "action": self.action,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence,
            "approval_required": self.approval_required,
            "category": self.category,
        }
        if self.error_kind is not None:
            data["error_kind"] = self.error_kind
        return data


# ── ChannelSpec (serializable, no callable) ───────────────────────────────

@dataclass(frozen=True)
class ChannelSpec:
    """Serializable channel metadata — no callable, safe for JSON."""
    key: str
    title: str
    purpose: str
    default_path: str
    risk: Risk
    required: bool = False
    approval_required: bool = False
    tags: tuple[str, ...] = ()
    hermes_native: bool = True
    setup_plan: tuple[str, ...] = ()
    timeout: int = 15

    def to_dict(self) -> dict:
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
            "timeout": self.timeout,
        }


# ── Channel (data + behavior) ─────────────────────────────────────────────

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
    timeout: int = 15

    @property
    def spec(self) -> ChannelSpec:
        return ChannelSpec(
            key=self.key,
            title=self.title,
            purpose=self.purpose,
            default_path=self.default_path,
            risk=self.risk,
            required=self.required,
            approval_required=self.approval_required,
            tags=self.tags,
            hermes_native=self.hermes_native,
            setup_plan=self.setup_plan,
            timeout=self.timeout,
        )

    def base_dict(self) -> dict:
        return self.spec.to_dict()


# ── IO abstraction (testable without monkeypatching) ──────────────────────

@dataclass
class IO:
    """Filesystem/subprocess IO. Swap for testing."""
    which: Callable[[str], bool] = lambda name: shutil.which(name) is not None
    run: Callable[..., tuple[int, str]] = lambda cmd, cwd=None, timeout=15: _real_run(cmd, cwd=cwd, timeout=timeout)
    read_text: Callable[[Path], str] = lambda path: path.read_text(errors="replace")
    exists: Callable[[Path], bool] = lambda path: path.exists()
    getenv: Callable[[str], str | None] = os.environ.get
    http_head: Callable[[str, int], tuple[int, str]] = lambda url, timeout=5: _real_http("HEAD", url, timeout)
    http_get: Callable[[str, int], tuple[int, str]] = lambda url, timeout=5: _real_http("GET", url, timeout)

    @classmethod
    def real(cls) -> IO:
        return cls()

    @classmethod
    def fake(
        cls,
        *,
        which: Callable[[str], bool] | None = None,
        run: Callable[..., tuple[int, str]] | None = None,
        read_text: Callable[[Path], str] | None = None,
        exists: Callable[[Path], bool] | None = None,
        getenv: Callable[[str], str | None] | None = None,
        http_head: Callable[[str, int], tuple[int, str]] | None = None,
        http_get: Callable[[str, int], tuple[int, str]] | None = None,
    ) -> IO:
        io = cls()
        if which is not None:
            io.which = which
        if run is not None:
            io.run = run
        if read_text is not None:
            io.read_text = read_text
        if exists is not None:
            io.exists = exists
        if getenv is not None:
            io.getenv = getenv
        if http_head is not None:
            io.http_head = http_head
        if http_get is not None:
            io.http_get = http_get
        return io


def _real_run(cmd: list[str], cwd: Path | None = None, timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _real_http(method: str, url: str, timeout: int = 5) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, method=method)
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read(512).decode("utf-8", errors="replace")[:100]
        return resp.status, body
    except Exception as exc:
        return 0, str(exc)


# Default IO instance
_io: IO = IO.real()


def set_io(io: IO) -> None:
    """Swap IO for testing."""
    global _io
    _io = io


def reset_io() -> None:
    """Restore real IO."""
    global _io
    _io = IO.real()


# ── Helpers ───────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 15) -> tuple[int, str]:
    return _io.run(cmd, cwd=cwd, timeout=timeout)


def _cmd(name: str) -> bool:
    return _io.which(name)


def _contains(path: Path, needle: str) -> bool:
    try:
        return needle in _io.read_text(path)
    except Exception:
        return False


def _cron_jobs() -> list[dict]:
    try:
        data = json.loads(_io.read_text(CRON))
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
    error_kind: ErrorKind | None = None,
) -> CheckResult:
    return CheckResult(
        status=status,
        detail=detail,
        action=action,
        evidence=evidence,
        confidence=confidence,
        approval_required=approval_required,
        category=category,
        error_kind=error_kind,
    )


# ── Channel check functions ───────────────────────────────────────────────

def check_web_search() -> CheckResult:
    if _io.exists(CONFIG):
        return _result(
            "ok",
            "Hermes config present; use native web_search tool when available.",
            evidence=(FileEvidence("file", "Hermes config exists", path=str(CONFIG)),),
        )
    return _result(
        "warn",
        "Hermes config missing; web_search availability depends on active toolset.",
        evidence=(FileEvidence("file", "Hermes config not found", path=str(CONFIG)),),
        error_kind="config_missing",
    )


def check_web_extract() -> CheckResult:
    return _result(
        "ok",
        "Use native web_extract; fallback recipe is Jina Reader: https://r.jina.ai/http://example.com",
        evidence=(PolicyEvidence("policy", "Native Hermes tool preferred over custom scraper"),),
    )


def check_github() -> CheckResult:
    if _cmd("gh"):
        rc, out = _run(["gh", "auth", "status"], timeout=10)
        evidence = (CommandEvidence("command", out[:500] or "gh auth status returned no output", command="gh auth status", return_code=rc),)
        if rc == 0:
            return _result("ok", "gh authenticated; GitHub MCP can also be used from Hermes.", evidence=evidence)
        return _result("warn", "gh installed but auth status is not clean.", action="Run `gh auth status`; authenticate only if needed.", evidence=evidence, error_kind="auth_failure")
    return _result(
        "warn", "gh CLI not installed or not on PATH.",
        action="Use GitHub MCP first; install gh only if terminal workflow needs it.",
        evidence=(CommandEvidence("command", "gh not found on PATH", command="which gh", return_code=127),),
        error_kind="unknown_tool",
    )


def check_x_search(live: bool = False) -> CheckResult:
    if _io.getenv("XAI_API_KEY"):
        return _result("ok", "XAI_API_KEY present; prefer Hermes x_search for current X discussion.", evidence=(EnvEvidence("env", "XAI_API_KEY is present", var_name="XAI_API_KEY"),))

    if live:
        try:
            url = "http://localhost:8788"
            status_code, _body = _io.http_head(url, timeout=5)
            if 200 <= status_code < 400:
                return _result(
                    "ok",
                    f"Local Nitter instance reachable at localhost:8788 (HTTP {status_code}); live X search fallback available.",
                    evidence=(
                        HttpEvidence("http", f"Nitter responded HTTP {status_code}", url=url, status_code=status_code),
                        PolicyEvidence("policy", "Cookie auth and posting are high-risk actions"),
                    ),
                    approval_required=True,
                )
            return _result(
                "warn",
                f"Local Nitter at localhost:8788 returned HTTP {status_code}; no XAI_API_KEY in environment.",
                action="Do not scrape cookies automatically; ask before configuring X auth.",
                evidence=(
                    EnvEvidence("env", "XAI_API_KEY absent", var_name="XAI_API_KEY"),
                    HttpEvidence("http", f"Nitter returned HTTP {status_code}", url=url, status_code=status_code),
                    PolicyEvidence("policy", "Cookie auth and posting are high-risk actions"),
                ),
                approval_required=True,
                error_kind="network_error",
            )
        except Exception as exc:
            return _result(
                "warn",
                f"Local Nitter at localhost:8788 not reachable ({exc}); no XAI_API_KEY in environment.",
                action="Do not scrape cookies automatically; ask before configuring X auth.",
                evidence=(
                    EnvEvidence("env", "XAI_API_KEY absent", var_name="XAI_API_KEY"),
                    HttpEvidence("http", f"Nitter probe failed: {exc}", url="http://localhost:8788"),
                    PolicyEvidence("policy", "Cookie auth and posting are high-risk actions"),
                ),
                approval_required=True,
            )

    nitter_hint = "local Nitter expected at localhost:8788 per Hermes memory; use fallback extraction if reachable."
    return _result(
        "warn",
        "No XAI_API_KEY in environment; x_search may be unavailable or credit-limited. " + nitter_hint,
        action="Do not scrape cookies automatically; ask before configuring X auth.",
        evidence=(EnvEvidence("env", "XAI_API_KEY absent", var_name="XAI_API_KEY"), PolicyEvidence("policy", "Cookie auth and posting are high-risk actions")),
        approval_required=True,
    )


def check_reddit(live: bool = False) -> CheckResult:
    redlib = "https://redlib.perennialte.ch"

    if live:
        try:
            status_code, body = _io.http_get(redlib, timeout=5)
            if 200 <= status_code < 400:
                return _result(
                    "ok",
                    f"Redlib frontend is live and responding at {redlib} (HTTP {status_code}).",
                    evidence=(HttpEvidence("http", f"Redlib responded HTTP {status_code}, body preview: {body}", url=redlib, status_code=status_code),),
                )
            return _result(
                "warn",
                f"Redlib frontend at {redlib} returned HTTP {status_code}; fall back to existing reddit-search tooling.",
                evidence=(
                    HttpEvidence("http", f"Redlib returned HTTP {status_code}", url=redlib, status_code=status_code),
                    PolicyEvidence("memory", f"Configured Redlib frontend: {redlib}"),
                ),
                error_kind="network_error",
            )
        except Exception as exc:
            return _result(
                "warn",
                f"Redlib frontend at {redlib} not reachable ({exc}); fall back to existing reddit-search tooling.",
                evidence=(
                    HttpEvidence("http", f"Redlib probe failed: {exc}", url=redlib),
                    PolicyEvidence("memory", f"Configured Redlib frontend: {redlib}"),
                ),
                error_kind="network_error",
            )

    return _result("ok", f"Prefer Redlib/privacy frontend or existing reddit-search tooling. Known Redlib: {redlib}", evidence=(PolicyEvidence("memory", f"Configured Redlib frontend: {redlib}"),))


def check_youtube() -> CheckResult:
    if _cmd("yt-dlp"):
        return _result("ok", "yt-dlp installed; use for transcripts/metadata when native media tools are not enough.", evidence=(CommandEvidence("command", "yt-dlp found on PATH", command="which yt-dlp"),))
    return _result("off", "yt-dlp not installed globally.", action="Install in a project venv only when a YouTube task needs it.", evidence=(CommandEvidence("command", "yt-dlp not found", command="which yt-dlp", return_code=127),), error_kind="unknown_tool")


def check_tiktok() -> CheckResult:
    if _cmd("proxitok") or _cmd("yt-dlp"):
        return _result("warn", "TikTok can be probed through available media/frontends, but coverage should be verified per query.", action="For TikTok research, run a platform-specific probe and report retrieved-count + dead-link count.", evidence=(CommandEvidence("command", "TikTok-capable helper candidate found", command="which proxitok || which yt-dlp"),))
    return _result(
        "off",
        "No dedicated TikTok reader/frontend is configured. Use web_search site:tiktok.com or supervised browser as fallback.",
        action="Add a loginless TikTok frontend/search path before claiming broad TikTok coverage.",
        evidence=(PolicyEvidence("policy", "TikTok coverage is not assumed without a configured reader/frontend"),),
        approval_required=True,
        error_kind="unknown_tool",
    )


def check_instagram() -> CheckResult:
    if _cmd("gallery-dl"):
        return _result("warn", "gallery-dl is available, but Instagram often needs account/session handling; use only with explicit scope.", evidence=(CommandEvidence("command", "gallery-dl found on PATH", command="which gallery-dl"),), approval_required=True)
    return _result(
        "off",
        "No dedicated Instagram reader/frontend is configured. Use web_search site:instagram.com or supervised browser as fallback.",
        action="Add a loginless Instagram frontend/search path before claiming broad Instagram coverage; account/session work needs approval.",
        evidence=(PolicyEvidence("policy", "Instagram coverage is not assumed without a configured reader/frontend"),),
        approval_required=True,
        error_kind="unknown_tool",
    )


def check_hermes_upstream() -> CheckResult:
    if not _io.exists(HERMES_AGENT_REPO):
        return _result("off", f"Hermes repo missing at {HERMES_AGENT_REPO}", evidence=(FileEvidence("file", "Repo directory missing", path=str(HERMES_AGENT_REPO)),), error_kind="missing_file")
    branch = _git_default_remote_branch(HERMES_AGENT_REPO)
    remote = f"origin/{branch}"
    rc, out = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...{remote}"], cwd=HERMES_AGENT_REPO)
    evidence = (CommandEvidence("command", out, command=f"git rev-list --left-right --count HEAD...{remote}", return_code=rc),)
    if rc != 0:
        return _result("warn", f"Could not compare Hermes repo to {remote}.", action="Run git fetch in the Hermes repo.", evidence=evidence, error_kind="network_error")
    ahead, behind = out.split()[:2]
    if behind == "0":
        return _result("ok", f"Hermes repo current with {remote} (ahead {ahead}, behind {behind}).", evidence=evidence)
    return _result("warn", f"Hermes repo is {behind} commits behind {remote}.", action="Run `hermes update` after checking local changes.", evidence=evidence)


def check_newsletter() -> CheckResult:
    missing = [str(p) for p in (NEWSLETTER, VALIDATOR) if not _io.exists(p)]
    if missing:
        return _result("warn", "Newsletter gate files missing: " + ", ".join(missing), evidence=tuple(FileEvidence("file", "missing", path=p) for p in missing), error_kind="missing_file")
    radar = _contains(NEWSLETTER, "HERMES CAPABILITY RADAR")
    validator = _contains(NEWSLETTER, "VALIDATOR")
    evidence = (
        FileEvidence("file_contains", f"HERMES CAPABILITY RADAR={radar}", path=str(NEWSLETTER)),
        FileEvidence("file_contains", f"VALIDATOR={validator}", path=str(NEWSLETTER)),
    )
    if radar and validator:
        return _result("ok", "Daily briefing has acceptance gate and Hermes Capability Radar.", evidence=evidence)
    return _result("warn", "Daily briefing exists but capability radar/gate is not verified.", evidence=evidence)


def check_docs_watcher() -> CheckResult:
    if not _io.exists(WATCHER):
        return _result("off", "Upstream docs/opportunity watcher script missing.", evidence=(FileEvidence("file", "watcher missing", path=str(WATCHER)),), error_kind="missing_file")
    jobs = _cron_jobs()
    matches = [job for job in jobs if job.get("name") == "hermes-upstream-opportunity-watch" or job.get("script") == "hermes-upstream-opportunity-watch.py"]
    evidence = (FileEvidence("file", f"matched_jobs={len(matches)} total_jobs={len(jobs)}", path=str(CRON)),)
    if matches:
        job = matches[0]
        status = job.get("last_status") or "unknown"
        next_run = job.get("next_run_at") or "unknown"
        return _result("ok", f"Docs opportunity watcher scheduled in Hermes cron (last_status={status}, next_run={next_run}).", evidence=evidence)
    if not _io.exists(CRON):
        return _result("warn", "Cron registry missing; watcher may not be scheduled.", evidence=evidence, error_kind="missing_file")
    return _result("warn", "Watcher script exists but cron registration not found.", evidence=evidence)


def check_agent_reach_upstream() -> CheckResult:
    return _result(
        "warn",
        "Agent-Reach is a plausible MIT scaffold, but cookie/global-install flows should stay sandboxed.",
        action="Use SourceScout first; sandbox Agent-Reach separately before installing anything into main Hermes.",
        evidence=(PolicyEvidence("upstream_review", "MIT repo inspected; broad cookie/global-install surfaces found"),),
        approval_required=True,
        category="external_tooling",
    )


# ── New tool channel checks ───────────────────────────────────────────────

def check_firecrawl() -> CheckResult:
    if _io.getenv("FIRECRAWL_API_KEY"):
        return _result("ok", "FIRECRAWL_API_KEY present; Firecrawl available for crawl/search/extract.", evidence=(EnvEvidence("env", "FIRECRAWL_API_KEY is present", var_name="FIRECRAWL_API_KEY"),), category="external_tooling")
    return _result("off", "No FIRECRAWL_API_KEY; Firecrawl not configured. Crawl4AI or Hermes web_extract can serve as fallbacks.", action="Set FIRECRAWL_API_KEY only if the crawl/extract budget justifies it.", evidence=(EnvEvidence("env", "FIRECRAWL_API_KEY absent", var_name="FIRECRAWL_API_KEY"),), error_kind="config_missing", category="external_tooling")


def check_crawl4ai() -> CheckResult:
    try:
        rc, out = _run(["python3", "-c", "import crawl4ai; print(crawl4ai.__version__)"], timeout=5)
        if rc == 0:
            return _result("ok", f"Crawl4AI {out.strip()} installed; deterministic crawl/extract available.", evidence=(CommandEvidence("command", out.strip(), command="python3 -c 'import crawl4ai'", return_code=rc),), category="external_tooling")
    except Exception:
        pass
    return _result("off", "Crawl4AI not installed. Install in a project venv: `uv pip install crawl4ai`.", action="Use Hermes web_extract as default; add Crawl4AI only for deterministic extraction pipelines.", evidence=(CommandEvidence("command", "crawl4ai import failed", command="python3 -c 'import crawl4ai'", return_code=1),), error_kind="unknown_tool", category="external_tooling")


def check_browserbase() -> CheckResult:
    if _io.getenv("BROWSERBASE_API_KEY") or _io.getenv("BROWSERBASE_PROJECT_ID"):
        return _result("ok", "Browserbase credentials present; hosted browser infrastructure available.", evidence=(EnvEvidence("env", "Browserbase env vars present", var_name="BROWSERBASE_API_KEY"),), approval_required=True, category="external_tooling")
    return _result("off", "Browserbase not configured. Use Hermes browser tools for interactive work.", action="Set BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID only when agent-native browser tools are insufficient.", evidence=(EnvEvidence("env", "BROWSERBASE_API_KEY absent", var_name="BROWSERBASE_API_KEY"),), error_kind="config_missing", category="external_tooling")


def check_jina_reader() -> CheckResult:
    try:
        status_code, _body = _io.http_get("https://r.jina.ai/http://example.com", timeout=5)
        if 200 <= status_code < 400:
            return _result("ok", f"Jina Reader reachable (HTTP {status_code}); URL-to-markdown fallback available.", evidence=(HttpEvidence("http", f"Jina Reader responded HTTP {status_code}", url="https://r.jina.ai", status_code=status_code),), category="external_tooling")
    except Exception as exc:
        pass
    return _result("warn", "Jina Reader not reachable. Hermes web_extract handles most URLs; Jina is an optional fallback.", evidence=(PolicyEvidence("policy", "Jina Reader is optional; Hermes web_extract is the default"),), category="external_tooling")


def check_exa() -> CheckResult:
    if _io.getenv("EXA_API_KEY"):
        return _result("ok", "EXA_API_KEY present; Exa semantic search available.", evidence=(EnvEvidence("env", "EXA_API_KEY is present", var_name="EXA_API_KEY"),), category="external_tooling")
    return _result("off", "No EXA_API_KEY; Exa not configured. Hermes web_search serves as the default discovery engine.", evidence=(EnvEvidence("env", "EXA_API_KEY absent", var_name="EXA_API_KEY"),), error_kind="config_missing", category="external_tooling")


def check_stagehand() -> CheckResult:
    try:
        rc, _out = _run(["npx", "stagehand", "--version"], timeout=10)
        if rc == 0:
            return _result("ok", "Stagehand CLI available; browser primitives (act/observe/extract) accessible.", evidence=(CommandEvidence("command", "stagehand --version succeeded", command="npx stagehand --version", return_code=0),), approval_required=True, category="external_tooling")
    except Exception:
        pass
    return _result("off", "Stagehand not installed. Hermes browser tools cover most interactive needs.", action="Install stagehand (`npm install -g @browserbasehq/stagehand`) only for sites needing programmatic observe/extract primitives.", evidence=(CommandEvidence("command", "stagehand not found", command="npx stagehand --version", return_code=127),), error_kind="unknown_tool", category="external_tooling")


# ── Channel registry ──────────────────────────────────────────────────────

CHANNELS: tuple[Channel, ...] = (
    Channel("web-search", "Web search", "Current broad discovery", "Hermes web_search", "low", check_web_search, ("Use native web_search.", "For deep research, triangulate primary sources and social sources."), required=True, tags=("research", "native")),
    Channel("web-extract", "Web/page extraction", "Read pages/PDFs as markdown", "Hermes web_extract", "low", check_web_extract, ("Use native web_extract first.", "Fallback to Jina Reader only for raw URL conversion."), required=True, tags=("research", "native")),
    Channel("github", "GitHub", "Repos, issues, PRs", "GitHub MCP / gh", "medium", check_github, ("Use GitHub MCP tools first.", "Use gh CLI for workflows that need terminal/git integration."), tags=("code", "mcp")),
    Channel("x-search", "X/Twitter", "Current maintainer/community signal", "x_search / Nitter", "high", check_x_search, ("Use x_search if credentialed.", "Fallback to Nitter extraction.", "Do not configure cookies or posting without explicit approval."), approval_required=True, tags=("social", "current")),
    Channel("reddit", "Reddit", "Practitioner threads", "Redlib / reddit-search", "medium", check_reddit, ("Use Redlib/privacy frontend.", "Avoid brittle anonymous scraping; browser/cookie auth requires approval."), tags=("social", "current")),
    Channel("tiktok", "TikTok", "Short-form creator/current signal", "site:tiktok.com search / supervised browser / TikTok frontend", "high", check_tiktok, ("Start with loginless site:tiktok.com discovery.", "Use a TikTok privacy frontend or media helper only when configured.", "Account/session/browser work requires explicit approval."), approval_required=True, tags=("social", "current", "video")),
    Channel("instagram", "Instagram", "Creator/profile/current signal", "site:instagram.com search / supervised browser / Instagram frontend", "high", check_instagram, ("Start with loginless site:instagram.com discovery.", "Use a privacy frontend or media helper only when configured.", "Account/session/browser work requires explicit approval."), approval_required=True, tags=("social", "current", "image")),
    Channel("youtube", "YouTube", "Video metadata/transcripts", "yt-dlp / media tools", "medium", check_youtube, ("Install yt-dlp only in a project venv when needed.", "Prefer transcript APIs/tools when already available."), tags=("media",)),
    Channel("firecrawl", "Firecrawl", "Crawl/search/extract API", "FIRECRAWL_API_KEY", "medium", check_firecrawl, ("Set FIRECRAWL_API_KEY only when crawl budget is justified.", "Prefer Crawl4AI for deterministic extraction."), approval_required=True, hermes_native=False, tags=("crawl", "api", "external"), timeout=5),
    Channel("crawl4ai", "Crawl4AI", "Open deterministic crawl/extract", "python3 -c 'import crawl4ai'", "low", check_crawl4ai, ("Install in a project venv: uv pip install crawl4ai.", "Use for CSS/XPath/Regex deterministic extraction."), hermes_native=False, tags=("crawl", "external"), timeout=5),
    Channel("browserbase", "Browserbase", "Hosted browser infrastructure", "BROWSERBASE_API_KEY", "high", check_browserbase, ("Set BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID.", "Use managed persistent contexts for sites needing session state."), approval_required=True, hermes_native=False, tags=("browser", "api", "external"), timeout=5),
    Channel("jina-reader", "Jina Reader", "URL-to-markdown reading", "https://r.jina.ai", "low", check_jina_reader, ("Jina Reader is optional; Hermes web_extract is the default.", "Use Jina only when web_extract fails on a known URL."), hermes_native=False, tags=("extract", "api", "external"), timeout=5),
    Channel("exa", "Exa", "Semantic search and extraction", "EXA_API_KEY", "medium", check_exa, ("Set EXA_API_KEY for semantic/deep search.", "Hermes web_search is sufficient for most discovery."), hermes_native=False, tags=("search", "api", "external"), timeout=5),
    Channel("stagehand", "Stagehand", "Browser primitives (act/observe/extract)", "npx stagehand", "high", check_stagehand, ("Install only for sites needing programmatic observe/extract.", "Hermes browser tools cover most interactive needs."), approval_required=True, hermes_native=False, tags=("browser", "external"), timeout=10),
    Channel("hermes-upstream", "Hermes upstream", "Docs/commit capability drift", "git fetch/log/diff", "low", check_hermes_upstream, ("Use git fetch/log/diff in /home/hermes/.hermes/hermes-agent.", "Feed actionable deltas to newsletter capability radar."), required=True, tags=("hermes", "upstream")),
    Channel("newsletter", "Daily newsletter", "AI/Hermes intelligence report", "morning brief v3", "low", check_newsletter, ("Keep acceptance gate mandatory.", "Keep Capability Radar frontloaded."), required=True, tags=("hermes", "reporting")),
    Channel("docs-watcher", "Docs watcher", "Silent upstream opportunity alerts", "no-agent cron", "low", check_docs_watcher, ("Keep no_agent=true.", "Silent stdout means healthy/no-change."), required=True, tags=("hermes", "cron")),
    Channel("agent-reach", "Agent-Reach upstream", "External broad internet scaffold", "sandbox only", "high", check_agent_reach_upstream, ("Do not install into main Hermes by default.", "Clone/test in /tmp or a venv.", "Adopt individual safe backends only after doctor proof."), approval_required=True, hermes_native=False, tags=("external", "sandbox")),
)


# ── API ────────────────────────────────────────────────────────────────────

def get_channel(key: str) -> Channel:
    for channel in CHANNELS:
        if channel.key == key:
            return channel
    raise KeyError(key)


def check_all() -> list[tuple[Channel, CheckResult]]:
    return [(channel, channel.check()) for channel in CHANNELS]


def check_all_parallel(max_workers: int = 6) -> list[tuple[Channel, CheckResult]]:
    """Run all channel checks concurrently via thread pool. Channels are independent."""
    results: list[tuple[Channel, CheckResult]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_channel = {executor.submit(channel.check): channel for channel in CHANNELS}
        for future in as_completed(future_to_channel):
            channel = future_to_channel[future]
            try:
                results.append((channel, future.result()))
            except Exception as exc:
                results.append((channel, _result("fail", f"Check raised: {exc}", error_kind="none")))
    # Preserve channel definition order
    key_order = {ch.key: i for i, ch in enumerate(CHANNELS)}
    results.sort(key=lambda pair: key_order.get(pair[0].key, 999))
    return results


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
