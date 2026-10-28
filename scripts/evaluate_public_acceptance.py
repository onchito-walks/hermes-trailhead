#!/usr/bin/env python3
"""Bounded, repeatable public acceptance evidence for Trailhead vs Agent Reach.

What this script is
-------------------
A *harness*, not a comparator. It does not score, rank, or grade. It:

1. Freezes a small multilingual outcome manifest (English + Chinese) with the
   artifacts a caller actually asked for (README install instructions, class
   entries, topic list entries), not a character budget.
2. Runs the existing ``hermes_trailhead compare`` CLI -- the matched-outcome
   benchmark that already exists -- repeatedly, cold and warm, over the same
   three public cases, under ``/usr/bin/time -v`` so wall clock and peak RSS
   are measured by an external process, not self-reported.
3. Checks artifact presence by reading the *actual* returned text from each
   tool's own public read path: ``extract.extract_one`` and the shipped
   ``hermes_trailhead read`` CLI for Trailhead, and the case's declared Agent
   Reach argv for the other side. No phrase-count win, no length threshold: an
   artifact is present or it is not -- and presence is not proof that the page
   or README was returned whole. Each match records its offset, a short context
   and (where output has a ``README:`` section) whether it came from README
   prose or repository metadata.
4. Inventories dependency surface (installed distributions, on-disk venv size)
   where it is measurable without reinstalling anything.
5. Writes a sanitized machine-readable JSON record. Raw stdout/stderr/time
   files stay in the scratch directory named on the command line.

What this script is NOT
-----------------------
- Not a new comparator, scoring model, or benchmark framework.
- Not a performance claim: one host, one network moment, three cases.
- Not an authenticated, paid, or ASR run. No credentials are used or accepted;
  the Agent Reach side is invoked with the environment-isolated tree that
  ``comparative.build_sandbox`` builds (environment isolation only -- not a
  filesystem sandbox).

Usage
-----
    python3 scripts/evaluate_public_acceptance.py \
        --agent-reach /path/to/agent-reach \
        --scratch /path/to/scratch/public-acceptance \
        --out docs/evidence/public-acceptance.json \
        --repeats 3
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA = "trailhead.public-acceptance/1"

# ── frozen manifest ──────────────────────────────────────────────────────────
# One entry per representative public case. ``compare_case`` is the id in
# hermes_trailhead.comparative.CASES: argv for both sides is read from that
# module, never retyped here. ``artifacts`` are the requested outcomes.
MANIFEST: dict = {
    "manifest_version": 1,
    "frozen_on": "2026-10-28",
    "languages": ["en", "zh-Hans"],
    "cases": [
        {
            "case_id": "public-docs-python-typing",
            "compare_case": "docs-python-typing",
            "language": "en",
            "family": "docs",
            "requested_outcome": (
                "complete 'typing' module reference: page identity plus the "
                "Protocol / TypeVar / Generic entries an API consumer needs"
            ),
            "artifacts": [
                {"label": "page_identity", "kind": "any_of", "values": ["Support for type hints"]},
                {"label": "entry_Protocol", "kind": "any_of", "values": ["Protocol"]},
                {"label": "entry_TypeVar", "kind": "any_of", "values": ["TypeVar"]},
                {"label": "entry_Generic", "kind": "any_of", "values": ["Generic"]},
                {"label": "special_form_TypeAlias", "kind": "any_of", "values": ["TypeAlias"]},
            ],
        },
        {
            "case_id": "public-github-requests-readme",
            "compare_case": "github-requests-readme",
            "language": "en",
            "family": "github",
            "requested_outcome": (
                "psf/requests repository README: identity, install command, a "
                "usage call, and the license the README states"
            ),
            "artifacts": [
                {"label": "repo_identity", "kind": "any_of", "values": ["psf/requests"]},
                {"label": "readme_install", "kind": "any_of", "values": ["pip install requests"]},
                {"label": "readme_usage", "kind": "any_of", "values": ["requests.get(", "requests.get("]},
                {"label": "readme_intro", "kind": "any_of", "values": ["A simple, yet elegant, HTTP library"]},
                {"label": "readme_license", "kind": "any_of", "values": ["Apache"]},
            ],
        },
        {
            "case_id": "public-v2ex-node-python-zh",
            "compare_case": "forum-v2ex-node",
            "language": "zh-Hans",
            "family": "v2ex",
            "requested_outcome": (
                "V2EX Python node listing (Chinese): node identity plus the "
                "titles/links of listed topics"
            ),
            "artifacts": [
                {"label": "node_identity", "kind": "any_of", "values": ["Python"]},
                {"label": "chinese_topic_prose", "kind": "regex_distinct", "pattern": "[\\u4e00-\\u9fff]{8,}", "min_distinct": 3},
                {"label": "topic_urls", "kind": "regex_distinct", "pattern": "v2ex\\.com/t/\\d+", "min_distinct": 3},
            ],
        },
    ],
}

#: Artifact labels that a public node/listing artifact genuinely must carry.
#: Listed separately so the report can name the gap rather than hide it.
INFORMATIONAL_COUNTS = ("topic_urls", "topic_titles")


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scratch(name: str) -> Path:
    path = SCRATCH / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


TIME_BIN = "/usr/bin/time"


def run_measured(argv: list[str], *, env: dict | None = None, timeout: float = 300) -> dict:
    """Run ``argv`` under /usr/bin/time -v; return wall seconds and peak RSS.

    GNU time reports the direct child's rusage. Subprocesses the CLI spawns are
    included only as far as the kernel accounts them to the child -- recorded
    as a limitation, not as a precise total.
    """
    time_file = _scratch(f"time-{int(time.time()*1000)}-{os.getpid()}.txt")
    cmd = [TIME_BIN, "-v", "-o", str(time_file), *argv]
    started = time.monotonic()
    try:
        stderr = ""
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(REPO)
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        completed = None
        timed_out = True
        stdout = (exc.stdout or b"")
        stderr = (exc.stderr or b"")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    wall = round(time.monotonic() - started, 3)
    raw = time_file.read_text(errors="replace") if time_file.exists() else ""
    peak_kb = None
    match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", raw)
    if match:
        peak_kb = int(match.group(1))
    return {
        "wall_s": wall,
        "peak_rss_kb": peak_kb,
        "timed_out": timed_out,
        "stdout": "" if completed is None else completed.stdout,
        "stderr": (stderr if completed is None else completed.stderr),
        "exit_code": None if completed is None else completed.returncode,
        "time_raw_path": str(time_file),
    }


def compare_argv(case_ids: list[str], agent_reach: str, sandbox: str | None,
                 timeout_s: float) -> list[str]:
    argv = [sys.executable, "-m", "hermes_trailhead", "compare"]
    for cid in case_ids:
        argv += ["--case", cid]
    argv += ["--agent-reach", agent_reach, "--timeout", f"{timeout_s:g}",
             "--limit", "3", "--format", "json"]
    if sandbox:
        argv += ["--sandbox", sandbox]
    return argv


def case_outcomes(report: dict) -> dict:
    """Flatten the compare report to observations per case and side."""
    out = {}
    for entry in report.get("cases") or []:
        case = entry.get("case") or {}
        comp = entry.get("comparison") or {}
        row = {}
        for side in ("trailhead", "agent_reach"):
            result = comp.get(side) or {}
            if not result:
                continue
            row[side] = {
                "status": result.get("status"),
                "evidence_ok": result.get("evidence_ok"),
                "evidence_verdict": result.get("evidence_verdict"),
                "duration_ms": result.get("duration_ms"),
                "cleaned_chars": result.get("cleaned_chars"),
                "error": (result.get("error") or "")[:160],
            }
        out[case.get("id", "?")] = {
            "sides": row,
            "parity_verdict": (comp.get("parity") or comp.get("verdict")
                               or entry.get("parity") or ""),
        }
    return out


# ── artifact probes (product read paths, not a new extractor) ────────────────

_TRAILHEAD_BOOTSTRAP = r"""
import json, sys
sys.path.insert(0, %r)
from hermes_trailhead.extract import extract_one
url = sys.argv[1]
result = extract_one(url, timeout=25)
sys.stdout.write(json.dumps({
    "status": result.status,
    "source_type": result.source_type,
    "content": result.content or "",
    "error": result.error_message or "",
}))
"""


def probe_trailhead(url: str, sandbox_env: dict) -> dict:
    argv = [sys.executable, "-c", _TRAILHEAD_BOOTSTRAP % str(REPO), url]
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                                   env=sandbox_env, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "text": "", "duration_ms": None}
    duration = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": (completed.stderr or "unparsable")[:200],
                "text": "", "duration_ms": duration}
    return {
        "ok": payload.get("status") == "ok",
        "status": payload.get("status"),
        "backend": payload.get("source_type"),
        "error": payload.get("error", ""),
        "text": payload.get("content", ""),
        "duration_ms": duration,
    }


def probe_agent_reach(case, executable: str, sandbox_env: dict) -> dict:
    argv = [executable] + list(case.ar_argv())
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                                   env=sandbox_env, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "text": "", "duration_ms": None}
    duration = int((time.monotonic() - started) * 1000)
    payload = None
    for chunk in (completed.stdout or "").strip().splitlines():
        chunk = chunk.strip()
        if chunk.startswith("{"):
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
    if payload is None:
        return {"ok": False, "error": (completed.stderr or completed.stdout or "no json")[:200],
                "text": "", "duration_ms": duration}
    items = payload.get("items") or []
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("title", "url", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return {
        "ok": bool(payload.get("ok")),
        "backend": payload.get("backend"),
        "error": ((payload.get("error") or {}).get("code", "")
                  if isinstance(payload.get("error"), dict) else ""),
        "items": len(items),
        "text": "\n".join(parts),
        "duration_ms": duration,
    }


_README_MARKER = re.compile(r"^README(?: excerpt)?:\s*$", re.M)


def _match_region(text: str, offset: int) -> str:
    """Where a marker matched: README body, metadata header, or unsectioned output."""
    marker = _README_MARKER.search(text)
    if marker is None:
        return "unsectioned"
    return "readme_body" if offset > marker.end() else "metadata_header"


def _occurrences(text: str, needle: str, cap: int = 200) -> list[int]:
    """Offsets of ``needle`` in ``text`` (bounded; used for region provenance)."""
    if not needle:
        return []
    out, start = [], 0
    while len(out) < cap:
        pos = text.find(needle, start)
        if pos < 0:
            break
        out.append(pos)
        start = pos + 1
    return out


def probe_read_cli(url: str, sandbox_env: dict) -> dict:
    """Run the shipped ``hermes_trailhead read`` command for one URL.

    The artifact probes above call ``extract.extract_one`` directly; this one
    exercises the public CLI surface a user actually invokes, so a difference
    between the library path and the command's payload is visible.
    """
    argv = [sys.executable, "-m", "hermes_trailhead", "read", url,
            "--format", "json", "--timeout", "25"]
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                                   env=sandbox_env, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "timeout", "text": "", "duration_ms": None}
    duration = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error_code": "unparsable", "text": "",
                "duration_ms": duration,
                "stderr": (completed.stderr or "")[:200]}
    error = payload.get("error") or {}
    return {
        "ok": bool(payload.get("ok")),
        "error_code": error.get("code", "") if isinstance(error, dict) else "",
        "source_type": payload.get("source_type", ""),
        "returned_chars": payload.get("returned_chars"),
        "content_length": payload.get("content_length"),
        "truncated": payload.get("truncated"),
        "extraction_status": payload.get("extraction_status", ""),
        "evidence_usable": (payload.get("evidence") or {}).get("usable"),
        "exit_code": completed.returncode,
        "text": payload.get("content") or "",
        "duration_ms": duration,
    }


def check_artifacts(text: str, artifacts: list[dict]) -> list[dict]:
    """Explicit presence checks. No length thresholds, no partial credit.

    Presence is all a marker proves: it does not prove the page/README was
    returned whole.  For any_of markers the matched offset is recorded (plus a
    short window and, where the output has a ``README:`` section, whether the
    match is README prose or repository metadata) so provenance is auditable.
    """
    results = []
    for artifact in artifacts:
        kind = artifact["kind"]
        if kind == "any_of":
            hit = next((v for v in artifact["values"] if v and v in text), "")
            offset = text.find(hit) if hit else -1
            regions = sorted({
                _match_region(text, pos)
                for pos in _occurrences(text, hit)
            }) if hit else []
            results.append({
                "label": artifact["label"],
                "kind": kind,
                "present": bool(hit),
                "matched": hit,
                "match_offset": offset,
                "match_region": regions[0] if regions else "",
                "match_regions": regions,
                "match_context": (text[max(0, offset - 60):offset + len(hit) + 60]
                                  .replace("\n", " ") if hit else ""),
                "expects": artifact["values"][:3],
            })
        elif kind == "regex_distinct":
            found = re.findall(artifact["pattern"], text)
            distinct = len(set(found))
            results.append({
                "label": artifact["label"],
                "kind": kind,
                "present": distinct >= artifact.get("min_distinct", 1),
                "distinct_found": distinct,
                "min_distinct": artifact.get("min_distinct", 1),
                "expects": artifact["pattern"],
            })
    return results


# ── dependency / disk inventory ──────────────────────────────────────────────

def dist_inventory(python_exe: str) -> dict:
    if not Path(python_exe).exists():
        return {"python": python_exe, "available": False}
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import json,importlib.metadata as m;"
             "print(json.dumps(sorted({d.metadata['Name'] for d in m.distributions() "
             "if d.metadata['Name']})))"],
            capture_output=True, text=True, timeout=60,
        )
        names = json.loads(out.stdout or "[]")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        names = []
    # Measure the virtualenv the executable lives in (unresolved path); the
    # interpreter itself may be a symlink into a shared uv/base install.
    root = Path(python_exe).absolute().parent.parent
    size_bytes = None
    try:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
        size_bytes = total
    except OSError:
        pass
    try:
        version_out = subprocess.run([python_exe, "-V"], capture_output=True,
                                     text=True, timeout=30).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        version_out = ""
    return {
        # Absolute paths stay in the raw scratch record; the published JSON keeps
        # only names so a shared-host layout is not leaked into a public artifact.
        "python_bin": Path(python_exe).name,
        "available": True,
        "version": version_out.replace("Python ", "") or platform.python_version(),
        "distribution_count": len(names),
        "distributions": names,
        "env_name": root.name,
        "env_disk_bytes": size_bytes,
    }


def host_inventory() -> dict:
    try:
        cpu = os.cpu_count()
        mem_kb = None
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    except OSError:
        cpu, mem_kb = os.cpu_count(), None
    return {
        "hostname_kind": "single Linux host (name withheld)",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpus": cpu,
        "mem_total_kb": mem_kb,
        "python": platform.python_version(),
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    global SCRATCH
    parser = argparse.ArgumentParser(
        description="Bounded repeatable public acceptance evidence (observations, no grades)"
    )
    parser.add_argument("--agent-reach", required=True,
                        help="Installed pinned agent-reach executable (not a bare PATH guess)")
    parser.add_argument("--scratch", required=True, help="Directory for raw outputs")
    parser.add_argument("--out", help="Write sanitized JSON evidence to this path")
    parser.add_argument("--repeats", type=int, default=3, help="Cold+warm repeats per case set")
    parser.add_argument("--timeout", type=float, default=25.0, help="Per-side wall budget (s)")
    parser.add_argument("--no-warm", action="store_true", help="Skip warm runs")
    args = parser.parse_args(argv)

    SCRATCH = Path(args.scratch).expanduser().resolve()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if not Path(args.agent_reach).exists():
        print(f"agent-reach not found: {args.agent_reach}", file=sys.stderr)
        return 2
    if not Path(TIME_BIN).exists():
        print(f"{TIME_BIN} is required for measured wall/RSS", file=sys.stderr)
        return 2

    from hermes_trailhead import comparative as comp

    ar_version = ""
    try:
        proc = subprocess.run([args.agent_reach, "channels"], capture_output=True,
                              text=True, timeout=90)
        payload = json.loads(proc.stdout or "{}")
        ar_version = str(payload.get("schema_version", ""))
        channel_count = len(payload.get("channels") or [])
    except (subprocess.SubprocessError, json.JSONDecodeError):
        channel_count = None

    dist_meta = {}
    dist_path = Path(args.agent_reach).resolve().parents[1] / "lib"
    for meta in dist_path.glob("python*/site-packages/agent_reach-*.dist-info/METADATA"):
        text = meta.read_text(errors="replace")
        match = re.search(r"^Version:\s*(\S+)", text, re.M)
        dist_meta["version"] = match.group(1) if match else ""
        dist_meta["dist_info"] = str(meta)
    direct_url = dist_path.glob("python*/site-packages/agent_reach-*.dist-info/direct_url.json")
    for path in direct_url:
        try:
            dist_meta["direct_url"] = json.loads(path.read_text()).get("url", "")
        except (json.JSONDecodeError, OSError):
            pass

    case_ids = [c["compare_case"] for c in MANIFEST["cases"]]
    warm_sandbox = SCRATCH / "warm-sandbox"
    warm_sandbox.mkdir(parents=True, exist_ok=True)

    runs = []
    for repeat in range(1, args.repeats + 1):
        for kind in (["cold", "warm"] if not args.no_warm else ["cold"]):
            sandbox = str(warm_sandbox) if kind == "warm" else None
            argv_cmp = compare_argv(case_ids, str(Path(args.agent_reach).resolve()),
                                    sandbox, args.timeout)
            measured = run_measured(argv_cmp, timeout=args.timeout * len(case_ids) * 2 + 120)
            raw_path = _scratch(f"compare-{kind}-r{repeat}.json")
            raw_path.write_text(measured["stdout"] or "")
            _scratch(f"compare-{kind}-r{repeat}.stderr").write_text(measured["stderr"] or "")
            report = {}
            try:
                report = json.loads(measured["stdout"])
            except json.JSONDecodeError:
                report = {}
            runs.append({
                "repeat": repeat,
                "run_kind": kind,
                "sandbox_reused": bool(sandbox),
                "wall_s": measured["wall_s"],
                "peak_rss_kb": measured["peak_rss_kb"],
                "exit_code": measured["exit_code"],
                "report_schema": report.get("schema", ""),
                "report_run_kind": (report.get("environment", {})
                                    .get("sandbox", {}).get("run_kind", "")),
                "outcomes": case_outcomes(report) if report else {},
                "raw_report_name": raw_path.name,
            })
            done = (report.get("summary") or {}).get("cases_both_exercised")
            print(f"[{kind} r{repeat}] wall={measured['wall_s']}s "
                  f"peakRSS={measured['peak_rss_kb']}kB exit={measured['exit_code']} "
                  f"cases={done}", file=sys.stderr)

    # Artifact completeness: one probe per side per case, in an isolated env.
    sandbox = comp.build_sandbox()
    env = sandbox["env"]
    completeness = []
    for case_spec in MANIFEST["cases"]:
        case = comp.CASES_BY_ID[case_spec["compare_case"]]
        trailhead = probe_trailhead(case.prompt, env)
        agent_reach = probe_agent_reach(case, str(Path(args.agent_reach).resolve()), env)
        entry = {
            "case_id": case_spec["case_id"],
            "language": case_spec["language"],
            "requested_outcome": case_spec["requested_outcome"],
            "sides": {},
        }
        read_cli = probe_read_cli(case.prompt, env)
        read_checks = check_artifacts(read_cli["text"], case_spec["artifacts"])
        entry["read_cli"] = {
            "command": "python -m hermes_trailhead read <url> --format json",
            "note": ("the agent_reach side has no separate CLI here: its probe is the "
                     "upstream CLI itself (see sides.agent_reach)"),
            "ok": read_cli.get("ok"),
            "error_code": read_cli.get("error_code", ""),
            "exit_code": read_cli.get("exit_code"),
            "source_type": read_cli.get("source_type", ""),
            "returned_chars": read_cli.get("returned_chars"),
            "truncated": read_cli.get("truncated"),
            "extraction_status": read_cli.get("extraction_status", ""),
            "evidence_usable": read_cli.get("evidence_usable"),
            "duration_ms": read_cli.get("duration_ms"),
            "checks": read_checks,
            "artifacts_present": sum(1 for c in read_checks if c["present"]),
            "artifacts_required": len(read_checks),
        }
        for side, probe in (("trailhead", trailhead), ("agent_reach", agent_reach)):
            checks = check_artifacts(probe["text"], case_spec["artifacts"])
            entry["sides"][side] = {
                "status": probe.get("status") or ("ok" if probe.get("ok") else "error"),
                "backend": probe.get("backend", ""),
                "error": (probe.get("error") or "")[:120],
                "duration_ms": probe.get("duration_ms"),
                "text_chars": len(probe["text"]),
                "checks": checks,
                "artifacts_present": sum(1 for c in checks if c["present"]),
                "artifacts_required": len(checks),
                "complete": all(c["present"] for c in checks),
                "informational": {
                    "distinct_topic_urls": len(set(re.findall(r"v2ex\.com/t/\d+", probe["text"]))),
                },
            }
            # Keep a bounded copy of what was checked, never the whole page.
            _scratch(f"artifact-{case_spec['case_id']}-{side}.txt").write_text(probe["text"][:20000])
        completeness.append(entry)

    gaps = []
    for entry in completeness:
        for side in ("trailhead", "agent_reach"):
            side_row = entry["sides"][side]
            missing = [c["label"] for c in side_row["checks"] if not c["present"]]
            if missing:
                gaps.append({
                    "case_id": entry["case_id"],
                    "side": side,
                    "missing_artifacts": missing,
                    "status": side_row["status"],
                })

    cold = [r for r in runs if r["run_kind"] == "cold"]
    warm = [r for r in runs if r["run_kind"] == "warm"]
    summary = {
        "runs": len(runs),
        "cold_runs": len(cold),
        "warm_runs": len(warm),
        "wall_s": {
            "cold": [r["wall_s"] for r in cold],
            "warm": [r["wall_s"] for r in warm],
        },
        "peak_rss_kb": {
            "cold": [r["peak_rss_kb"] for r in cold],
            "warm": [r["peak_rss_kb"] for r in warm],
        },
        "artifact_complete_cases": {
            side: sum(1 for e in completeness if e["sides"][side]["complete"])
            for side in ("trailhead", "agent_reach")
        },
        "cases_total": len(completeness),
        "artifact_marker_scope": (
            "presence only: 'complete' means every listed marker was found, not "
            "that the page/README was returned in full"
        ),
        "read_cli_cases_ok": sum(
            1 for e in completeness if e.get("read_cli", {}).get("ok")
        ),
        "superiority_claim": (
            "not established: this run measures parity observations and artifact "
            "completeness on three public cases; it does not compare every channel, "
            "authenticated workloads, transcription, or onboarding"
        ),
    }

    reference_actions = None
    try:
        from hermes_trailhead.reach_backend import parity_inventory

        counts = parity_inventory().get("counts") or {}
        reference_actions = {
            "actions_total": counts.get("actions"),
            "source": "hermes_trailhead.reach_backend.parity_inventory()['counts']['actions']",
            "exercised_in_this_run": len(case_ids),
            "note": ("the advertised reference surface, not this harness's coverage: "
                     f"this run exercises {len(case_ids)} public actions"),
        }
    except Exception:  # inventory is local, but never fail evidence on it
        reference_actions = None

    marker_provenance = [
        {
            "case_id": entry["case_id"],
            "side": side,
            "label": check["label"],
            "matched": check.get("matched", ""),
            "region": check.get("match_region", ""),
            "context": check.get("match_context", "")[:160],
        }
        for entry in completeness
        for side in ("trailhead", "agent_reach")
        for check in entry["sides"][side]["checks"]
        if check.get("present") and check.get("match_region") not in ("", "unsectioned")
    ]

    evidence = {
        "schema": SCHEMA,
        "generated_at": _now(),
        "host": host_inventory(),
        "manifest": MANIFEST,
        "tools": {
            "trailhead": {
                "python_bin": os.path.basename(sys.executable),
                "python_version": platform.python_version(),
                "invocation": f"{os.path.basename(sys.executable)} -m hermes_trailhead compare",
                "commit": _git_head(),
            },
            "agent_reach": {
                "executable_name": Path(args.agent_reach).name,
                "distribution": {
                    "version": dist_meta.get("version", ""),
                    "direct_url": dist_meta.get("direct_url", ""),
                },
                "channels_reported": channel_count,
                "channels_schema_version": ar_version,
                "install_source": "GitHub archive at pinned commit (see distribution.direct_url)",
            },
        },
        "dependencies": {
            "trailhead_env": dist_inventory(sys.executable),
            "agent_reach_env": dist_inventory(
                str(Path(args.agent_reach).resolve().parents[1] / "bin" / "python")
            ),
            "setup_note": (
                "install durations are not re-measured here (both tools already "
                "installed); on-disk env size and distribution counts are measured"
            ),
        },
        "budget": {"per_side_timeout_s": args.timeout, "repeats": args.repeats,
                   "case_count": len(case_ids), "asr_disabled": True,
                   "credentials_used": False},
        "measurement": {
            "process": (
                "each timed run is one `python -m hermes_trailhead compare` process "
                "that executes BOTH sides (Trailhead extraction plus the Agent Reach "
                "child/subprocesses)"
            ),
            "per_tool_rss": False,
            "per_tool_rss_note": (
                "GNU time's peak RSS is the whole compare process, so it cannot be "
                "split between Trailhead and Agent Reach; no per-tool memory "
                "comparison is claimed"
            ),
            "artifact_checks": (
                "marker presence only; a pass is not proof that the page or README "
                "was returned in full"
            ),
        },
        "reference_actions": reference_actions,
        "runs": runs,
        "completeness": completeness,
        "marker_provenance": marker_provenance,
        "gaps": gaps,
        "summary": summary,
        "limitations": [
            "One host, one network moment, three cases: not a general availability claim.",
            "Timed wall clock and peak RSS are for one compare process running BOTH "
            "sides; RSS cannot be attributed per tool, so per-tool memory is not claimed.",
            "Warm runs reuse the sandbox tree only; public HTTP caches at the origin/CDN "
            "and at each tool's backend are not controlled.",
            "Artifact markers are presence checks, not completeness proof. A marker "
            "can be satisfied by repository metadata instead of README prose, so every "
            "match records match_region and a short match_context (see "
            "marker_provenance).",
            "Artifact markers were chosen from the public artifact contract (install "
            "command, class entries, topic links) before the run; the V2EX Chinese case "
            "additionally reports distinct topic URLs as an observed count.",
            "Environment isolation is not a filesystem sandbox and no credentials were "
            "supplied to either side.",
            "No paid, authenticated, transcription, or account-lifecycle workload ran.",
        ],
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        print(f"evidence written: {out_path}", file=sys.stderr)
    else:
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0


def _git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


SCRATCH = Path(".")


if __name__ == "__main__":
    raise SystemExit(main())
