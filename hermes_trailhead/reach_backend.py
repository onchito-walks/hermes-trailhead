"""Optional Agent Reach backend — reuse, not clone.

Agent Reach (https://github.com/Panniantong/Agent-Reach) ships read-only accessors
for platforms Trailhead's native lanes do not cover (bilibili, v2ex, boss,
xueqiu, xiaohongshu, ...).  This module *forwards* to an already-installed
``agent-reach`` executable when the operator asks for it.  It is deliberately
not a reimplementation and never pretends the items are Trailhead-native.

Hard rules encoded here
-----------------------
* **Explicit, never auto-installed.**  The executable comes from an explicit
  argument, ``TRAILHEAD_AGENT_REACH_BIN``, or ``shutil.which("agent-reach")``.
  Nothing is downloaded, installed, updated, or configured from this module.
* **Read-only allowlist.**  Only channel/action pairs listed in
  ``READ_ONLY_ACTION_ALLOWLIST`` can run.  Management verbs (``setup``,
  ``add``, ``remove``, ``login``, ``logout``, ``browser``, ``configure``,
  ``update``, ``uninstall``, ``skill``, ``doctor``, ``check``) are rejected
  before a process is spawned.
* **Quota actions are visible but double-gated.**  ``youtube transcribe`` and
  ``xiaoyuzhou transcribe`` appear in the discoverable inventory so agents can
  see the gap, but they never run by default.  A call needs
  ``allow_quota_consuming=True`` *and* ``allow_authenticated=True`` (the
  Whisper backends read the operator's configured key), and
  ``TRAILHEAD_DISABLE_ASR=1`` vetoes them even when both flags are passed.  The
  veto is process-wide: it is read from the real process environment **or**
  from a caller-supplied ``env`` mapping, so an empty override cannot clear a
  veto that is set for the process.  ``READ_ONLY_ACTION_ALLOWLIST`` stays free
  of them, so a normal search run cannot reach a billable endpoint through this
  module.
* **No shell, argument arrays only.**  ``subprocess`` is invoked with a list
  and ``shell=False``.  Positional targets are separated with ``--`` and a
  leading ``-`` is rejected outright, so a target can never become an option.
* **Output is bounded while it is captured, and the process group is
  killable.**  The default runner is ``Popen``-based (not ``subprocess.run``):
  both pipes are drained here and the kept buffers stop at
  ``MAX_OUTPUT_BYTES`` (stdout) and ``MAX_STDERR_BYTES`` (stderr), so a
  flooding upstream is cut off instead of buffered and measured afterwards.  On
  POSIX the child gets its own session, so a timeout, a stdout overflow, or a
  child that exited while a descendant still holds the pipes kills the whole
  process group.  Known limit: Windows has no process group to signal, so only
  the direct child is killed there and a helper it spawned can outlive the call
  (the byte caps and the wall-clock budget still apply).
* **Untrusted registry.**  ``agent-reach channels`` is validated field by
  field (schema version, names, params, backend labels, public-web prefixes)
  and cached.  Malformed output is an error, not a best-effort guess.
* **Public mode is public, and blind.**  When ``allow_authenticated`` is
  false the child process runs with a private, empty temporary ``HOME``
  (``XDG_*``, ``APPDATA``, ``LOCALAPPDATA`` included), deleted when the call
  returns.  The operator's ``HOME`` and the ``TRAILHEAD_AGENT_REACH_HOME``
  override are ignored, so ``~/.agent-reach`` config, ``~/.config/gh``
  credentials, and stored sessions are unreachable.  Route selection is
  per-action: a declared public-web scope is forced to
  ``--backend public-web``, a declared public API backend (``github-api``,
  ``v2ex-api``, ``bilibili-api``, ``tencent``) is forced explicitly, and only
  actions reached solely through a login are reported as ``auth_required``
  without spawning anything.  A declared ``session``/``browser`` login on the
  channel does not by itself make its public actions authenticated.
* **The route is verified, not assumed.**  When a backend was forced and the
  successful payload reports a different one, the result is
  ``route_violation`` — ``ok: false``, zero items — instead of forwarding
  content from an unverified route.
* **Untrusted response text is bounded and redacted, not trusted.**  Item
  titles, authors, timestamps and URLs are clipped to the output budget, and
  the upstream ``backend`` label is clipped too — a hostile payload cannot
  inflate one result past the advertised envelope.  Registry stderr,
  execution stderr, and upstream ``error``/``meta.attempts`` fields are passed
  through best-effort pattern redaction for common API-key/token/bearer shapes
  and ``scheme://user:password@host`` URLs.  This is pattern redaction of a
  known-shape vocabulary, not a guarantee that third-party output can never
  contain a secret; a hostile upstream can still print one in a novel format.
* **Credentials come from upstream's own HOME config, never from our
  environment.**  Consented mode forwards the operator's ``HOME``/``XDG_*``
  paths so the already-configured upstream CLI can read its own key store;
  ``_ENV_PASSTHROUGH`` never includes an API key, token, or cookie, in either
  mode.  Public mode has neither the paths nor the variables.
* **Attribution stays intact.**  Every result carries provenance naming Agent
  Reach as the producing engine and lists the forwarding limitations.
* **A shell is not a successful read.**  Forwarded detail reads (``read`` /
  ``thread`` / ``comments``) are supposed to return a page body.  When upstream
  says ``ok: true`` but the body is only an access block or a missing-page
  shell ("You've been blocked by network security", "你访问的页面不见了",
  LinkedIn's multilingual 404), those items are withheld and, if nothing usable
  remains, the result is ``content_unusable`` — never ``ok: true``.  A row with
  no body text at all is held to the same bar: an empty ``read`` ``text`` (with
  or without a metadata ``raw``) is a missing artifact, not a successful read,
  and is reported as ``content_unusable`` with the ``empty_body`` reason.  The
  judgement for shell text delegates to
  :func:`hermes_trailhead.extract.classify_page_shell` so extraction and
  forwarding share one classifier.  Metadata-only actions (``v2ex user``,
  ``bilibili hot``, ``xueqiu search``, ...) legitimately carry no body text and
  are never filtered.
"""
from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

# One usability classifier for extracted pages and forwarded items alike: a
# blocked/missing-page shell must never be counted as a successful read by
# either path.  (extract imports backends/search, never this module.)
from .extract import classify_page_shell


AGENT_REACH_ENV = "TRAILHEAD_AGENT_REACH_BIN"
AGENT_REACH_HOME_ENV = "TRAILHEAD_AGENT_REACH_HOME"

ENGINE = "agent-reach"
SCHEMA_VERSION = 1

MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 120.0
DEFAULT_TIMEOUT = 30.0

MIN_LIMIT = 1
MAX_LIMIT = 50
MAX_TEXT_CHARS = 4000
MAX_VALUE_CHARS = 1024
#: Item URLs are longer than a plain text field but still bounded: a hostile
#: payload must not inflate one result past the forwarded envelope.
MAX_URL_CHARS = 2048
#: Upstream route labels are short by contract (``BACKEND_LABEL_RE`` allows 64);
#: anything longer is untrusted noise, and it is echoed in provenance/errors.
MAX_BACKEND_CHARS = 128
MAX_ITEMS = 50
MAX_REGISTRY_CHANNELS = 64
MAX_REGISTRY_ACTIONS = 64
#: Byte cap on captured stdout, enforced by the runner *while* draining (see
#: ``_default_runner``) and re-checked on the decoded text before parsing.
MAX_OUTPUT_BYTES = 4_000_000
#: stderr is only ever forwarded as a short diagnostic (300 characters), so it
#: has its own, much smaller capture cap: past that point the stream is drained
#: and discarded rather than buffered, and a chatty CLI is not failed for it.
MAX_STDERR_BYTES = 65_536

#: ``agent-reach`` verbs that mutate state, install software, drive a browser,
#: or touch credentials.  They are never valid *channel* names here.
FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "setup",
        "add",
        "remove",
        "login",
        "logout",
        "browser",
        "configure",
        "update",
        "uninstall",
        "skill",
        "doctor",
        "check",
        "help",
        "version",
        "channels",
        "read",
    }
)

#: Actions that mutate, cost money, or are management verbs.
FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    {
        "login",
        "logout",
        "setup",
        "add",
        "remove",
        "configure",
        "update",
        "uninstall",
    }
)

#: Actions handled by an explicit consent gate instead of the ordinary
#: allowlist.  Kept empty for now: quota actions have their own allowlist so the
#: read-only surface can never reach them.
EXCLUDED_ACTIONS: dict[str, str] = {}

#: Paid / key-consuming actions.  They are *discoverable* (an agent can see the
#: gap) but require ``allow_quota_consuming`` **and** ``allow_authenticated``,
#: and ``TRAILHEAD_DISABLE_ASR=1`` vetoes them even then.  This mapping is the
#: only way a billable action can enter the execution path.
QUOTA_ACTION_ALLOWLIST: dict[str, frozenset[str]] = {
    "youtube": frozenset({"transcribe"}),
    "xiaoyuzhou": frozenset({"transcribe"}),
}

#: Environment veto shared with the native media ASR tier (``extract.py``).
ASR_DISABLE_ENV = "TRAILHEAD_DISABLE_ASR"

#: Actions whose item text is meant to be a fetched page body — the complete
#: artifact the caller asked for.  Only these are held to the "readable body"
#: bar; discovery actions (``search``, ``jobs``, ``hot``, ``quote``) return
#: leads/records where a snippet or empty text is normal, and metadata actions
#: (``v2ex user``, ``bilibili hot``, ``xueqiu search``, ...) carry structured
#: ``raw`` fields with no body text at all.
BODY_READ_ACTIONS: frozenset[str] = frozenset({"read", "thread", "comments"})

#: The complete read-only surface this backend is willing to forward.
READ_ONLY_ACTION_ALLOWLIST: dict[str, frozenset[str]] = {
    "github": frozenset({"search", "read"}),
    "v2ex": frozenset({"hot", "node", "read", "user"}),
    "youtube": frozenset({"read", "search", "subtitle"}),
    "web": frozenset({"search", "read"}),
    "twitter": frozenset({"search", "profile", "tweets", "thread"}),
    "reddit": frozenset({"search", "read", "subreddit"}),
    "facebook": frozenset({"search", "profile"}),
    "instagram": frozenset({"search", "profile", "posts"}),
    "xiaohongshu": frozenset({"search", "read", "comments"}),
    "linkedin": frozenset({"jobs", "read"}),
    "boss": frozenset({"search", "read"}),
    "bilibili": frozenset({"search", "read", "hot", "subtitle"}),
    "xueqiu": frozenset({"quote", "search", "hot_posts", "hot_stocks"}),
}

#: Everything the inventory advertises: read-only plus the double-gated quota
#: actions.  ``capabilities()`` uses this; execution still branches on which
#: allowlist matched.
DISCOVERABLE_ACTION_ALLOWLIST: dict[str, frozenset[str]] = {
    **READ_ONLY_ACTION_ALLOWLIST,
    "youtube": READ_ONLY_ACTION_ALLOWLIST["youtube"] | QUOTA_ACTION_ALLOWLIST["youtube"],
    "xiaoyuzhou": QUOTA_ACTION_ALLOWLIST["xiaoyuzhou"],
}

#: Frozen comparison reference.  Only this commit may be used to claim parity.
PINNED_UPSTREAM: dict[str, Any] = {
    "project": "Panniantong/Agent-Reach",
    "url": "https://github.com/Panniantong/Agent-Reach",
    "version": "1.6.0",
    "commit": "14c213405669414492bda0f8d52cc6531d062c45",
    "channels": 14,
    "actions": 40,
    "measured": "2026-10-28",
}

#: State vocabulary used by the parity inventory.  ``native`` means Trailhead
#: produces the same artifact itself, ``native-partial`` means it produces part
#: of it, ``upstream`` means only Agent Reach covers it.
COVERAGE_STATES: tuple[str, ...] = ("native", "native-partial", "upstream")

#: Gate vocabulary.  ``public`` can run without consent; ``consent`` needs
#: ``allow_authenticated``; ``quota`` needs both consent flags and is vetoed by
#: ``TRAILHEAD_DISABLE_ASR=1``.
GATE_STATES: tuple[str, ...] = ("public", "consent", "quota")

#: Per-action public API backends, in preference order, for channels whose
#: upstream entry also declares a login.  A label is only used when the action
#: declares it in ``backends``; the match is forced with ``--backend`` so the
#: call cannot fall through to a session/browser backend.
#:
#: * ``bilibili`` search/hot/read work without a login (``bilibili-api`` is
#:   plain HTTP; ``bili-cli`` is login-free but needs the local tool installed).
#:   ``subtitle`` needs the bili-cli credential, so it stays authenticated.
#: * ``xueqiu`` quote/search have a public Tencent backend; ``hot_posts`` and
#:   ``hot_stocks`` are xueqiu-api only and need the browser session cookie.
#: * ``github`` ``gh`` uses ``~/.config/gh``; ``github-api`` needs no credential.
PUBLIC_API_BACKENDS: dict[str, dict[str, tuple[str, ...]]] = {
    "github": {"search": ("github-api",), "read": ("github-api",)},
    "v2ex": {action: ("v2ex-api",) for action in ("hot", "node", "read", "user")},
    "bilibili": {
        "hot": ("bilibili-api",),
        "read": ("bilibili-api",),
        "search": ("bili-cli",),
    },
    "xueqiu": {"quote": ("tencent",), "search": ("tencent",)},
}

CHANNEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ACTION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
PARAM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BACKEND_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")

_PARAM_TYPES = frozenset({"str", "int", "float", "bool"})
_NON_POSITIONAL_PARAMS = frozenset({"target", "url", "link", "href", "repo"})

#: Scheme prefixes that are never acceptable, whatever the parameter name.
_DANGEROUS_SCHEMES = frozenset(
    {"javascript", "data", "file", "vbscript", "about", "chrome", "ftp", "gopher", "smb", "telnet"}
)
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")

#: Best-effort redaction for untrusted upstream text (registry stderr, execution
#: stderr, ``error`` fields, attempt rows).  It matches common credential
#: *shapes* and ``scheme://user:password@host`` URLs.  It does not prove a
#: third-party message is free of secrets: an upstream that prints a credential
#: in an unrecognized shape still gets through.  No dependency beyond ``re``.
_SECRET_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credential-bearing URL: scheme://user:password@host -> scheme://[..]@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
        r"\1[redacted-credentials]@",
    ),
    # Authorization: Bearer <token>
    (
        re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{6,}"),
        r"\1 [redacted-token]",
    ),
    # name=value / name: value for credential-shaped names (api_key, token, ...)
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.\-]*"
            r"(?:api[_-]?key|apikey|token|secret|password|passwd|credential|authorization)"
            r"[A-Za-z0-9_.\-]*\s*[:=]\s*)(['\"]?)([^\s'\",;}\]]{4,})"
        ),
        r"\1\2[redacted]",
    ),
    # Well-known token/key shapes.
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"), "[redacted-key]"),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        "[redacted-token]",
    ),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"), "[redacted-token]"),
    (
        re.compile(r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,}|gsk_[A-Za-z0-9]{20,})\b"),
        "[redacted-key]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b"),
        "[redacted-jwt]",
    ),
)


def redact_secrets(text: Any, *, limit: int | None = None) -> str:
    """Redact common credential shapes from one untrusted upstream string.

    Redaction runs before ``limit`` truncation so a cut can never leave a
    partial token behind.  Applied to every upstream error channel this module
    forwards; it is pattern-based and explicitly not a universal guarantee.
    """
    out = text if isinstance(text, str) else ("" if text is None else str(text))
    for pattern, replacement in _SECRET_RULES:
        out = pattern.sub(replacement, out)
    if limit is not None:
        out = out[:limit]
    return out

#: Only these environment keys reach the child process.  No tokens, API keys,
#: cookie jars, or browser profiles are forwarded by this module.
_ENV_PASSTHROUGH = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "PATHEXT",
)

#: Home/config keys.  Forwarded only in consented authenticated mode; in public
#: mode they are redirected into a throwaway directory instead.
_ENV_HOME_KEYS = (
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)

#: Temp-home layout for public mode: (env key, path components under the home).
_PUBLIC_HOME_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HOME", ()),
    ("USERPROFILE", ()),
    ("XDG_CONFIG_HOME", (".config",)),
    ("XDG_CACHE_HOME", (".cache",)),
    ("XDG_DATA_HOME", (".local", "share")),
    ("XDG_STATE_HOME", (".local", "state")),
    ("APPDATA", ("AppData", "Roaming")),
    ("LOCALAPPDATA", ("AppData", "Local")),
)

LIMITATION_FORWARDED = (
    "Items are produced by the third-party Agent Reach CLI and forwarded by "
    "Trailhead without native scoring or extraction."
)
LIMITATION_NOT_INSTALLED = (
    "Trailhead never installs, configures, updates, or logs in to Agent Reach."
)
LIMITATION_PUBLIC = (
    "Public-only mode: no authenticated session and no browser fallback were used."
)
LIMITATION_PUBLIC_HOME = (
    "The upstream process ran with a private empty HOME and redirected "
    "config/cache variables; that is environment isolation, not a filesystem "
    "sandbox, so operator files remain readable by absolute path."
)
LIMITATION_PUBLIC_WEB = (
    "Upstream ran with --backend public-web, which forbids browser fallback."
)
LIMITATION_AUTHENTICATED = (
    "Ran with allow_authenticated=True against the operator's existing Agent "
    "Reach login state; Trailhead did not create, copy, or refresh it."
)
LIMITATION_QUOTA = (
    "Ran with allow_quota_consuming=True: the upstream action may bill a "
    "Whisper/Groq/OpenAI endpoint. Trailhead did not meter or cap that spend."
)


# ── errors ────────────────────────────────────────────────────────────────


class ReachBackendError(Exception):
    """Base error for this module."""


class ReachUnavailable(ReachBackendError):
    """No usable ``agent-reach`` executable was found."""


class RegistryError(ReachBackendError):
    """The upstream ``channels`` payload failed schema validation."""


class InvalidRequest(ReachBackendError):
    """The requested channel/action/parameters are not allowed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── registry model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReachParam:
    name: str
    required: bool = False
    type: str = "str"
    default: Any = None
    help: str = ""


@dataclass(frozen=True)
class ReachAction:
    name: str
    help: str
    params: tuple[ReachParam, ...] = ()
    public_web: tuple[str, ...] = ()
    backends: tuple[str, ...] = ()

    @property
    def required_params(self) -> tuple[ReachParam, ...]:
        return tuple(p for p in self.params if p.required)

    @property
    def optional_params(self) -> tuple[ReachParam, ...]:
        return tuple(p for p in self.params if not p.required)


@dataclass(frozen=True)
class ReachChannel:
    name: str
    description: str
    level: str
    login_via: str | None
    actions: dict[str, ReachAction] = field(default_factory=dict)

    @property
    def requires_login(self) -> bool:
        return self.login_via is not None


@dataclass(frozen=True)
class ReachMode:
    """How one channel/action pair can be reached with this backend."""

    channel: str
    action: str
    mode: str  # "public_web" | "public_api" | "authenticated" | "quota"
    public: bool
    reason: str
    forced_backend: str | None = None
    quota_consuming: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "action": self.action,
            "mode": self.mode,
            "public": self.public,
            "reason": self.reason,
            "forced_backend": self.forced_backend,
            "quota_consuming": self.quota_consuming,
        }


@dataclass(frozen=True)
class ReachRegistry:
    schema_version: int
    channels: dict[str, ReachChannel]

    def action(self, channel: str, action: str) -> ReachAction:
        try:
            return self.channels[channel].actions[action]
        except KeyError as exc:  # pragma: no cover - callers pre-check
            raise InvalidRequest("unknown_action", f"{channel} has no action {action!r}") from exc


@dataclass(frozen=True)
class ReachAvailability:
    found: bool
    path: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"found": self.found, "path": self.path, "reason": self.reason}


# ── pinned parity inventory ───────────────────────────────────────────────


@dataclass(frozen=True)
class ParityAction:
    """One upstream action and what Trailhead can honestly say about it.

    ``coverage`` answers "does Trailhead do this itself?"; ``evidence`` records
    how the row is known to work.  ``"fixture"`` means a contract test with a
    fake CLI, which is *not* live evidence; only an explicit ``"live"`` entry
    (with a dated record in the docs) claims a real run.
    """

    channel: str
    action: str
    coverage: str
    evidence: tuple[str, ...] = ("fixture",)
    note: str = ""

    @property
    def pair(self) -> tuple[str, str]:
        return (self.channel, self.action)

    @property
    def live_verified(self) -> bool:
        return "live" in self.evidence

    @property
    def fixture_only(self) -> bool:
        return not self.live_verified

    @property
    def gated(self) -> bool:
        return self.gate in ("consent", "quota")

    @property
    def gate(self) -> str:
        if self.channel in QUOTA_ACTION_ALLOWLIST and self.action in QUOTA_ACTION_ALLOWLIST[self.channel]:
            return "quota"
        mode = PUBLIC_API_BACKENDS.get(self.channel, {})
        if _DECLARED_PUBLIC_WEB.get((self.channel, self.action)):
            return "public"
        if self.action in mode:
            return "public"
        if self.channel in _PUBLIC_BY_DECLARATION:
            return "public"
        return "consent"

    @property
    def states(self) -> tuple[str, ...]:
        """Machine-readable state words for this row.

        The first word is always the exact ``coverage`` value, so a partial row
        reads ``native-partial`` rather than a misleading ``upstream`` +
        ``partial`` pair (the upstream action adds the remainder; Trailhead does
        produce part of the artifact).
        """
        states = [self.coverage]
        if self.gate == "consent":
            states.append("gated-auth")
        elif self.gate == "quota":
            states.append("gated-quota")
        if self.fixture_only:
            states.append("testing-fixture")
        return tuple(states)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "action": self.action,
            "coverage": self.coverage,
            "gate": self.gate,
            "states": list(self.states),
            "surfaced": self.pair in _SURFACED_PAIRS,
            "live_verified": self.live_verified,
            "evidence": list(self.evidence),
            "note": self.note,
        }


#: Channels the pinned registry declares with no login and no per-action
#: public-web scope, so their actions run without consent on their declared
#: backends.  Used only by :attr:`ParityAction.gate` so the inventory is static;
#: ``validate_parity_inventory`` cross-checks it against a live registry.
_PUBLIC_BY_DECLARATION: frozenset[str] = frozenset({"web", "youtube"})

#: Actions the pinned registry declares a public-web scope for (subset that is
#: not already public via a forced API backend).
_DECLARED_PUBLIC_WEB: dict[tuple[str, str], bool] = {
    ("twitter", "search"): True,
    ("reddit", "search"): True,
    ("reddit", "read"): True,
    ("facebook", "search"): True,
    ("xiaohongshu", "search"): True,
    ("xiaohongshu", "read"): True,
    ("linkedin", "jobs"): True,
    ("linkedin", "read"): True,
    ("boss", "search"): True,
    ("boss", "read"): True,
}

#: Exactly 40 actions across 14 channels, pinned to Agent Reach 1.6.0 at
#: ``PINNED_UPSTREAM["commit"]``.  Every row here is exercised by the focused
#: contract suite; only rows carrying ``"live"`` have a recorded real run.
PARITY_ACTIONS: tuple[ParityAction, ...] = (
    ParityAction("github", "search", "native", ("fixture", "native-tests", "live"),),
    ParityAction("github", "read", "native-partial", ("fixture", "native-tests"), "Native repo-root reads fetch the public README and repository metadata; issue/PR comment completeness remains partial."),
    ParityAction("twitter", "search", "native", ("fixture", "native-tests"),),
    ParityAction("twitter", "profile", "upstream", ("fixture",),),
    ParityAction("twitter", "tweets", "upstream", ("fixture",),),
    ParityAction("twitter", "thread", "upstream", ("fixture",),),
    ParityAction("youtube", "read", "native", ("fixture",),),
    ParityAction("youtube", "search", "native", ("fixture",),),
    ParityAction("youtube", "subtitle", "native", ("fixture", "native-tests"),),
    ParityAction("youtube", "transcribe", "native-partial", ("fixture", "native-tests"), "A native caption/ASR fallback exists in extract.py, but it is key-gated and not this forwarding path."),
    ParityAction("reddit", "search", "native", ("fixture", "native-tests", "live"),),
    ParityAction("reddit", "read", "native-partial", ("fixture",), "Trailhead extracts public page text; exhaustive reply capture is upstream's."),
    ParityAction("reddit", "subreddit", "native-partial", ("fixture",), "Trailhead lists posts via public search; upstream's node listing is the fuller artifact."),
    ParityAction("facebook", "search", "upstream", ("fixture",),),
    ParityAction("facebook", "profile", "upstream", ("fixture",),),
    ParityAction("instagram", "search", "upstream", ("fixture",),),
    ParityAction("instagram", "profile", "upstream", ("fixture",),),
    ParityAction("instagram", "posts", "upstream", ("fixture",),),
    ParityAction("bilibili", "search", "upstream", ("fixture",),),
    ParityAction("bilibili", "read", "upstream", ("fixture",),),
    ParityAction("bilibili", "hot", "upstream", ("fixture", "live"),),
    ParityAction("bilibili", "subtitle", "upstream", ("fixture",),),
    ParityAction("xiaohongshu", "search", "upstream", ("fixture",),),
    ParityAction("xiaohongshu", "read", "upstream", ("fixture",),),
    ParityAction("xiaohongshu", "comments", "upstream", ("fixture",),),
    ParityAction("linkedin", "jobs", "upstream", ("fixture",),),
    ParityAction("linkedin", "read", "upstream", ("fixture",),),
    ParityAction("boss", "search", "upstream", ("fixture",),),
    ParityAction("boss", "read", "upstream", ("fixture",),),
    ParityAction("v2ex", "hot", "upstream", ("fixture", "live"),),
    ParityAction("v2ex", "node", "upstream", ("fixture",),),
    ParityAction("v2ex", "read", "upstream", ("fixture",),),
    ParityAction("v2ex", "user", "upstream", ("fixture",),),
    ParityAction("xueqiu", "quote", "upstream", ("fixture", "live"),),
    ParityAction("xueqiu", "search", "upstream", ("fixture",),),
    ParityAction("xueqiu", "hot_posts", "upstream", ("fixture",),),
    ParityAction("xueqiu", "hot_stocks", "upstream", ("fixture",),),
    ParityAction("xiaoyuzhou", "transcribe", "upstream", ("fixture",),),
    ParityAction("web", "search", "native", ("fixture", "native-tests"),),
    ParityAction("web", "read", "native", ("fixture", "native-tests"),),
)

_SURFACED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    (channel, action)
    for channel, actions in DISCOVERABLE_ACTION_ALLOWLIST.items()
    for action in actions
)


def parity_inventory() -> dict[str, Any]:
    """The pinned 40-action inventory, with honest state labels.

    Static: no network, no executable, no registry call.  ``live_verified`` is
    true only where a dated real run is recorded in the docs; a fixture test is
    reported as ``testing-fixture`` and never as live.
    """
    rows = [row.to_dict() for row in PARITY_ACTIONS]
    channels = sorted({row["channel"] for row in rows})
    live = [row for row in rows if row["live_verified"]]
    surfaced = sum(1 for row in rows if row["surfaced"])
    return {
        "reference": dict(PINNED_UPSTREAM),
        "counts": {
            "channels": len(channels),
            "actions": len(rows),
            "surfaced": surfaced,
            # Surfaced / total, computed here so no caller has to guess it.
            "surfaced_ratio": (surfaced / len(rows)) if rows else 0.0,
            "native": sum(1 for row in rows if row["coverage"] == "native"),
            "native_partial": sum(1 for row in rows if row["coverage"] == "native-partial"),
            "upstream_only": sum(1 for row in rows if row["coverage"] == "upstream"),
            "public": sum(1 for row in rows if row["gate"] == "public"),
            "gated_auth": sum(1 for row in rows if row["gate"] == "consent"),
            "gated_quota": sum(1 for row in rows if row["gate"] == "quota"),
            "live_verified": len(live),
            "fixture_only": len(rows) - len(live),
        },
        "live_verified_actions": [f"{row['channel']} {row['action']}" for row in live],
        "states": {
            "coverage": list(COVERAGE_STATES),
            "gates": list(GATE_STATES),
            "evidence": [
                "native-tests",
                "fixture",
                "live",
            ],
            "legend": (
                "fixture/native-tests are local contract tests, not live "
                "evidence; only 'live' rows have a recorded real run."
            ),
        },
        "actions": rows,
    }


def validate_parity_inventory(registry: ReachRegistry | None = None) -> None:
    """Fail loudly if the inventory drifts from the pinned reference.

    Without a registry only internal consistency is checked (counts, unique
    pairs, state vocabulary, surfaced rows).  With a parsed upstream registry
    the exact channel/action set is compared, so upstream drift is an error
    rather than a silent mismatch.
    """
    if not PARITY_ACTIONS:
        raise ValueError("parity inventory is empty")
    pairs = [row.pair for row in PARITY_ACTIONS]
    if len(pairs) != len(set(pairs)):
        raise ValueError("parity inventory contains duplicate channel/action pairs")
    if len(pairs) != PINNED_UPSTREAM["actions"]:
        raise ValueError(
            f"parity inventory has {len(pairs)} actions, pinned reference has "
            f"{PINNED_UPSTREAM['actions']}"
        )
    channels = {row.channel for row in PARITY_ACTIONS}
    if len(channels) != PINNED_UPSTREAM["channels"]:
        raise ValueError(
            f"parity inventory has {len(channels)} channels, pinned reference has "
            f"{PINNED_UPSTREAM['channels']}"
        )
    for row in PARITY_ACTIONS:
        if row.coverage not in COVERAGE_STATES:
            raise ValueError(f"{row.channel} {row.action} has an unknown coverage state")
        if row.gate not in GATE_STATES:
            raise ValueError(f"{row.channel} {row.action} has an unknown gate state")
        if row.pair not in _SURFACED_PAIRS:
            raise ValueError(f"{row.channel} {row.action} is not surfaced by the allowlists")
    # Every pair the allowlists surface must have a row: a surfaced pair with no
    # inventory row would inflate ``surfaced / total`` beyond 1.
    unlisted = sorted(_SURFACED_PAIRS - set(pairs))
    if unlisted:
        raise ValueError(f"surfaced pairs are missing from the inventory: {unlisted}")
    if registry is not None:
        registry_pairs = {
            (channel.name, action)
            for channel in registry.channels.values()
            for action in channel.actions
        }
        missing = sorted(registry_pairs - set(pairs))
        extra = sorted(set(pairs) - registry_pairs)
        if missing or extra:
            raise ValueError(
                "parity inventory does not match the pinned registry: "
                f"missing={missing} extra={extra}"
            )


# ── result model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReachResult:
    ok: bool
    channel: str | None
    action: str | None
    backend: str | None
    items: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    elapsed_ms: int | None = None
    attempts: tuple[dict[str, Any], ...] = ()
    exit_code: int | None = None
    timed_out: bool = False
    argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "engine": ENGINE,
            "channel": self.channel,
            "action": self.action,
            "backend": self.backend,
            "items": list(self.items),
            "error": self.error,
            "provenance": dict(self.provenance),
            "limitations": list(self.limitations),
            "elapsed_ms": self.elapsed_ms,
            "attempts": list(self.attempts),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "argv": list(self.argv),
        }


# ── discovery ─────────────────────────────────────────────────────────────


def discover_agent_reach(
    executable: str | None = None,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> ReachAvailability:
    """Resolve the ``agent-reach`` executable without installing anything.

    Order: explicit ``executable`` argument, then ``TRAILHEAD_AGENT_REACH_BIN``,
    then ``shutil.which("agent-reach")``.  The resolved path must be an
    executable regular file.
    """
    environ = os.environ if env is None else env
    resolver = shutil.which if which is None else which
    candidate = str(executable).strip() if executable is not None else ""
    source = "explicit"
    if not candidate:
        candidate = (environ.get(AGENT_REACH_ENV) or "").strip()
        source = "env"
    if not candidate:
        found = resolver("agent-reach")
        if found:
            return _check_executable(found, "path")
        return ReachAvailability(False, None, "not_installed")
    if os.sep not in candidate and (os.altsep is None or os.altsep not in candidate):
        found = resolver(candidate)
        if not found:
            return ReachAvailability(False, None, f"{source}_not_executable")
        return _check_executable(found, source)
    return _check_executable(candidate, source)


def _check_executable(path: str, source: str) -> ReachAvailability:
    if not os.path.exists(path):
        return ReachAvailability(False, None, f"{source}_missing")
    if os.path.isdir(path):
        return ReachAvailability(False, None, f"{source}_is_directory")
    if not os.path.isfile(path):
        return ReachAvailability(False, None, f"{source}_not_a_file")
    if not os.access(path, os.X_OK):
        return ReachAvailability(False, None, f"{source}_not_executable")
    return ReachAvailability(True, os.path.abspath(path), f"{source}_ok")


def _child_env(
    source: Mapping[str, str] | None,
    executable: str,
    *,
    public: bool,
    home: str | None = None,
) -> dict[str, str]:
    """Environment for the upstream process.

    Authenticated mode forwards the caller's own home/config variables so the
    existing upstream login is usable.  Public mode gets ``home`` (a fresh empty
    directory) for every credential-bearing variable, and never the operator's
    ``HOME`` or ``TRAILHEAD_AGENT_REACH_HOME`` override.

    Credential material is never read from this process's environment: no API
    key, token, or cookie variable is forwarded, in either mode.  Consented mode
    only hands upstream the ``HOME``/``XDG_*`` paths it uses to read **its own**
    config/key store, which is where the Whisper backends get their key.  In
    both modes only ``_ENV_PASSTHROUGH`` plus the home keys below are copied.
    """
    if public and not home:
        raise ValueError("public mode requires an isolated home directory")
    base = dict(os.environ if source is None else source)
    env = {key: str(base[key]) for key in _ENV_PASSTHROUGH if base.get(key)}
    if public:
        root = os.path.abspath(str(home))
        for key, parts in _PUBLIC_HOME_KEYS:
            env[key] = os.path.join(root, *parts) if parts else root
    else:
        override = (base.get(AGENT_REACH_HOME_ENV) or "").strip()
        if override:
            # A caller-supplied home is meant to isolate the run, so every
            # credential-bearing variable moves inside it instead of half of
            # them still pointing at the operator's real config.
            root = os.path.abspath(override)
            for key, parts in _PUBLIC_HOME_KEYS:
                env[key] = os.path.join(root, *parts) if parts else root
        else:
            for key in _ENV_HOME_KEYS:
                if base.get(key):
                    env[key] = str(base[key])
    exe_dir = os.path.dirname(os.path.abspath(executable))
    path = env.get("PATH") or os.defpath
    parts_path = [p for p in path.split(os.pathsep) if p]
    if exe_dir not in parts_path:
        parts_path.insert(0, exe_dir)
    env["PATH"] = os.pathsep.join(parts_path)
    return env


@contextmanager
def _isolated_home() -> Iterator[str]:
    """A private, empty ``HOME`` that is deleted when the block exits."""
    with tempfile.TemporaryDirectory(prefix="trailhead-agent-reach-home-") as home:
        yield home


_ASR_TRUTHY = frozenset({"1", "true", "yes", "on"})


def asr_disabled(env: Mapping[str, str] | None = None) -> bool:
    """Is the process-wide ASR veto set?  Mirrors ``extract.py``'s meaning.

    The veto is an OR, never a replacement: it is true when
    ``TRAILHEAD_DISABLE_ASR`` is set in the real process environment **or** in
    the supplied mapping.  A caller-supplied ``env={}`` (or one that omits the
    key) therefore cannot bypass a veto that holds for the process — an
    override can only add a veto, never clear one.
    """
    for source in (os.environ, env):
        if source is None:
            continue
        if (source.get(ASR_DISABLE_ENV) or "").strip().lower() in _ASR_TRUTHY:
            return True
    return False


# ── registry parsing (untrusted input) ────────────────────────────────────


def parse_registry(payload: Any) -> ReachRegistry:
    """Validate a parsed ``agent-reach channels`` payload.

    Everything is checked: the envelope, schema version, channel/action names,
    parameter declarations, backend labels, and public-web prefixes.  Unknown
    fields are ignored; wrong types are rejected.
    """
    if not isinstance(payload, dict):
        raise RegistryError("channels output is not a JSON object")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION or not isinstance(version, int) or isinstance(version, bool):
        raise RegistryError(f"unsupported schema_version: {version!r}")
    if payload.get("ok") is not True:
        raise RegistryError("channels output did not report ok=true")
    raw_channels = payload.get("channels")
    if not isinstance(raw_channels, list) or not raw_channels:
        raise RegistryError("channels output has no channel list")
    if len(raw_channels) > MAX_REGISTRY_CHANNELS:
        raise RegistryError("channels output exceeds the channel bound")

    channels: dict[str, ReachChannel] = {}
    for raw in raw_channels:
        channel = _parse_channel(raw)
        if channel.name in channels:
            raise RegistryError(f"duplicate channel: {channel.name}")
        channels[channel.name] = channel
    return ReachRegistry(schema_version=SCHEMA_VERSION, channels=channels)


def _require_str(value: Any, what: str, *, limit: int = 2048) -> str:
    if not isinstance(value, str):
        raise RegistryError(f"{what} must be a string")
    if len(value) > limit:
        raise RegistryError(f"{what} is longer than {limit} characters")
    return value


def _parse_channel(raw: Any) -> ReachChannel:
    if not isinstance(raw, dict):
        raise RegistryError("channel entry is not an object")
    name = _require_str(raw.get("name"), "channel name", limit=64)
    if not CHANNEL_NAME_RE.match(name):
        raise RegistryError(f"invalid channel name: {name!r}")
    description = _require_str(raw.get("description", ""), f"{name}.description")
    level = _require_str(raw.get("level", ""), f"{name}.level", limit=32)
    login_via = _parse_login(name, raw.get("login"))

    raw_actions = raw.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise RegistryError(f"{name} has no actions")
    if len(raw_actions) > MAX_REGISTRY_ACTIONS:
        raise RegistryError(f"{name} exceeds the action bound")

    actions: dict[str, ReachAction] = {}
    for raw_action in raw_actions:
        action = _parse_action(name, raw_action)
        if action.name in actions:
            raise RegistryError(f"duplicate action: {name} {action.name}")
        actions[action.name] = action
    return ReachChannel(
        name=name,
        description=description,
        level=level,
        login_via=login_via,
        actions=actions,
    )


def _parse_login(channel: str, raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RegistryError(f"{channel}.login must be null or an object")
    via = raw.get("via")
    if via not in ("browser", "session"):
        raise RegistryError(f"{channel}.login.via is invalid: {via!r}")
    logged_in = raw.get("logged_in")
    if logged_in is not None and not isinstance(logged_in, bool):
        raise RegistryError(f"{channel}.login.logged_in must be bool or null")
    command = raw.get("command")
    if command is not None:
        _require_str(command, f"{channel}.login.command", limit=128)
    return via


def _parse_action(channel: str, raw: Any) -> ReachAction:
    if not isinstance(raw, dict):
        raise RegistryError(f"{channel} action entry is not an object")
    name = _require_str(raw.get("name"), f"{channel} action name", limit=64)
    if not ACTION_NAME_RE.match(name):
        raise RegistryError(f"invalid action name: {name!r}")
    help_text = _require_str(raw.get("help", ""), f"{channel}.{name}.help")

    raw_params = raw.get("params", [])
    if not isinstance(raw_params, list):
        raise RegistryError(f"{channel}.{name}.params must be a list")
    if len(raw_params) > 16:
        raise RegistryError(f"{channel}.{name} declares too many params")
    params: list[ReachParam] = []
    seen: set[str] = set()
    for raw_param in raw_params:
        param = _parse_param(channel, name, raw_param)
        if param.name in seen:
            raise RegistryError(f"duplicate param: {channel}.{name}.{param.name}")
        seen.add(param.name)
        params.append(param)

    raw_public = raw.get("public_web", [])
    if not isinstance(raw_public, list) or len(raw_public) > 16:
        raise RegistryError(f"{channel}.{name}.public_web must be a short list")
    public_web: list[str] = []
    for prefix in raw_public:
        text = _require_str(prefix, f"{channel}.{name}.public_web entry", limit=256)
        if not text.strip() or any(ch.isspace() for ch in text):
            raise RegistryError(f"{channel}.{name} has a malformed public_web prefix")
        public_web.append(text)

    raw_backends = raw.get("backends", [])
    if not isinstance(raw_backends, list) or len(raw_backends) > 16:
        raise RegistryError(f"{channel}.{name}.backends must be a short list")
    backends: list[str] = []
    for label in raw_backends:
        text = _require_str(label, f"{channel}.{name}.backend label", limit=64)
        if not BACKEND_LABEL_RE.match(text):
            raise RegistryError(f"{channel}.{name} has an invalid backend label")
        backends.append(text)

    return ReachAction(
        name=name,
        help=help_text,
        params=tuple(params),
        public_web=tuple(public_web),
        backends=tuple(backends),
    )


def _parse_param(channel: str, action: str, raw: Any) -> ReachParam:
    if not isinstance(raw, dict):
        raise RegistryError(f"{channel}.{action} param entry is not an object")
    name = _require_str(raw.get("name"), f"{channel}.{action} param name", limit=32)
    if not PARAM_NAME_RE.match(name):
        raise RegistryError(f"invalid param name: {name!r}")
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise RegistryError(f"{channel}.{action}.{name}.required must be bool")
    ptype = raw.get("type", "str")
    if ptype not in _PARAM_TYPES:
        raise RegistryError(f"{channel}.{action}.{name}.type is unsupported: {ptype!r}")
    default = raw.get("default")
    if default is not None and not isinstance(default, (str, int, float, bool)):
        raise RegistryError(f"{channel}.{action}.{name}.default has an unsupported type")
    help_text = raw.get("help", "")
    if not isinstance(help_text, str):
        raise RegistryError(f"{channel}.{action}.{name}.help must be a string")
    return ReachParam(name=name, required=required, type=ptype, default=default, help=help_text)


# ── parameter / target validation ─────────────────────────────────────────


def _reject_control_chars(value: str, name: str) -> None:
    for ch in value:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise InvalidRequest(
                "unsafe_target",
                f"parameter {name!r} contains a control character",
            )


def _validate_str(value: str, name: str, *, max_len: int = MAX_VALUE_CHARS) -> str:
    if not isinstance(value, str):
        raise InvalidRequest("invalid_params", f"parameter {name!r} must be a string")
    if not value.strip():
        raise InvalidRequest("invalid_params", f"parameter {name!r} is empty")
    if len(value) > max_len:
        raise InvalidRequest(
            "invalid_params",
            f"parameter {name!r} is longer than {max_len} characters",
        )
    _reject_control_chars(value, name)
    # Reject option-shaped positionals outright.  ``--`` is still used as
    # defence in depth, but a target must never look like a flag.
    if value.startswith("-"):
        raise InvalidRequest(
            "unsafe_target",
            f"parameter {name!r} starts with '-' and could be parsed as an option",
        )
    if "://" in value or _SCHEME_RE.match(value):
        match = _SCHEME_RE.match(value)
        scheme = match.group(1).lower() if match else ""
        if scheme in _DANGEROUS_SCHEMES:
            raise InvalidRequest(
                "unsafe_target",
                f"parameter {name!r} uses a forbidden URL scheme: {scheme}",
            )
        if name in _NON_POSITIONAL_PARAMS and scheme:
            if scheme not in ("http", "https"):
                raise InvalidRequest(
                    "unsafe_target",
                    f"parameter {name!r} must be an http(s) URL or a bare identifier",
                )
            parsed = urlparse(value)
            if not parsed.netloc:
                raise InvalidRequest("unsafe_target", f"parameter {name!r} has no host")
            if parsed.username or parsed.password:
                raise InvalidRequest(
                    "unsafe_target",
                    f"parameter {name!r} embeds credentials",
                )
    return value


def _validate_int(value: Any, name: str) -> str:
    if isinstance(value, bool):
        raise InvalidRequest("invalid_params", f"parameter {name!r} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,6}", value.strip()):
        number = int(value.strip())
    else:
        raise InvalidRequest("invalid_params", f"parameter {name!r} must be an integer")
    if name == "limit":
        if not MIN_LIMIT <= number <= MAX_LIMIT:
            raise InvalidRequest(
                "invalid_params",
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )
    elif number < 0 or number > 1_000_000:
        raise InvalidRequest("invalid_params", f"parameter {name!r} is out of bounds")
    return str(number)


def _coerce_params(action: ReachAction, params: Mapping[str, Any] | None) -> tuple[list[str], list[tuple[str, str]]]:
    """Split params into positionals (required) and ``--name value`` options."""
    if params is not None and not isinstance(params, Mapping):
        raise InvalidRequest("invalid_params", "params must be a mapping of parameter names")
    supplied = dict(params or {})
    declared = {p.name: p for p in action.params}
    unknown = sorted(str(key) for key in set(supplied) - set(declared))
    if unknown:
        raise InvalidRequest(
            "invalid_params",
            f"{action.name} does not accept parameter(s): {', '.join(unknown)}",
        )
    positionals: list[str] = []
    options: list[tuple[str, str]] = []
    for param in action.required_params:
        if param.name not in supplied or supplied[param.name] is None:
            raise InvalidRequest(
                "invalid_params",
                f"{action.name} requires parameter {param.name!r}",
            )
        value = supplied[param.name]
        text = _validate_int(value, param.name) if param.type == "int" else _validate_str(value, param.name)
        positionals.append(text)
    for param in action.optional_params:
        value = supplied.get(param.name)
        if value is None:
            continue
        text = _validate_int(value, param.name) if param.type == "int" else _validate_str(value, param.name)
        options.append((param.name, text))
    return positionals, options


def build_argv(
    executable: str,
    channel: str,
    action: str,
    *,
    positionals: Sequence[str] = (),
    options: Sequence[tuple[str, str]] = (),
    backend: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[str]:
    """Build the argument array for one read-only upstream call.

    Options come before ``--``; every positional follows the terminator so no
    target can be reinterpreted as a flag.
    """
    argv = [executable, channel, action]
    for name, value in options:
        argv.extend([f"--{name}", value])
    if backend:
        argv.extend(["--backend", backend])
    argv.extend(["--timeout", _format_timeout(timeout)])
    if positionals:
        argv.append("--")
        argv.extend(positionals)
    return argv


def _format_timeout(timeout: float) -> str:
    return f"{float(timeout):g}"


def _bounded_timeout(timeout: float | None) -> float:
    if timeout is None:
        return DEFAULT_TIMEOUT
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest("invalid_params", "timeout must be a number") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise InvalidRequest("invalid_params", "timeout must be finite")
    if value < MIN_TIMEOUT or value > MAX_TIMEOUT:
        raise InvalidRequest(
            "invalid_params",
            f"timeout must be between {MIN_TIMEOUT:g} and {MAX_TIMEOUT:g} seconds",
        )
    return value


# ── upstream call ─────────────────────────────────────────────────────────


def _bounded_items(max_items: int | None, default: int) -> int:
    if max_items is None:
        return default
    try:
        value = int(max_items)
    except (TypeError, ValueError, OverflowError) as exc:
        # ``int(float('inf'))`` raises OverflowError, which is not a ValueError;
        # it must not escape execute()'s documented "never raises" contract.
        raise InvalidRequest("invalid_params", "max_items must be an integer") from exc
    if value < 1:
        raise InvalidRequest("invalid_params", "max_items must be positive")
    return min(value, MAX_ITEMS)


def _constructor_items(max_items: int) -> int:
    """Constructor-time budget: a bad value falls back to the default.

    ``execute()`` reports bad per-call input as an ``invalid_params`` result;
    construction is not a request, so it clamps instead of raising.
    """
    try:
        return _bounded_items(max_items, MAX_ITEMS)
    except InvalidRequest:
        return MAX_ITEMS


Runner = Callable[..., subprocess.CompletedProcess]

#: Bytes per drain read.  One chunk in flight is the only buffer beyond the caps.
_READ_CHUNK = 65_536

#: Seconds to keep draining after the direct child exits while something it
#: spawned still holds the pipes open.  Output that arrives after this is a
#: leaked descendant, not the child's answer, so the group is killed.
_PIPE_HOLD_GRACE = 1.0

#: Seconds to keep draining after the process group was killed, so the pipes
#: close and the child can be reaped without blocking forever.
_KILL_GRACE = 2.0


class BoundedCompletedProcess(subprocess.CompletedProcess):
    """``CompletedProcess`` plus what the bounded drain had to do.

    ``overflow`` means stdout crossed ``MAX_OUTPUT_BYTES`` and the producer was
    killed: the text is a truncated prefix, not the upstream answer, and the
    caller must report it as oversized rather than trying to parse it.
    ``stderr_truncated`` means stderr was drained but only its first
    ``MAX_STDERR_BYTES`` were kept.  ``killed`` records that the process group
    was signalled (timeout, stdout overflow, or a pipe-holding descendant).
    """

    overflow: bool = False
    stderr_truncated: bool = False
    killed: bool = False


class _Capture:
    """Bounded stdout/stderr buffers shared by both drain strategies."""

    def __init__(self) -> None:
        self.out = bytearray()
        self.err = bytearray()
        self.overflow = False
        self.stderr_truncated = False

    def feed(self, stream: str, chunk: bytes) -> bool:
        """Keep what fits; return True when stdout overflowed on this chunk."""
        if stream == "stdout":
            if self.overflow:
                return False
            room = MAX_OUTPUT_BYTES - len(self.out)
            if len(chunk) > room:
                self.out.extend(chunk[:room])
                self.overflow = True
                return True
            self.out.extend(chunk)
            return False
        room = MAX_STDERR_BYTES - len(self.err)
        if len(chunk) > room:
            self.err.extend(chunk[:room])
            self.stderr_truncated = True
        else:
            self.err.extend(chunk)
        return False


def _kill_process_group(proc: subprocess.Popen) -> bool:
    """Kill the child and anything it spawned.  True if a group was signalled.

    The child was started with ``start_new_session``, so its pid *is* its
    session/process-group id.  Signalling the pid directly (instead of
    ``os.getpgid(proc.pid)``) is deliberate: it still works after the direct
    child was reaped while a descendant kept the pipes open, which is exactly
    the leak this guard exists for.  Same pattern as
    ``comparative._kill_process_group``; it stays local because consolidating
    both helpers means editing that module, which is outside this change.

    Windows has no process group to signal here, so only the direct child is
    killed (``Popen.kill``) and a helper it spawned can outlive the call.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        return False
    return True


def _drain_selectors(
    proc: subprocess.Popen,
    capture: _Capture,
    deadline: float,
) -> tuple[bool, bool]:
    """POSIX drain: ``selectors`` over both pipes, bounded in time and bytes.

    Returns ``(timed_out, killed)``.  ``timed_out`` is only true when the
    wall-clock budget expired, never when the group was killed for an overflow
    or for a pipe-holding descendant — those keep their own meaning upstream.
    """
    selector = selectors.DefaultSelector()
    streams: dict[str, Any] = {}
    for name in ("stdout", "stderr"):
        stream = getattr(proc, name, None)
        if stream is None:
            continue
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
        streams[name] = stream
    timed_out = False
    killed = False
    stop_at = deadline
    child_exit_at: float | None = None
    try:
        while streams:
            now = time.monotonic()
            if child_exit_at is None and proc.poll() is not None:
                # The direct child is done.  Anything still writing is a
                # descendant holding an inherited pipe: give it a short grace,
                # then kill the group instead of waiting out the full timeout.
                child_exit_at = now
            orphan_deadline = (
                None if child_exit_at is None else child_exit_at + _PIPE_HOLD_GRACE
            )
            at_limit = now >= stop_at
            at_orphan = orphan_deadline is not None and now >= orphan_deadline
            if at_limit or at_orphan:
                if killed:
                    break  # the post-kill grace is spent too
                timed_out = at_limit and child_exit_at is None
                killed = _kill_process_group(proc)
                stop_at = now + _KILL_GRACE
                child_exit_at = None
                continue
            wait = max(0.0, min(stop_at - now, 0.25))
            if orphan_deadline is not None:
                wait = min(wait, max(0.0, orphan_deadline - now))
            for key, _events in selector.select(wait):
                stream = streams.get(key.data)
                if stream is None:
                    continue
                try:
                    chunk = os.read(stream.fileno(), _READ_CHUNK)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    selector.unregister(stream)
                    streams.pop(key.data, None)
                    continue
                if capture.feed(key.data, chunk) and not killed:
                    # stdout crossed the cap: stop the producer now and drain
                    # only long enough for the pipes to close.
                    killed = _kill_process_group(proc)
                    stop_at = min(stop_at, time.monotonic() + _KILL_GRACE)
                    child_exit_at = None
    finally:
        selector.close()
    return timed_out, killed


def _drain_threads(
    proc: subprocess.Popen,
    capture: _Capture,
    deadline: float,
) -> tuple[bool, bool]:
    """Portable drain: one reader thread per pipe.

    Used where ``selectors`` cannot watch pipes (Windows).  Same byte caps and
    the same kill decisions as :func:`_drain_selectors`; threads are daemons and
    are joined with a bound, so a wedged pipe cannot hold the caller open.
    """
    readers: list[threading.Thread] = []

    def pump(name: str, stream: Any) -> None:
        read = getattr(stream, "read1", stream.read)
        while True:
            try:
                chunk = read(_READ_CHUNK)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", "replace")
            capture.feed(name, chunk)

    for name in ("stdout", "stderr"):
        stream = getattr(proc, name, None)
        if stream is None:
            continue
        thread = threading.Thread(target=pump, args=(name, stream), daemon=True)
        thread.start()
        readers.append(thread)
    timed_out = False
    killed = False
    stop_at = deadline
    child_exit_at: float | None = None
    while any(thread.is_alive() for thread in readers):
        now = time.monotonic()
        if child_exit_at is None and proc.poll() is not None:
            child_exit_at = now
        if capture.overflow and not killed:
            killed = _kill_process_group(proc)
            stop_at = min(stop_at, now + _KILL_GRACE)
            child_exit_at = None
            continue
        orphan_deadline = None if child_exit_at is None else child_exit_at + _PIPE_HOLD_GRACE
        at_limit = now >= stop_at
        at_orphan = orphan_deadline is not None and now >= orphan_deadline
        if at_limit or at_orphan:
            if killed:
                break
            timed_out = at_limit and child_exit_at is None
            killed = _kill_process_group(proc)
            stop_at = now + _KILL_GRACE
            child_exit_at = None
            continue
        time.sleep(0.02)
    for thread in readers:
        thread.join(timeout=_KILL_GRACE)
    return timed_out, killed


def _drain(proc: subprocess.Popen, capture: _Capture, deadline: float) -> tuple[bool, bool]:
    if os.name == "posix":
        return _drain_selectors(proc, capture, deadline)
    return _drain_threads(proc, capture, deadline)


def _default_runner(
    argv: list[str], *, timeout: float, env: Mapping[str, str]
) -> BoundedCompletedProcess:
    """Run ``argv`` with the output cap enforced *during* capture.

    Bounded by construction, not after the fact:

    * Both pipes are drained here, and the keep-buffers stop at
      ``MAX_OUTPUT_BYTES`` (stdout) / ``MAX_STDERR_BYTES`` (stderr).  The rest of
      a flooding stream is read and discarded, never accumulated, so a looping
      upstream cannot make this process hold more than one cap of output.
    * On POSIX the child runs in its own session, so its pid is a process-group
      id.  A timeout, a stdout overflow, or a child that exited while a
      descendant still holds the pipes kills the whole group with
      ``SIGKILL`` — a spawned browser/downloader cannot outlive the call.
    * The wall-clock budget covers the whole drain.  On expiry the group is
      killed and :class:`subprocess.TimeoutExpired` is raised, so callers keep
      their existing timeout contract.  An overflow is *not* a timeout: the
      truncated prefix comes back with ``overflow=True`` and the caller reports
      ``oversized``.

    Windows limits (stated, not silently assumed): there is no process group to
    signal, so only the direct child is killed and a helper it spawned can
    outlive the call; the byte caps and the wall-clock budget still apply.
    ``selectors`` cannot watch pipes there, so the drain uses reader threads.
    """
    started = time.monotonic()
    kwargs: dict[str, Any] = {
        # Fixed argv, no shell, no inherited stdin: the same envelope as before.
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "env": dict(env),
        # Unbuffered pipes: the drain bounds bytes itself, and a buffered wrapper
        # would read past the cap before it could be enforced.
        "bufsize": 0,
    }
    if os.name == "posix":
        # Own session => own process group, killable as a unit.
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(list(argv), **kwargs)  # noqa: S603 - fixed argv, shell disabled
    capture = _Capture()
    deadline = started + max(float(timeout), 0.0)
    timed_out = False
    killed = False
    try:
        timed_out, killed = _drain(proc, capture, deadline)
        try:
            proc.wait(timeout=_KILL_GRACE)
        except subprocess.TimeoutExpired:
            # Pipes closed but the process outlived its budget: still a timeout.
            _kill_process_group(proc)
            killed = True
            timed_out = True
            with suppress(subprocess.TimeoutExpired, OSError):
                proc.wait(timeout=_KILL_GRACE)
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
    stdout = bytes(capture.out).decode("utf-8", "replace")
    stderr = bytes(capture.err).decode("utf-8", "replace")
    if timed_out:
        raise subprocess.TimeoutExpired(
            list(argv), timeout, output=stdout, stderr=stderr
        )
    completed = BoundedCompletedProcess(list(argv), proc.returncode, stdout, stderr)
    completed.overflow = capture.overflow
    completed.stderr_truncated = capture.stderr_truncated
    completed.killed = killed
    return completed


def _output_overflowed(completed: subprocess.CompletedProcess, stdout: str) -> bool:
    """Did capture hit the cap, or is the decoded text over the byte bound?

    The bounded runner stops the producer *at* ``MAX_OUTPUT_BYTES``, so the
    truncated prefix itself sits exactly at the cap and a length test alone
    would let it through to the JSON parser.  The length check stays for an
    injected runner that returns a plain ``CompletedProcess``.
    """
    if getattr(completed, "overflow", False):
        return True
    return len(stdout.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES


class AgentReachBackend:
    """Thin, safety-bounded forwarding layer over an existing Agent Reach CLI."""

    #: Extra wall-clock seconds on top of ``--timeout`` so upstream can emit
    #: its own JSON timeout envelope before we kill it.
    timeout_grace = 5.0

    def __init__(
        self,
        executable: str | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        allow_authenticated: bool = False,
        allow_quota_consuming: bool = False,
        runner: Runner | None = None,
        max_items: int = MAX_ITEMS,
    ) -> None:
        self._explicit = executable
        self._env_override = env
        self._timeout = _bounded_timeout(timeout)
        self._allow_authenticated = bool(allow_authenticated)
        self._allow_quota_consuming = bool(allow_quota_consuming)
        self._runner = runner or _default_runner
        self._max_items = _constructor_items(max_items)
        self._registry: ReachRegistry | None = None
        self._availability: ReachAvailability | None = None

    # -- discovery / registry ------------------------------------------------

    def availability(self) -> ReachAvailability:
        if self._availability is None:
            self._availability = discover_agent_reach(self._explicit, self._env_override)
        return self._availability

    def available(self) -> bool:
        return self.availability().found

    def registry(self, *, refresh: bool = False) -> ReachRegistry:
        if self._registry is not None and not refresh:
            return self._registry
        availability = self.availability()
        if not availability.found or not availability.path:
            raise ReachUnavailable(
                "agent-reach executable not found; set "
                f"{AGENT_REACH_ENV} or install it yourself (this backend never installs)"
            )
        argv = [availability.path, "channels"]
        try:
            if self._allow_authenticated:
                env = _child_env(self._env_override, availability.path, public=False)
                completed = self._runner(argv, timeout=self.timeout_grace + 30.0, env=env)
            else:
                with _isolated_home() as home:
                    env = _child_env(
                        self._env_override, availability.path, public=True, home=home
                    )
                    completed = self._runner(argv, timeout=self.timeout_grace + 30.0, env=env)
        except subprocess.TimeoutExpired as exc:
            raise RegistryError("agent-reach channels timed out") from exc
        except OSError as exc:
            raise ReachUnavailable(f"could not run agent-reach: {exc}") from exc
        stdout = completed.stdout or ""
        if not isinstance(stdout, str):
            stdout = stdout.decode("utf-8", "replace")
        if _output_overflowed(completed, stdout):
            raise RegistryError("agent-reach channels output is oversized")
        if completed.returncode not in (0, None):
            raise RegistryError(
                f"agent-reach channels exited {completed.returncode}: "
                f"{redact_secrets(completed.stderr or '', limit=300)}".strip()
            )
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise RegistryError(f"agent-reach channels returned malformed JSON: {exc}") from exc
        self._registry = parse_registry(payload)
        return self._registry

    # -- capability surface --------------------------------------------------

    def capabilities(self) -> list[dict[str, Any]]:
        """Discoverable channel/action pairs and how each one can be reached.

        Includes the two quota-gated transcription actions, marked
        ``quota_consuming`` and ``blocked_by_default``; the read-only allowlist
        never contains them.
        """
        registry = self.registry()
        out: list[dict[str, Any]] = []
        for channel_name, actions in DISCOVERABLE_ACTION_ALLOWLIST.items():
            channel = registry.channels.get(channel_name)
            if channel is None:
                continue
            for action in channel.actions.values():
                if action.name not in actions:
                    continue
                if self.is_quota_action(channel_name, action.name):
                    mode = self.quota_mode(channel, action)
                elif self.is_allowlisted(channel_name, action.name):
                    mode = self.reach_mode(channel, action)
                else:
                    continue
                entry = mode.to_dict()
                entry["help"] = action.help
                entry["backends"] = list(action.backends)
                entry["public_web"] = list(action.public_web)
                entry["gate"] = (
                    "quota" if mode.quota_consuming else ("public" if mode.public else "consent")
                )
                entry["blocked_by_default"] = bool(mode.quota_consuming or not mode.public)
                entry["asr_veto"] = bool(mode.quota_consuming and asr_disabled(self._env_override))
                out.append(entry)
        out.sort(key=lambda row: (row["channel"], row["action"]))
        return out

    def describe(self) -> dict[str, Any]:
        """Probe payload for CLI/doctor use — no network beyond ``channels``."""
        availability = self.availability()
        veto = asr_disabled(self._env_override)
        payload: dict[str, Any] = {
            "engine": ENGINE,
            "executable": availability.path,
            "found": availability.found,
            "reason": availability.reason,
            "schema_version": None,
            "public_only": not self._allow_authenticated,
            # Consent (the flags this run carries) is reported separately from
            # readiness (a quota call could actually run right now).
            "quota_consuming_allowed": self._allow_quota_consuming,
            "authenticated_allowed": self._allow_authenticated,
            "asr_disabled": veto,
            "asr_vetoed": veto,
            "quota_ready": bool(
                self._allow_quota_consuming and self._allow_authenticated and not veto
            ),
            "credential_source": "upstream-home-config",
            "capabilities": [],
            "parity": parity_inventory(),
            "error": None,
        }
        if not availability.found:
            payload["error"] = {
                "code": "not_configured",
                "message": "agent-reach is not installed or not discoverable",
            }
            return payload
        try:
            registry = self.registry()
            payload["schema_version"] = registry.schema_version
            payload["capabilities"] = self.capabilities()
        except ReachBackendError as exc:
            payload["error"] = {"code": "registry_invalid", "message": str(exc)}
        return payload

    # -- policy --------------------------------------------------------------

    @staticmethod
    def is_allowlisted(channel: str, action: str) -> bool:
        if action in FORBIDDEN_ACTIONS:
            return False
        return action in READ_ONLY_ACTION_ALLOWLIST.get(channel, frozenset())

    @staticmethod
    def is_quota_action(channel: str, action: str) -> bool:
        """Is this a paid/key-consuming action with its own consent gate?"""
        return action in QUOTA_ACTION_ALLOWLIST.get(channel, frozenset())

    @staticmethod
    def quota_mode(channel: ReachChannel, action: ReachAction) -> ReachMode:
        """Route for a double-gated quota action (never public)."""
        return ReachMode(
            channel.name,
            action.name,
            "quota",
            False,
            "paid/key-consuming transcription: needs allow_quota_consuming=True "
            "and allow_authenticated=True; TRAILHEAD_DISABLE_ASR=1 vetoes it",
            forced_backend=None,
            quota_consuming=True,
        )

    @staticmethod
    def reach_mode(channel: ReachChannel, action: ReachAction) -> ReachMode:
        """The public (no-consent) route for one channel/action pair.

        Selection is per action, never per channel: a declared session or
        browser login does not make an action authenticated if upstream also
        declares a public backend for it.
        """
        if action.public_web:
            return ReachMode(
                channel.name,
                action.name,
                "public_web",
                True,
                "public-web route declared by upstream; forced with --backend public-web",
                forced_backend="public-web",
            )
        preferred = PUBLIC_API_BACKENDS.get(channel.name, {}).get(action.name, ())
        for label in preferred:
            if label in action.backends:
                return ReachMode(
                    channel.name,
                    action.name,
                    "public_api",
                    True,
                    f"public backend {label!r} declared by upstream; forced with "
                    f"--backend {label}",
                    forced_backend=label,
                )
        if preferred:
            return ReachMode(
                channel.name,
                action.name,
                "authenticated",
                False,
                f"upstream no longer declares a public backend for {channel.name} "
                f"{action.name}; requires allow_authenticated=True",
            )
        if not channel.requires_login:
            return ReachMode(
                channel.name,
                action.name,
                "public_api",
                True,
                "no login declared by upstream; runs on its declared public backends",
            )
        return ReachMode(
            channel.name,
            action.name,
            "authenticated",
            False,
            f"{channel.name} only exposes this action behind a {channel.login_via} login; "
            "requires allow_authenticated=True",
        )

    # -- execution -----------------------------------------------------------

    def execute(
        self,
        channel: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        allow_authenticated: bool | None = None,
        allow_quota_consuming: bool | None = None,
        max_items: int | None = None,
    ) -> ReachResult:
        """Run one discoverable action and return attributed results.

        Read-only actions follow the allowlist and per-action route policy.
        Quota actions additionally require ``allow_quota_consuming`` and
        ``allow_authenticated``; ``TRAILHEAD_DISABLE_ASR=1`` vetoes them first.
        Never raises for user input or upstream failures — the result carries a
        machine-readable ``error.code`` instead.
        """
        consent = self._allow_authenticated if allow_authenticated is None else bool(allow_authenticated)
        quota_consent = (
            self._allow_quota_consuming
            if allow_quota_consuming is None
            else bool(allow_quota_consuming)
        )
        limitations: list[str] = [LIMITATION_FORWARDED, LIMITATION_NOT_INSTALLED]
        provenance: dict[str, Any] = {
            "engine": ENGINE,
            "native": False,
            "attribution": "Agent Reach (third-party CLI), forwarded by Hermes Trailhead",
            "executable": None,
            "schema_version": None,
            "route": None,
            "public_only": not consent,
            "quota_consuming": False,
            "requested": f"{channel} {action}",
            "reported_backend": None,
            "forced_backend": None,
        }

        try:
            effective_timeout = _bounded_timeout(self._timeout if timeout is None else timeout)
            limit = _bounded_items(max_items, self._max_items)
            self._check_names(channel, action)
            quota_action = self.is_quota_action(channel, action)
            if quota_action:
                provenance["quota_consuming"] = True
                # The veto is checked before availability/registry, so nothing is
                # spawned and no environment is constructed.
                if asr_disabled(self._env_override):
                    raise InvalidRequest(
                        "asr_disabled",
                        f"transcription is disabled for this process ({ASR_DISABLE_ENV}=1); "
                        "this veto applies even with explicit consent flags",
                    )
                if not quota_consent:
                    raise InvalidRequest(
                        "quota_required",
                        f"{channel} {action} may bill a Whisper/Groq/OpenAI endpoint; "
                        "pass allow_quota_consuming=True (CLI --allow-quota-consuming) "
                        "to consent explicitly",
                    )
                if not consent:
                    raise InvalidRequest(
                        "auth_required",
                        f"{channel} {action} uses the operator's configured ASR key; "
                        "allow_quota_consuming=True is not enough — pass "
                        "allow_authenticated=True (CLI --allow-authenticated) as well",
                    )
            availability = self.availability()
            if not availability.found or not availability.path:
                raise InvalidRequest(
                    "not_configured",
                    "agent-reach executable not found; set "
                    f"{AGENT_REACH_ENV} or install it yourself",
                )
            provenance["executable"] = availability.path
            registry = self.registry()
            provenance["schema_version"] = registry.schema_version
            upstream_channel = registry.channels.get(channel)
            if upstream_channel is None:
                raise InvalidRequest("unknown_channel", f"unknown channel: {channel!r}")
            if action not in upstream_channel.actions:
                raise InvalidRequest(
                    "unknown_action",
                    f"unknown action for {channel}: {action!r}",
                )
            if quota_action:
                if action not in QUOTA_ACTION_ALLOWLIST.get(channel, frozenset()):
                    raise InvalidRequest(
                        "action_not_allowlisted",
                        f"{channel} {action} is not a gated transcription action Trailhead forwards",
                    )
            elif not self.is_allowlisted(channel, action):
                raise InvalidRequest(
                    "action_not_allowlisted",
                    f"{channel} {action} is not a read-only action Trailhead forwards",
                )
            upstream_action = upstream_channel.actions[action]
            mode = (
                self.quota_mode(upstream_channel, upstream_action)
                if quota_action
                else self.reach_mode(upstream_channel, upstream_action)
            )
            provenance["route"] = mode.mode

            if not mode.public and not consent:
                raise InvalidRequest(
                    "auth_required",
                    f"{channel} {action} requires an existing {upstream_channel.login_via} "
                    "login upstream; pass allow_authenticated=True to consent, or use a "
                    "public route",
                )

            positionals, options = _coerce_params(upstream_action, params)
            backend: str | None = None
            if consent:
                if upstream_channel.requires_login or quota_action:
                    limitations.append(LIMITATION_AUTHENTICATED)
                if quota_action:
                    limitations.append(LIMITATION_QUOTA)
            else:
                backend = mode.forced_backend
                limitations.append(LIMITATION_PUBLIC)
                limitations.append(LIMITATION_PUBLIC_HOME)
                if backend == "public-web":
                    limitations.append(LIMITATION_PUBLIC_WEB)
            provenance["forced_backend"] = backend
            provenance["home_mode"] = "operator" if consent else "isolated-temp"

            argv = build_argv(
                availability.path,
                channel,
                action,
                positionals=positionals,
                options=options,
                backend=backend,
                timeout=effective_timeout,
            )
            started = time.monotonic()
            try:
                with self._process_env(availability.path, public=not consent) as env:
                    completed = self._runner(
                        argv,
                        timeout=effective_timeout + self.timeout_grace,
                        env=env,
                    )
            except subprocess.TimeoutExpired:
                elapsed = int((time.monotonic() - started) * 1000)
                return self._fail(
                    channel,
                    action,
                    "timeout",
                    f"agent-reach {channel} {action} exceeded {effective_timeout:g}s",
                    provenance=provenance,
                    limitations=limitations,
                    elapsed_ms=elapsed,
                    argv=argv,
                    timed_out=True,
                )
            except OSError as exc:
                elapsed = int((time.monotonic() - started) * 1000)
                return self._fail(
                    channel,
                    action,
                    "process_error",
                    f"could not run agent-reach: {exc}",
                    provenance=provenance,
                    limitations=limitations,
                    elapsed_ms=elapsed,
                    argv=argv,
                )
            elapsed = int((time.monotonic() - started) * 1000)
            return self._interpret(
                completed,
                channel=channel,
                action=action,
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed,
                argv=argv,
                limit=limit,
                forced_backend=backend,
            )
        except InvalidRequest as exc:
            return self._fail(
                channel,
                action,
                exc.code,
                exc.message,
                provenance=provenance,
                limitations=limitations,
            )
        except ReachUnavailable as exc:
            return self._fail(
                channel,
                action,
                "not_configured",
                str(exc),
                provenance=provenance,
                limitations=limitations,
            )
        except RegistryError as exc:
            return self._fail(
                channel,
                action,
                "registry_invalid",
                str(exc),
                provenance=provenance,
                limitations=limitations,
            )

    # -- internals -----------------------------------------------------------

    @contextmanager
    def _process_env(self, executable: str, *, public: bool) -> Iterator[dict[str, str]]:
        """Child environment, with a throwaway HOME in public mode."""
        if not public:
            yield _child_env(self._env_override, executable, public=False)
            return
        with _isolated_home() as home:
            yield _child_env(self._env_override, executable, public=True, home=home)

    @staticmethod
    def _check_names(channel: Any, action: Any) -> None:
        if not isinstance(channel, str) or not CHANNEL_NAME_RE.match(channel):
            raise InvalidRequest("unknown_channel", f"invalid channel name: {channel!r}")
        if channel in FORBIDDEN_COMMANDS:
            raise InvalidRequest(
                "forbidden_command",
                f"{channel!r} is an Agent Reach management command, not a read-only channel",
            )
        if not isinstance(action, str) or not ACTION_NAME_RE.match(action):
            raise InvalidRequest("unknown_action", f"invalid action name: {action!r}")
        if action in EXCLUDED_ACTIONS:
            raise InvalidRequest(
                "action_not_allowlisted",
                f"{action!r} is excluded: {EXCLUDED_ACTIONS[action]}",
            )
        if action in FORBIDDEN_ACTIONS:
            raise InvalidRequest(
                "forbidden_command",
                f"{action!r} is not a read-only action",
            )

    def _interpret(
        self,
        completed: subprocess.CompletedProcess,
        *,
        channel: str,
        action: str,
        provenance: dict[str, Any],
        limitations: list[str],
        elapsed_ms: int,
        argv: list[str],
        limit: int,
        forced_backend: str | None = None,
    ) -> ReachResult:
        stdout = completed.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        stderr = completed.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        code = completed.returncode
        if not stdout.strip():
            return self._fail(
                channel,
                action,
                "malformed_output",
                f"agent-reach produced no JSON (exit {code}): "
                f"{redact_secrets(stderr, limit=300)}".strip(),
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        if _output_overflowed(completed, stdout):
            return self._fail(
                channel,
                action,
                "malformed_output",
                "agent-reach output is oversized",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            return self._fail(
                channel,
                action,
                "malformed_output",
                f"agent-reach returned malformed JSON: {exc}",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        if not isinstance(payload, dict):
            return self._fail(
                channel,
                action,
                "malformed_output",
                "agent-reach JSON payload is not an object",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        echoed_channel = payload.get("channel")
        echoed_action = payload.get("action")
        if echoed_channel is not None and echoed_channel != channel:
            return self._fail(
                channel,
                action,
                "malformed_output",
                f"upstream reported channel {echoed_channel!r} for request {channel!r}",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        if echoed_action is not None and echoed_action != action:
            return self._fail(
                channel,
                action,
                "malformed_output",
                f"upstream reported action {echoed_action!r} for request {action!r}",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        ok = payload.get("ok")
        if not isinstance(ok, bool):
            return self._fail(
                channel,
                action,
                "malformed_output",
                "agent-reach JSON payload has no boolean 'ok'",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )

        reported_backend = payload.get("backend")
        if isinstance(reported_backend, str) and reported_backend:
            # Echoed in provenance, results and error text: clip and redact it
            # like any other untrusted field instead of forwarding a 100 KB
            # label verbatim.
            provenance["reported_backend"] = redact_secrets(
                reported_backend, limit=MAX_BACKEND_CHARS
            )
        attempts = _clean_attempts(payload.get("meta"))
        upstream_elapsed = _clean_elapsed(payload.get("meta"))

        if not ok:
            error = payload.get("error")
            code_text, message, hint = _normalize_upstream_error(error)
            return ReachResult(
                ok=False,
                channel=channel,
                action=action,
                backend=provenance.get("reported_backend"),
                items=(),
                error={"code": "upstream_error", "upstream_code": code_text, "message": message, "hint": hint},
                provenance=provenance,
                limitations=tuple(limitations),
                elapsed_ms=upstream_elapsed if upstream_elapsed is not None else elapsed_ms,
                attempts=attempts,
                exit_code=code,
                argv=tuple(argv),
            )

        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return self._fail(
                channel,
                action,
                "malformed_output",
                "agent-reach JSON payload has no item list",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        if forced_backend is not None and not _backend_matches(
            provenance.get("reported_backend"), forced_backend
        ):
            # The payload claims a different route than the one we pinned.
            # Never hand untrusted content back as a successful public result.
            return self._fail(
                channel,
                action,
                "route_violation",
                f"upstream reported backend "
                f"{provenance.get('reported_backend')!r} for a call forced to "
                f"{forced_backend!r}; the payload was not forwarded",
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        body_read = action in BODY_READ_ACTIONS
        items, dropped_raw, rejected_urls, withheld, clipped = _normalize_items(
            raw_items, limit, body_read=body_read
        )
        if len(raw_items) > len(items) + len(withheld):
            limitations.append(
                f"Upstream returned {len(raw_items)} items; Trailhead kept the first {len(items)}."
            )
        if dropped_raw:
            limitations.append("Some upstream raw payloads were dropped to keep output bounded.")
        if clipped:
            limitations.append(
                f"{clipped} item field(s) were truncated at Trailhead's output bound."
            )
        if rejected_urls:
            limitations.append(f"{rejected_urls} item URL(s) were withheld because they were not http(s).")
        if withheld:
            blocked = sum(1 for reason in withheld if reason == "blocked")
            missing = sum(1 for reason in withheld if reason == "missing_page")
            empty = sum(1 for reason in withheld if reason == "empty_body")
            limitations.append(
                f"{len(withheld)} item(s) were withheld: the fetched body was only a "
                f"blocked or missing-page shell (blocked={blocked}, missing_page={missing}) "
                f"or carried no body text at all (empty_body={empty}), not readable "
                "content."
            )
        if body_read and not items and withheld:
            # Upstream said ok:true but forwarded no artifact — only shells or
            # empty rows.  Reporting that as a successful read is the false
            # success this guard exists to prevent; the attribution and attempts
            # survive.
            reasons = sorted(set(withheld))
            return ReachResult(
                ok=False,
                channel=channel,
                action=action,
                backend=provenance.get("reported_backend"),
                items=(),
                error={
                    "code": "content_unusable",
                    "message": redact_secrets(
                        f"agent-reach {channel} {action} returned no readable content: "
                        f"{len(withheld)} item(s) were blocked or missing-page shells, or "
                        "carried no body text, not the requested page"
                    ),
                    "withheld_items": len(withheld),
                    "reasons": reasons,
                },
                provenance=provenance,
                limitations=tuple(limitations),
                elapsed_ms=upstream_elapsed if upstream_elapsed is not None else elapsed_ms,
                attempts=attempts,
                exit_code=code,
                argv=tuple(argv),
            )
        return ReachResult(
            ok=True,
            channel=channel,
            action=action,
            backend=provenance.get("reported_backend"),
            items=tuple(items),
            error=None,
            provenance=provenance,
            limitations=tuple(limitations),
            elapsed_ms=upstream_elapsed if upstream_elapsed is not None else elapsed_ms,
            attempts=attempts,
            exit_code=code,
            argv=tuple(argv),
        )

    def _fail(
        self,
        channel: str | None,
        action: str | None,
        code: str,
        message: str,
        *,
        provenance: dict[str, Any],
        limitations: Iterable[str],
        elapsed_ms: int | None = None,
        argv: Sequence[str] = (),
        exit_code: int | None = None,
        timed_out: bool = False,
    ) -> ReachResult:
        return ReachResult(
            ok=False,
            channel=channel,
            action=action,
            backend=provenance.get("reported_backend"),
            items=(),
            # Every failure message can carry upstream text (stderr, an echoed
            # backend label, an OSError).  Redact at this single choke point;
            # the success path does not go through here.
            error={"code": code, "message": redact_secrets(message)},
            provenance=provenance,
            limitations=tuple(limitations),
            elapsed_ms=elapsed_ms,
            attempts=(),
            exit_code=exit_code,
            timed_out=timed_out,
            argv=tuple(argv),
        )


# ── payload normalisation ─────────────────────────────────────────────────


def _clean_elapsed(meta: Any) -> int | None:
    if not isinstance(meta, dict):
        return None
    value = meta.get("elapsed_ms")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 3_600_000:
        return None
    return int(value)


def _clean_attempts(meta: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(meta, dict):
        return ()
    raw = meta.get("attempts")
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    for entry in raw[:16]:
        if not isinstance(entry, dict):
            continue
        backend = entry.get("backend")
        result = entry.get("result")
        message = entry.get("message")
        out.append(
            {
                "backend": redact_secrets(backend, limit=128) if isinstance(backend, str) else None,
                "result": redact_secrets(result, limit=128) if isinstance(result, str) else None,
                "message": redact_secrets(message, limit=300) if isinstance(message, str) else None,
            }
        )
    return tuple(out)


def _normalize_upstream_error(error: Any) -> tuple[str, str, str]:
    if not isinstance(error, dict):
        return "UNKNOWN", "upstream reported an error without details", ""
    code = error.get("code")
    message = error.get("message")
    hint = error.get("hint")
    return (
        redact_secrets(code, limit=64) if isinstance(code, str) and code else "UNKNOWN",
        redact_secrets(message, limit=600)
        if isinstance(message, str) and message
        else "upstream error",
        redact_secrets(hint, limit=400) if isinstance(hint, str) else "",
    )


def _backend_matches(reported: Any, forced: str) -> bool:
    """Is the payload's reported backend the route we pinned?

    ``--backend public-web`` is answered with ``public-web`` (per-attempt rows
    carry ``public-web/<tool>``), so the prefix is accepted only for that pin.
    """
    if not isinstance(reported, str) or not reported:
        return False
    if forced == "public-web":
        return reported == "public-web" or reported.startswith("public-web/")
    return reported == forced


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    return value[:MAX_URL_CHARS]


def _clip(value: Any, limit: int) -> tuple[str | None, bool]:
    """One untrusted text field, clipped; ``(value, was_clipped)``."""
    if not isinstance(value, str):
        return None, False
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _normalize_items(
    raw_items: Sequence[Any],
    limit: int,
    *,
    body_read: bool = False,
) -> tuple[list[dict[str, Any]], bool, int, list[str], int]:
    """Normalise upstream items, withholding blocked/missing page shells.

    ``body_read`` marks actions whose text is supposed to be the fetched page
    body.  For those, an item whose text is only a block/missing-page shell is
    withheld (reason ``blocked`` / ``missing_page``), and so is an item with no
    body text at all (reason ``empty_body``): a ``read`` that returns a row with
    an empty body and nothing else has not delivered the artifact the caller
    asked for, and forwarding it as a successful read is a false success.
    ``raw`` is a structured side payload, not a page body, so its presence does
    not make an empty read usable.  Items with no text on metadata-only actions
    (``v2ex user``, ``bilibili hot``, ``xueqiu search``, ...) are never
    classified: empty text is legitimate there, and they carry their value in
    ``raw``.  Search/discovery actions are likewise untouched — a snippet is a
    lead, not a complete-artifact claim.

    Every forwarded string is clipped to a documented bound; the final element
    of the tuple counts how many fields were clipped so the caller can say so
    instead of silently shortening evidence.
    """
    items: list[dict[str, Any]] = []
    dropped_raw = False
    rejected_urls = 0
    withheld: list[str] = []
    clipped = 0
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        raw_url = entry.get("url")
        url = _safe_url(raw_url)
        if raw_url and url is None:
            rejected_urls += 1
        text = entry.get("text")
        text_out = text[:MAX_TEXT_CHARS] if isinstance(text, str) else ""
        if body_read:
            if not text_out.strip():
                withheld.append("empty_body")
                continue
            reason = classify_page_shell(text_out)
            if reason is not None:
                withheld.append(reason)
                continue
        if len(items) >= limit:
            break
        # Clip only what is actually forwarded, so the limitation line counts
        # fields the caller can see.
        title, title_cut = _clip(entry.get("title"), MAX_VALUE_CHARS)
        author, author_cut = _clip(entry.get("author"), MAX_VALUE_CHARS)
        published, published_cut = _clip(entry.get("published_at"), MAX_VALUE_CHARS)
        clipped += sum((title_cut, author_cut, published_cut))
        if isinstance(raw_url, str) and len(raw_url) > MAX_URL_CHARS:
            clipped += 1
        raw = entry.get("raw")
        raw_kept: Any = None
        if isinstance(raw, dict):
            try:
                encoded = json.dumps(raw, ensure_ascii=False)
            except (TypeError, ValueError):
                encoded = ""
            if encoded and len(encoded) <= 2000:
                raw_kept = raw
            else:
                dropped_raw = True
        items.append(
            {
                "title": title,
                "url": url,
                "url_rejected": bool(raw_url and url is None),
                "author": author,
                "published_at": published,
                "text": text_out,
                "text_truncated": isinstance(text, str) and len(text) > MAX_TEXT_CHARS,
                "raw": raw_kept,
            }
        )
    return items, dropped_raw, rejected_urls, withheld, clipped


__all__ = [
    "AGENT_REACH_ENV",
    "AGENT_REACH_HOME_ENV",
    "ASR_DISABLE_ENV",
    "BODY_READ_ACTIONS",
    "AgentReachBackend",
    "COVERAGE_STATES",
    "DEFAULT_TIMEOUT",
    "DISCOVERABLE_ACTION_ALLOWLIST",
    "EXCLUDED_ACTIONS",
    "FORBIDDEN_ACTIONS",
    "FORBIDDEN_COMMANDS",
    "GATE_STATES",
    "LIMITATION_QUOTA",
    "MAX_LIMIT",
    "MAX_TIMEOUT",
    "MIN_TIMEOUT",
    "PARITY_ACTIONS",
    "PINNED_UPSTREAM",
    "PUBLIC_API_BACKENDS",
    "QUOTA_ACTION_ALLOWLIST",
    "READ_ONLY_ACTION_ALLOWLIST",
    "ParityAction",
    "ReachAction",
    "ReachAvailability",
    "ReachBackendError",
    "ReachChannel",
    "ReachMode",
    "ReachParam",
    "ReachRegistry",
    "ReachResult",
    "ReachUnavailable",
    "RegistryError",
    "InvalidRequest",
    "asr_disabled",
    "build_argv",
    "discover_agent_reach",
    "parity_inventory",
    "parse_registry",
    "redact_secrets",
    "validate_parity_inventory",
]
