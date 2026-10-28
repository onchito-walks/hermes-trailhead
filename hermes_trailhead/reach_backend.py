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
  before a process is spawned, and so are paid/key-consuming transcription
  actions.
* **No shell, argument arrays only.**  ``subprocess`` is invoked with a list
  and ``shell=False``.  Positional targets are separated with ``--`` and a
  leading ``-`` is rejected outright, so a target can never become an option.
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
* **Attribution stays intact.**  Every result carries provenance naming Agent
  Reach as the producing engine and lists the forwarding limitations.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlparse


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
MAX_ITEMS = 50
MAX_REGISTRY_CHANNELS = 64
MAX_REGISTRY_ACTIONS = 64
MAX_OUTPUT_BYTES = 4_000_000

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
        "transcribe",
    }
)

#: Paid / key-consuming actions excluded even though they are read-only.
#: ``transcribe`` bills a Whisper endpoint (groq-whisper / whisper).
EXCLUDED_ACTIONS: dict[str, str] = {
    "transcribe": "paid/key-consuming transcription is never run automatically",
}

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
    # xiaoyuzhou exposes only `transcribe` — intentionally absent.
}

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
    "The upstream process ran with a private empty HOME; operator config, "
    "login state, and stored credentials were not visible to it."
)
LIMITATION_PUBLIC_WEB = (
    "Upstream ran with --backend public-web, which forbids browser fallback."
)
LIMITATION_AUTHENTICATED = (
    "Ran with allow_authenticated=True against the operator's existing Agent "
    "Reach login state; Trailhead did not create, copy, or refresh it."
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
    mode: str  # "public_web" | "public_api" | "authenticated"
    public: bool
    reason: str
    forced_backend: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "action": self.action,
            "mode": self.mode,
            "public": self.public,
            "reason": self.reason,
            "forced_backend": self.forced_backend,
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

    In both modes only the allowlisted variables are forwarded: no API keys,
    tokens, cookies, or browser paths.
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
    except (TypeError, ValueError) as exc:
        raise InvalidRequest("invalid_params", "max_items must be an integer") from exc
    if value < 1:
        raise InvalidRequest("invalid_params", "max_items must be positive")
    return min(value, MAX_ITEMS)


Runner = Callable[..., subprocess.CompletedProcess]


def _default_runner(argv: list[str], *, timeout: float, env: Mapping[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, shell disabled
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        shell=False,
        check=False,
    )


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
        runner: Runner | None = None,
        max_items: int = MAX_ITEMS,
    ) -> None:
        self._explicit = executable
        self._env_override = env
        self._timeout = _bounded_timeout(timeout)
        self._allow_authenticated = bool(allow_authenticated)
        self._runner = runner or _default_runner
        self._max_items = max(1, min(int(max_items), MAX_ITEMS))
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
        if len(stdout.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
            raise RegistryError("agent-reach channels output is oversized")
        if completed.returncode not in (0, None):
            raise RegistryError(
                f"agent-reach channels exited {completed.returncode}: "
                f"{(completed.stderr or '')[:300]}".strip()
            )
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise RegistryError(f"agent-reach channels returned malformed JSON: {exc}") from exc
        self._registry = parse_registry(payload)
        return self._registry

    # -- capability surface --------------------------------------------------

    def capabilities(self) -> list[dict[str, Any]]:
        """Allowlisted channel/action pairs and how they can be reached."""
        registry = self.registry()
        out: list[dict[str, Any]] = []
        for channel_name in READ_ONLY_ACTION_ALLOWLIST:
            channel = registry.channels.get(channel_name)
            if channel is None:
                continue
            for action in channel.actions.values():
                if not self.is_allowlisted(channel_name, action.name):
                    continue
                mode = self.reach_mode(channel, action)
                entry = mode.to_dict()
                entry["help"] = action.help
                entry["backends"] = list(action.backends)
                entry["public_web"] = list(action.public_web)
                out.append(entry)
        out.sort(key=lambda row: (row["channel"], row["action"]))
        return out

    def describe(self) -> dict[str, Any]:
        """Probe payload for CLI/doctor use — no network beyond ``channels``."""
        availability = self.availability()
        payload: dict[str, Any] = {
            "engine": ENGINE,
            "executable": availability.path,
            "found": availability.found,
            "reason": availability.reason,
            "schema_version": None,
            "public_only": not self._allow_authenticated,
            "capabilities": [],
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
        max_items: int | None = None,
    ) -> ReachResult:
        """Run one allowlisted read-only action and return attributed results.

        Never raises for user input or upstream failures; the result carries a
        machine-readable ``error.code`` instead.
        """
        consent = self._allow_authenticated if allow_authenticated is None else bool(allow_authenticated)
        limitations: list[str] = [LIMITATION_FORWARDED, LIMITATION_NOT_INSTALLED]
        provenance: dict[str, Any] = {
            "engine": ENGINE,
            "native": False,
            "attribution": "Agent Reach (third-party CLI), forwarded by Hermes Trailhead",
            "executable": None,
            "schema_version": None,
            "route": None,
            "public_only": not consent,
            "requested": f"{channel} {action}",
            "reported_backend": None,
            "forced_backend": None,
        }

        try:
            effective_timeout = _bounded_timeout(self._timeout if timeout is None else timeout)
            limit = _bounded_items(max_items, self._max_items)
            self._check_names(channel, action)
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
            if not self.is_allowlisted(channel, action):
                raise InvalidRequest(
                    "action_not_allowlisted",
                    f"{channel} {action} is not a read-only action Trailhead forwards",
                )
            upstream_action = upstream_channel.actions[action]
            mode = self.reach_mode(upstream_channel, upstream_action)
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
                if upstream_channel.requires_login:
                    limitations.append(LIMITATION_AUTHENTICATED)
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
                f"agent-reach produced no JSON (exit {code}): {stderr[:300]}".strip(),
                provenance=provenance,
                limitations=limitations,
                elapsed_ms=elapsed_ms,
                argv=argv,
                exit_code=code,
            )
        if len(stdout.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
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
            provenance["reported_backend"] = reported_backend
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
        items, dropped_raw, rejected_urls = _normalize_items(raw_items, limit)
        if len(raw_items) > len(items):
            limitations.append(
                f"Upstream returned {len(raw_items)} items; Trailhead kept the first {len(items)}."
            )
        if dropped_raw:
            limitations.append("Some upstream raw payloads were dropped to keep output bounded.")
        if rejected_urls:
            limitations.append(f"{rejected_urls} item URL(s) were withheld because they were not http(s).")
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
            error={"code": code, "message": message},
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
                "backend": backend if isinstance(backend, str) else None,
                "result": result if isinstance(result, str) else None,
                "message": message[:300] if isinstance(message, str) else None,
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
        code[:64] if isinstance(code, str) and code else "UNKNOWN",
        message[:600] if isinstance(message, str) and message else "upstream error",
        hint[:400] if isinstance(hint, str) else "",
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
    return value


def _normalize_items(
    raw_items: Sequence[Any],
    limit: int,
) -> tuple[list[dict[str, Any]], bool, int]:
    items: list[dict[str, Any]] = []
    dropped_raw = False
    rejected_urls = 0
    for entry in raw_items:
        if len(items) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        raw_url = entry.get("url")
        url = _safe_url(raw_url)
        if raw_url and url is None:
            rejected_urls += 1
        title = entry.get("title")
        author = entry.get("author")
        published = entry.get("published_at")
        text = entry.get("text")
        text_out = text[:MAX_TEXT_CHARS] if isinstance(text, str) else ""
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
                "title": title if isinstance(title, str) else None,
                "url": url,
                "url_rejected": bool(raw_url and url is None),
                "author": author if isinstance(author, str) else None,
                "published_at": published if isinstance(published, str) else None,
                "text": text_out,
                "text_truncated": isinstance(text, str) and len(text) > MAX_TEXT_CHARS,
                "raw": raw_kept,
            }
        )
    return items, dropped_raw, rejected_urls


__all__ = [
    "AGENT_REACH_ENV",
    "AGENT_REACH_HOME_ENV",
    "AgentReachBackend",
    "DEFAULT_TIMEOUT",
    "EXCLUDED_ACTIONS",
    "FORBIDDEN_ACTIONS",
    "FORBIDDEN_COMMANDS",
    "MAX_LIMIT",
    "MAX_TIMEOUT",
    "MIN_TIMEOUT",
    "PUBLIC_API_BACKENDS",
    "READ_ONLY_ACTION_ALLOWLIST",
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
    "build_argv",
    "discover_agent_reach",
    "parse_registry",
]
