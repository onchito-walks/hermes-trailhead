#!/usr/bin/env python3
"""Frozen per-tool public resource/artifact campaign (P1 + P3).

What this script is
-------------------
One bounded harness that, for a *frozen* manifest of existing matched public
cases, does two things and nothing else:

* **P1 (artifact assessment)** — for every measured run it reads the raw stdout
  that tool actually produced, and records per requested unit
  ``present | absent | unverified`` with a +/-40 character context and the
  region (body / metadata field) the match came from.
* **P3 (per-tool resources)** — it measures **one tool per invocation** with a
  wrapper that starts exactly one child and reports that child's
  ``resource.getrusage(RUSAGE_CHILDREN)``. Peak RSS and CPU are therefore the
  measured tool's, never a comparator's.

What it is NOT
--------------
- Not a comparator: it writes no winner, ranking or index. Comparisons are left
  to a reader who is told the denominators, host, window and limitations.
- Not a completeness certificate: a run where every required marker is present
  is reported as ``markers_present`` — an observable state, never "the artifact
  is complete". ``complete`` is not a verdict this script can emit.
- Not an authenticated/paid/ASR run: both tools run in empty throwaway homes
  built by ``comparative.build_sandbox`` (no credential, cookie, proxy or
  session variable is inherited) with ``TRAILHEAD_DISABLE_ASR=1``.

Frozen rules implemented (see docs/PUBLIC-REMAINING-ACCEPTANCE.md §2, §3, §5)
----------------------------------------------------------------------------
1. ``docs/evidence/public-remaining-manifest.json`` is written and hashed
   **before** the first measured run; every run record carries its hash. A
   manifest that no longer matches its hash aborts the campaign.
2. The manifest is never edited by this script after freezing (``--freeze``
   refuses to overwrite an existing manifest unless ``--refreeze`` is passed,
   which is a new campaign and is recorded as such).
3. Exactly one tool process per measured invocation, under an equal 25 s
   killable *process-group* deadline. Cold = fresh sandbox tree, warm = second
   run in that same tree.
4. Tools alternate inside every round so a network moment cannot land on one
   side only.
5. Raw stdout/stderr stay in the scratch directory; the published JSON is
   sanitized (no absolute paths, no hostname, no username) and bounded
   (payloads are never embedded).

Usage
-----
    # 1. freeze (independent reviewer; once)
    python3 scripts/evaluate_public_resources.py --freeze \
        --manifest docs/evidence/public-remaining-manifest.json \
        --frozen-by "reviewer"

    # 2. campaign
    python3 scripts/evaluate_public_resources.py \
        --manifest docs/evidence/public-remaining-manifest.json \
        --agent-reach <pinned>/bin/agent-reach \
        --scratch "$TMPDIR/public-resource-campaign" \
        --out docs/evidence/public-resource.json \
        --rounds 5 --timeout 25
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA = "trailhead.public-resource/1"
MANIFEST_SCHEMA = "trailhead.public-remaining-manifest/1"
#: Bumped when the assessment code changes. The manifest (cases/units) is what
#: must stay frozen; this number is how a reader audits the evaluator that was
#: applied to a given campaign.
EVALUATOR_VERSION = 2
MANIFEST_HASH_FIELD = "manifest_sha256"
TOOLS = ("trailhead", "agent_reach")
STATES = ("cold", "warm")
#: Words that must never appear in a published verdict, because they would turn
#: marker presence (or a single run) into a completeness/quality claim.
FORBIDDEN_VERDICTS = ("complete", "winner", "better", "faster", "superior")

DEFAULT_TIMEOUT_S = 25.0
DEFAULT_ROUNDS = 5
DEFAULT_MAX_RAW_BYTES = 4 * 1024 * 1024
CONTEXT_CHARS = 40
#: Never pre-fill an independence claim: who froze the manifest is a fact the
#: operator has to state, and a default that reads "independent reviewer" would
#: manufacture provenance the harness cannot verify.
DEFAULT_FROZEN_BY = "unspecified"

# ── frozen case set ──────────────────────────────────────────────────────────
# The three cases are the ones already frozen in scripts/evaluate_public_acceptance.py
# (docs / GitHub / V2EX). URLs and Agent Reach argv are read from
# hermes_trailhead.comparative at freeze time and copied into the manifest, so a
# later drift in the code cannot silently re-point a frozen case.
CASE_SPECS: tuple[dict, ...] = (
    {
        "case_id": "public-docs-python-typing",
        "compare_case": "docs-python-typing",
        "family": "docs",
        "language": "en",
        "requested_outcome": (
            "the typing module reference page for an API consumer: page "
            "identity plus the Protocol / TypeVar / Generic / TypeAlias entries"
        ),
        "artifact_units": [
            {"id": "page_identity", "kind": "text_any_of",
             "values": ["Support for type hints"], "required": True,
             "whole_artifact": True},
            {"id": "entry_Protocol", "kind": "text_any_of",
             "values": ["Protocol"], "required": True, "whole_artifact": False},
            {"id": "entry_TypeVar", "kind": "text_any_of",
             "values": ["TypeVar"], "required": True, "whole_artifact": False},
            {"id": "entry_Generic", "kind": "text_any_of",
             "values": ["Generic"], "required": True, "whole_artifact": False},
            {"id": "special_form_TypeAlias", "kind": "text_any_of",
             "values": ["TypeAlias"], "required": True, "whole_artifact": False},
        ],
        "pagination_expectation": {"whole_artifact": True,
                                   "continuation": "none",
                                   "max_units_known": None},
        "truncation_matters": True,
    },
    {
        "case_id": "public-github-requests-readme",
        "compare_case": "github-requests-readme",
        "family": "github",
        "language": "en",
        "requested_outcome": (
            "psf/requests repository README: identity, the install command, one "
            "usage call, the opening description and the license it states"
        ),
        "artifact_units": [
            {"id": "repo_identity", "kind": "text_any_of",
             "values": ["psf/requests"], "required": True,
             "whole_artifact": True},
            {"id": "readme_install", "kind": "text_any_of",
             "values": ["pip install requests"], "required": True,
             "whole_artifact": False},
            {"id": "readme_usage", "kind": "text_any_of",
             "values": ["requests.get("], "required": True,
             "whole_artifact": False},
            {"id": "readme_intro", "kind": "text_any_of",
             "values": ["A simple, yet elegant, HTTP library"], "required": True,
             "whole_artifact": False},
            {"id": "license_mentioned", "kind": "text_any_of",
             "values": ["Apache License", "Apache-2.0"], "required": False,
             "whole_artifact": False},
            {"id": "identity_url_field", "kind": "field_present",
             "field": "url", "required": False, "whole_artifact": False},
        ],
        "pagination_expectation": {"whole_artifact": True,
                                   "continuation": "none",
                                   "max_units_known": None},
        "truncation_matters": True,
    },
    {
        "case_id": "public-v2ex-node-python-zh",
        "compare_case": "forum-v2ex-node",
        "family": "v2ex",
        "language": "zh-Hans",
        "requested_outcome": (
            "the V2EX Python node listing (Chinese): node identity plus the "
            "titles and links of the listed topics"
        ),
        "artifact_units": [
            {"id": "node_identity", "kind": "text_any_of",
             "values": ["Python", "python"], "required": True,
             "whole_artifact": True},
            {"id": "chinese_topic_prose", "kind": "regex_distinct",
             "pattern": "[\\u4e00-\\u9fff]{8,}", "min_distinct": 3,
             "required": True, "whole_artifact": False},
            {"id": "topic_urls", "kind": "regex_distinct",
             "pattern": "v2ex\\.com/t/\\d+", "min_distinct": 3,
             "required": True, "whole_artifact": True},
        ],
        "pagination_expectation": {"whole_artifact": True,
                                   "continuation": "page",
                                   "max_units_known": None},
        "truncation_matters": True,
    },
)

#: Env keys a measured child may see. Anything credential-shaped aborts the run.
ALLOWED_ENV_KEYS = frozenset({
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "PYTHONIOENCODING",
    "HOME", "HERMES_HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    "TRAILHEAD_AGENT_REACH_HOME", "TRAILHEAD_DISABLE_ASR", "PYTHONPATH",
})
SENSITIVE_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "COOKIE", "API_KEY", "APIKEY",
    "CREDENTIAL", "SESSION", "AUTH", "PROXY", "BEARER", "PRIVATE",
)


# ── small helpers ────────────────────────────────────────────────────────────

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(obj) -> str:
    """Canonical JSON used for hashing (stable across dict ordering)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_hash(manifest: dict) -> str:
    """SHA-256 of the canonical manifest **without** its own hash field."""
    body = {k: v for k, v in manifest.items() if k != MANIFEST_HASH_FIELD}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _scrub(text: str) -> str:
    """Remove absolute paths / user names from a string bound for publication."""
    if not text:
        return ""
    text = re.sub(
        r"(?<![\w:/])/(?:home|srv|tmp|var|usr|opt|root|mnt|proc|etc)"
        r"(?:/[\w.@+-]+)+/?",
        "<path>", text)
    text = re.sub(r"\b[\w.@+-]+@[\w.-]+\b", "<user>", text)
    return text[:400]


def distribution(values: list) -> dict:
    """n / min / median / max for one metric. Never a single-run 'the number'."""
    clean = sorted(v for v in values if isinstance(v, (int, float)))
    if not clean:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {
        "n": len(clean),
        "min": clean[0],
        "median": round(statistics.median(clean), 3),
        "max": clean[-1],
    }


# ── manifest ─────────────────────────────────────────────────────────────────

def build_manifest(frozen_by: str, timeout_s: float, rounds: int,
                   frozen_at: str | None = None) -> dict:
    """Freeze the three matched public cases into the §2 manifest shape."""
    from hermes_trailhead import comparative as comp  # local import: no network

    cases = []
    for spec in CASE_SPECS:
        case = comp.CASES_BY_ID[spec["compare_case"]]
        ar_argv = case.ar_argv() + ["--timeout", f"{timeout_s:g}"]
        cases.append({
            "case_id": spec["case_id"],
            "compare_case": spec["compare_case"],
            "lane": "public",
            "language": spec["language"],
            "family": spec["family"],
            "url_or_action": (
                case.prompt if not spec["family"] == "v2ex"
                else f"{case.prompt} (agent-reach: {' '.join(case.ar_argv())})"
            ),
            "url": case.prompt,
            "requested_outcome": spec["requested_outcome"],
            # Placeholders, not host paths: the manifest is a public artifact.
            "tool_argv": {
                "trailhead": ["python", "-m", "hermes_trailhead", "read",
                              case.prompt, "--format", "json",
                              "--timeout", f"{timeout_s:g}"],
                "agent_reach": ["<agent-reach>", *ar_argv],
            },
            "artifact_units": [dict(unit) for unit in spec["artifact_units"]],
            "pagination_expectation": dict(spec["pagination_expectation"]),
            "truncation_matters": spec["truncation_matters"],
        })

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "frozen_at": frozen_at or now_utc(),
        "frozen_by": frozen_by,
        "campaign": {
            "rounds_per_case_tool_state": rounds,
            "states": list(STATES),
            "timeout_s": timeout_s,
            "tools": list(TOOLS),
            "interleaved": True,
            "asr_disabled": True,
            "credentials": "none (public lane)",
        },
        "rules": {
            "artifact_units": "requested outcomes; immutable after the first measured run",
            "verdict_vocabulary": ["markers_present", "incomplete", "unverified"],
            "completeness_claim": "none — marker presence is never called completeness",
            "pagination_unknown": "counts as not exhausted",
        },
        "cases": cases,
    }
    manifest[MANIFEST_HASH_FIELD] = manifest_hash(manifest)
    return manifest


def write_manifest(manifest: dict, path: str | Path) -> dict:
    path = Path(path)
    manifest = dict(manifest)
    manifest[MANIFEST_HASH_FIELD] = manifest_hash(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def load_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def verify_manifest(manifest: dict) -> tuple[bool, str]:
    recorded = manifest.get(MANIFEST_HASH_FIELD) or ""
    computed = manifest_hash(manifest)
    if not recorded:
        return False, "manifest has no manifest_sha256"
    if recorded != computed:
        return False, f"manifest hash mismatch (recorded {recorded[:12]}…)"
    return True, ""


# ── per-tool payload reading ─────────────────────────────────────────────────

def _iter_json_objects(text: str) -> list[dict]:
    """Top-level JSON objects in stdout, bounded; last parsable object wins."""
    out = []
    stripped = (text or "").strip()
    if not stripped:
        return out
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            out.append(obj)
            return out
    except json.JSONDecodeError:
        pass
    for line in stripped.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _pagination_state(pagination) -> dict:
    """Continuation state from a tool's own payload; unknown stays unknown."""
    if not isinstance(pagination, dict) or not pagination:
        return {"state": "unknown", "source": "absent"}
    more = pagination.get("more")
    next_offset = pagination.get("next_offset")
    if more is False and not next_offset:
        return {"state": "exhausted", "source": "payload.pagination"}
    if more is True or next_offset:
        return {"state": "pending", "source": "payload.pagination",
                "next_offset": next_offset}
    return {"state": "unknown", "source": "payload.pagination"}


def has_artifact(payload: dict) -> bool:
    """True only when there is an artifact to search for markers.

    A parsed *error* envelope (``ok: false``) is not an artifact: the tool
    returned a failure record, not the requested content. Its units are
    ``unverified`` — never ``absent`` — because nothing was ever returned to
    search, and a failed run must not be published as an incomplete artifact.
    """
    return bool(payload.get("parsed")) and payload.get("ok") is not False


def read_payload(tool: str, raw_stdout: str) -> dict:
    """Normalize one tool's raw stdout into body / metadata / flags.

    ``body`` is the text the caller asked for. ``metadata`` is envelope/field
    text (title, url, author, status fields) and is tracked separately so a
    metadata match can never be reported as body text.
    """
    blank = {
        "parsed": False, "ok": False, "error_code": "", "status": "unparsed",
        "body": "", "metadata": "", "fields": {}, "truncated": None,
        "continuation": {"state": "unknown", "source": "absent"},
        "items": None, "returned_chars": None, "note": "",
    }
    objects = _iter_json_objects(raw_stdout)
    if not objects:
        return {**blank, "status": "unparsed",
                "note": "stdout carried no JSON object"}
    payload = objects[-1]

    if tool == "trailhead":
        error = payload.get("error") or {}
        fields = {
            "url": payload.get("url"),
            "source_type": payload.get("source_type"),
            "extraction_status": payload.get("extraction_status"),
            "command": payload.get("command"),
        }
        body = payload.get("content") or ""
        metadata = " ".join(str(v) for v in fields.values() if v)
        return {
            "parsed": True,
            "ok": bool(payload.get("ok")),
            "error_code": (error.get("code", "") if isinstance(error, dict) else ""),
            "status": "ok" if payload.get("ok") else "error",
            "body": body,
            "metadata": metadata,
            "fields": fields,
            "truncated": payload.get("truncated"),
            "continuation": _pagination_state(payload.get("pagination")),
            "items": None,
            "returned_chars": payload.get("returned_chars"),
            "note": "",
        }

    if tool == "agent_reach":
        error = payload.get("error") or {}
        items = payload.get("items") or []
        body_parts, meta_parts, fields = [], [], {
            "backend": payload.get("backend"),
            "channel": payload.get("channel"),
            "action": payload.get("action"),
        }
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("text",):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    body_parts.append(value)
            for key in ("title", "url", "author", "published_at"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    meta_parts.append(value)
                    fields.setdefault(key, value)
        return {
            "parsed": True,
            "ok": bool(payload.get("ok")),
            "error_code": (error.get("code", "") if isinstance(error, dict) else ""),
            "status": "ok" if payload.get("ok") else "error",
            "body": "\n".join(body_parts),
            "metadata": "\n".join(meta_parts),
            "fields": fields,
            # Upstream carries no truncation flag: unknown, never "false".
            "truncated": payload.get("truncated"),
            "continuation": _pagination_state(_ar_pagination(payload)),
            "items": len(items),
            "returned_chars": len("\n".join(body_parts)),
            "note": "",
        }


    return {**blank, "status": "error", "note": f"unknown tool {tool}"}


def _ar_pagination(payload: dict) -> dict:
    """Agent Reach pagination/cursor field if the payload has one."""
    for candidate in (payload.get("pagination"),
                      (payload.get("meta") or {}).get("pagination")
                      if isinstance(payload.get("meta"), dict) else None):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


# ── artifact units ───────────────────────────────────────────────────────────

def _context(text: str, offset: int, length: int) -> str:
    start = max(0, offset - CONTEXT_CHARS)
    end = min(len(text), offset + length + CONTEXT_CHARS)
    return text[start:end].replace("\n", " ").strip()


def _field_value(fields: dict, dotted: str):
    node = fields
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def assess_units(units: list[dict], payload: dict) -> list[dict]:
    """Per-unit ``present | absent | unverified`` with region + bounded context.

    ``unverified`` is reserved for "there was no artifact to evaluate"; an
    absent marker inside a real payload is ``absent``, never ``unverified``.
    """
    results = []
    if not has_artifact(payload):
        if not payload.get("parsed"):
            reason = "no artifact returned (unparsable or empty payload)"
        else:
            reason = (
                "no artifact returned (tool reported failure "
                f"{payload.get('status')!r}, error {payload.get('error_code') or 'none'})"
            )
        for unit in units:
            results.append({
                "id": unit["id"], "kind": unit["kind"], "state": "unverified",
                "required": bool(unit.get("required")),
                "whole_artifact": bool(unit.get("whole_artifact")),
                "reason": reason,
                "matched": "", "region": "", "offset": None, "context": "",
            })
        return results

    body = payload.get("body") or ""
    metadata = payload.get("metadata") or ""
    for unit in units:
        kind = unit["kind"]
        row = {
            "id": unit["id"], "kind": kind,
            "required": bool(unit.get("required")),
            "whole_artifact": bool(unit.get("whole_artifact")),
            "matched": "", "region": "", "offset": None, "context": "",
            "reason": "",
        }
        if kind == "text_any_of":
            hit = next((v for v in unit.get("values", []) if v and v in body), "")
            if hit:
                offset = body.find(hit)
                row.update(state="present", matched=hit, region="body",
                           offset=offset,
                           context=_context(body, offset, len(hit)))
            else:
                meta_hit = next((v for v in unit.get("values", []) if v and v in metadata), "")
                if meta_hit:
                    offset = metadata.find(meta_hit)
                    row.update(state="present", matched=meta_hit,
                               region="metadata_field", offset=offset,
                               context=_context(metadata, offset, len(meta_hit)),
                               reason="matched envelope/field text, not body text")
                else:
                    row.update(state="absent",
                               reason="none of the declared values appear in body or metadata")
        elif kind == "regex_distinct":
            pattern = unit.get("pattern", "")
            in_body = re.findall(pattern, body) if pattern else []
            in_meta = re.findall(pattern, metadata) if pattern else []
            need = int(unit.get("min_distinct", 1))
            distinct_body = len(set(in_body))
            # Links/ids a caller asked for may legitimately live in a structured
            # field (Agent Reach returns topic URLs in `url`, not in `text`).
            # They are counted, but the region is recorded so a reader can see
            # the match was not body prose.
            distinct_all = len(set(in_body) | set(in_meta))
            region = ("body" if in_body else
                      "metadata_field" if in_meta else "")
            row.update(
                distinct_found=distinct_all,
                distinct_body=distinct_body,
                distinct_metadata=len(set(in_meta) - set(in_body)),
                min_distinct=need,
                state="present" if distinct_all >= need else "absent",
                region=region,
                reason="" if distinct_all >= need else
                f"{distinct_all} distinct match(es) < min_distinct {need}",
            )
        elif kind == "field_present":
            field = unit.get("field", "")
            value = _field_value(payload.get("fields") or {}, field)
            if isinstance(value, (str, int, float)) and str(value).strip():
                row.update(state="present", matched=str(value)[:120],
                           region="structured_field", offset=None,
                           context=_scrub(str(value))[:160])
            else:
                row.update(state="absent",
                           reason=f"payload exposes no non-empty field {field!r}")
        else:
            row.update(state="unverified", reason=f"unsupported unit kind {kind!r}")
        results.append(row)
    return results


def case_verdict(units: list[dict], payload: dict, expectation: dict) -> dict:
    """Gate a per-run verdict on the frozen rules; never emits ``complete``.

    ``markers_present`` means every required marker was found, truncation was
    explicitly reported false, and the continuation was known to be exhausted
    (or the case declares none). It is an observation about markers on this
    run, not a completeness certificate.

    ``unverified`` means there was no artifact at all (unparsable output, or a
    tool error envelope). Such a run is never reported as ``incomplete``: a
    failure to produce an artifact says nothing about what the artifact
    contained, and its required units stay out of the presence denominator.
    """
    required = [u for u in units if u["required"]]
    reasons: list[str] = []
    if not has_artifact(payload):
        if not payload.get("parsed"):
            reasons.append("no artifact to evaluate: stdout carried no JSON object")
        else:
            reasons.append(
                "no artifact to evaluate: tool reported failure "
                f"{payload.get('status')!r} ({payload.get('error_code') or 'no error code'})"
            )
        return {
            "verdict": "unverified", "reasons": reasons, "incomplete_for": None,
            "required_total": len(required), "required_present": 0,
            "required_assessed": 0,
            "markers_total": len(units),
            "markers_present": sum(1 for u in units if u["state"] == "present"),
            "continuation_state": (payload.get("continuation") or {}).get("state", "unknown"),
            "truncated": payload.get("truncated"),
            "completeness_claim": "none",
        }

    missing = [u["id"] for u in required if u["state"] == "absent"]
    unverified = [u["id"] for u in required if u["state"] == "unverified"]
    truncated_units = [u["id"] for u in required
                       if u["whole_artifact"] and payload.get("truncated") is True]

    if missing:
        reasons.append("required_unit_absent:" + ",".join(missing))
    if unverified:
        reasons.append("required_unit_unverified:" + ",".join(unverified))
    if truncated_units:
        reasons.append("required_unit_truncated:" + ",".join(truncated_units))

    truncation_unknown = (
        payload.get("truncated") is None
        and any(u["whole_artifact"] for u in required)
        and bool(expectation.get("whole_artifact"))
    )
    if truncation_unknown:
        reasons.append("truncation_unverified: payload reports no truncation flag")

    continuation = payload.get("continuation") or {"state": "unknown"}
    continuation_state = continuation.get("state", "unknown")
    wants_continuation = expectation.get("continuation", "none") != "none"
    if wants_continuation and continuation_state != "exhausted":
        reasons.append(f"continuation_not_exhausted:{continuation_state}")

    if missing or truncated_units:
        verdict = "incomplete"
    elif unverified or truncation_unknown:
        verdict = "incomplete"
    elif wants_continuation and continuation_state != "exhausted":
        verdict = "incomplete"
    else:
        verdict = "markers_present"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "required_total": len(required),
        "required_present": sum(1 for u in required if u["state"] == "present"),
        "required_assessed": sum(1 for u in required
                                 if u["state"] in ("present", "absent")),
        "markers_total": len(units),
        "markers_present": sum(1 for u in units if u["state"] == "present"),
        "continuation_state": continuation_state,
        "truncated": payload.get("truncated"),
        "completeness_claim": "none",
    }


# ── measurement: one tool, one child, equal killable deadline ────────────────

WRAPPER_SRC = r'''
import json, os, resource, signal, subprocess, sys, time

spec = json.loads(sys.argv[1])
result = {"started": False, "error": ""}
t0 = time.monotonic()
try:
    out_f = open(spec["stdout"], "wb")
    err_f = open(spec["stderr"], "wb")
    try:
        proc = subprocess.Popen(
            spec["argv"], stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL,
            cwd=spec.get("cwd") or None, env=spec["env"], start_new_session=True,
        )
        result["started"] = True
        result["pid"] = proc.pid
        timed_out = False
        try:
            code = proc.wait(timeout=spec["timeout_s"])
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                code = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                code = None
        result.update(exit_code=code, timed_out=timed_out)
    finally:
        out_f.close()
        err_f.close()
except OSError as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
    result.setdefault("exit_code", None)
    result.setdefault("timed_out", False)

wall = time.monotonic() - t0
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
result.update(
    wall_s=round(wall, 3),
    cpu_user_s=round(ru.ru_utime, 3),
    cpu_sys_s=round(ru.ru_stime, 3),
    peak_rss_kb=int(ru.ru_maxrss),
    child_count=1,
)
with open(spec["result"], "w", encoding="utf-8") as handle:
    json.dump(result, handle)
'''


def measure_once(argv: list[str], *, env: dict, cwd: str, timeout_s: float,
                 stdout_path: Path, stderr_path: Path,
                 max_raw_bytes: int) -> dict:
    """Run exactly one tool process under one killable 25 s group deadline.

    The wrapper starts exactly one child, so ``RUSAGE_CHILDREN.maxrss`` is that
    child's peak RSS: no comparator, no second tool, nothing combined.
    """
    result_path = stdout_path.with_suffix(".rusage.json")
    spec = {
        "argv": list(argv),
        "env": dict(env),
        "cwd": cwd,
        "timeout_s": timeout_s,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "result": str(result_path),
    }
    started = now_utc()
    try:
        wrapper = subprocess.run(
            [sys.executable, "-c", WRAPPER_SRC, json.dumps(spec)],
            capture_output=True, text=True, timeout=timeout_s + 30,
        )
        wrapper_err = (wrapper.stderr or "")[:400]
        wrapper_code = wrapper.returncode
    except subprocess.TimeoutExpired:
        wrapper_err, wrapper_code = "wrapper exceeded its own grace window", None

    measured: dict = {}
    if result_path.exists():
        try:
            measured = json.loads(result_path.read_text())
        except json.JSONDecodeError:
            measured = {}
    stdout_bytes = stdout_path.stat().st_size if stdout_path.exists() else 0
    stderr_bytes = stderr_path.stat().st_size if stderr_path.exists() else 0
    capped = False
    if stdout_bytes > max_raw_bytes:
        with open(stdout_path, "rb") as handle:
            head = handle.read(max_raw_bytes)
        stdout_path.write_bytes(head)
        capped = True

    status = "ok"
    if not measured or "wall_s" not in measured:
        # The wrapper itself died or was killed before writing its rusage
        # record. Nothing about this invocation was measured, so it must never
        # be published as a successful run with null metrics.
        status = "harness_error"
    elif measured.get("error"):
        status = "harness_error"
    elif measured.get("timed_out"):
        status = "timeout"
    elif measured.get("exit_code") not in (0, None):
        status = f"exit:{measured.get('exit_code')}"

    return {
        "started_at": started,
        "wall_s": measured.get("wall_s"),
        "cpu_user_s": measured.get("cpu_user_s"),
        "cpu_sys_s": measured.get("cpu_sys_s"),
        "peak_rss_kb": measured.get("peak_rss_kb"),
        "exit_code": measured.get("exit_code"),
        "timed_out": bool(measured.get("timed_out")),
        "status": status,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "raw_capped": capped,
        "file_names": {"stdout": stdout_path.name, "stderr": stderr_path.name,
                       "rusage": result_path.name},
        "wrapper": {"exit_code": wrapper_code, "stderr": _scrub(wrapper_err)},
    }


def classify(status: str, payload: dict) -> str:
    """Normalize a run status, keeping the tool's own error code visible."""
    if status != "ok":
        return status
    if payload.get("ok"):
        return "ok"
    code = (payload.get("error_code") or "").lower()
    if code in {"rate_limited", "blocked", "auth_required", "missing_page",
                "timeout", "not_found", "bad_input"}:
        return code
    return f"error:{code}" if code else "error"


def check_env(env: dict) -> None:
    """Fail closed if a measured child could see a credential-shaped variable."""
    unexpected = set(env) - ALLOWED_ENV_KEYS
    if unexpected:
        raise SystemExit(f"refusing to run: unexpected env keys {sorted(unexpected)}")
    leaks = [k for k in env if any(m in k.upper() for m in SENSITIVE_MARKERS)]
    if leaks:
        raise SystemExit(f"refusing to run: credential-shaped env keys {sorted(leaks)}")
    if env.get("TRAILHEAD_DISABLE_ASR") != "1":
        raise SystemExit("refusing to run: TRAILHEAD_DISABLE_ASR is not 1")


# ── campaign ─────────────────────────────────────────────────────────────────

def tool_argv(tool: str, case: dict, agent_reach: str, timeout_s: float) -> list[str]:
    """Render a frozen ``tool_argv`` with placeholders resolved.

    The manifest stores placeholders (``python``, ``<agent-reach>``) so the
    published artifact carries no host paths; resolution happens here, per run.
    """
    frozen = case["tool_argv"][tool]
    out = []
    for index, part in enumerate(frozen):
        if index == 0 and tool == "trailhead":
            out.append(sys.executable)
        elif index == 0 and tool == "agent_reach":
            out.append(agent_reach)
        else:
            out.append(part)
    # Keep the deadline identical in the frozen argv and in the harness kill.
    for index, part in enumerate(out[:-1]):
        if part == "--timeout":
            out[index + 1] = f"{timeout_s:g}"
    return out


def run_campaign(manifest: dict, agent_reach: str, scratch: Path, rounds: int,
                 timeout_s: float, max_raw_bytes: int) -> dict:
    from hermes_trailhead import comparative as comp

    scratch.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    case_rows: list[dict] = []

    for case in manifest["cases"]:
        case_scratch = scratch / case["case_id"]
        case_scratch.mkdir(parents=True, exist_ok=True)

        for round_no in range(1, rounds + 1):
            # One empty tree per (case, tool, round). `cold` runs in it first;
            # `warm` is the second run in that same tree -- nothing is inherited
            # from an earlier round.
            trees = {tool: case_scratch / f"tree-{tool}-r{round_no}" for tool in TOOLS}
            for state in STATES:
                # Interleave the two tools inside the same state, in the same
                # time window: a network change cannot land on one side only.
                for tool in TOOLS:
                    sandbox = comp.build_sandbox(trees[tool])
                    env = sandbox["env"]
                    check_env(env)
                    argv = tool_argv(tool, case, agent_reach, timeout_s)
                    stem = f"{tool}-{state}-r{round_no}"
                    out_path = case_scratch / f"{stem}.stdout.json"
                    err_path = case_scratch / f"{stem}.stderr.txt"
                    measured = measure_once(
                        argv, env=env, cwd=str(REPO), timeout_s=timeout_s,
                        stdout_path=out_path, stderr_path=err_path,
                        max_raw_bytes=max_raw_bytes,
                    )
                    raw_stdout = ""
                    if out_path.exists():
                        raw_stdout = out_path.read_text(errors="replace")
                    payload = read_payload(tool, raw_stdout)
                    units = assess_units(case["artifact_units"], payload)
                    verdict = case_verdict(units, payload,
                                           case["pagination_expectation"])
                    status = classify(measured["status"], payload)
                    row = {
                        "case_id": case["case_id"],
                        "tool": tool,
                        "state": state,
                        "round": round_no,
                        "sandbox_reused": state == "warm",
                        "sandbox_tree": f"{case['case_id']}/tree-{tool}-r{round_no}",
                        "loadavg": _loadavg(),
                        "status": status,
                        "tool_ok": bool(payload.get("ok")),
                        "error_code": payload.get("error_code", ""),
                        "started_at": measured["started_at"],
                        "wall_s": measured["wall_s"],
                        "cpu_user_s": measured["cpu_user_s"],
                        "cpu_sys_s": measured["cpu_sys_s"],
                        "peak_rss_kb": measured["peak_rss_kb"],
                        "exit_code": measured["exit_code"],
                        "timed_out": measured["timed_out"],
                        "stdout_bytes": measured["stdout_bytes"],
                        "stderr_bytes": measured["stderr_bytes"],
                        "raw_capped": measured["raw_capped"],
                        "items": payload.get("items"),
                        "returned_chars": payload.get("returned_chars"),
                        "truncated": payload.get("truncated"),
                        "continuation": payload.get("continuation"),
                        "units": units,
                        "verdict": verdict["verdict"],
                        "verdict_reasons": verdict["reasons"],
                        "required_present": verdict.get("required_present"),
                        "required_total": verdict.get("required_total"),
                        "required_assessed": verdict.get("required_assessed"),
                        "artifacts": {
                            "unit_states": {u["id"]: u["state"] for u in units},
                            "body_chars": len(payload.get("body") or ""),
                            "metadata_chars": len(payload.get("metadata") or ""),
                            "body_sha256": hashlib.sha256(
                                (payload.get("body") or "").encode("utf-8")).hexdigest()[:16],
                        },
                        "raw_files": measured["file_names"],
                        "wrapper": measured["wrapper"],
                    }
                    runs.append(row)
                    print(
                        f"[{case['case_id']} {tool} {state} r{round_no}] "
                        f"status={status} wall={row['wall_s']}s "
                        f"cpu={_cpu(row)}s rss={row['peak_rss_kb']}kB "
                        f"units={row['required_present']}/{row['required_total']} "
                        f"verdict={row['verdict']}",
                        file=sys.stderr,
                    )

        case_rows.append({
            "case_id": case["case_id"],
            "requested_outcome": case["requested_outcome"],
            "pagination_expectation": case["pagination_expectation"],
            "tools": {
                tool: {
                    state: _summarize([r for r in runs
                                       if r["case_id"] == case["case_id"]
                                       and r["tool"] == tool and r["state"] == state])
                    for state in STATES
                }
                for tool in TOOLS
            },
        })

    return {"runs": runs, "cases": case_rows}


def _cpu(row: dict) -> float | str:
    if row.get("cpu_user_s") is None or row.get("cpu_sys_s") is None:
        return "?"
    return round(row["cpu_user_s"] + row["cpu_sys_s"], 3)


def _loadavg() -> list[float] | None:
    """1/5/15-minute load average at the moment a run started."""
    try:
        return [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except (OSError, ValueError):
        return None


def _assessed_required(row: dict) -> int:
    """Required units on this row that actually had an artifact to assess.

    Rows produced before ``required_assessed`` existed are derived from the
    verdict: an ``unverified`` row assessed nothing.
    """
    value = row.get("required_assessed")
    if value is not None:
        return int(value)
    if row.get("verdict") == "unverified":
        return 0
    return int(row.get("required_total") or 0)


def _summarize(rows: list[dict]) -> dict:
    """Per tool / case / state aggregates. Never mixes the two tools."""
    declared = sum(int(r["required_total"] or 0) for r in rows)
    assessed = sum(_assessed_required(r) for r in rows)
    return {
        "attempts": len(rows),
        "ok": sum(1 for r in rows if r["status"] == "ok"),
        "status_counts": _counts(r["status"] for r in rows),
        "verdict_counts": _counts(r["verdict"] for r in rows),
        "timeouts": sum(1 for r in rows if r["timed_out"]),
        "truncated_counts": _counts(str(r["truncated"]) for r in rows),
        "wall_s": distribution([r["wall_s"] for r in rows]),
        "cpu_total_s": distribution([
            (r["cpu_user_s"] + r["cpu_sys_s"])
            for r in rows if r["cpu_user_s"] is not None and r["cpu_sys_s"] is not None
        ]),
        "cpu_user_s": distribution([r["cpu_user_s"] for r in rows]),
        "cpu_sys_s": distribution([r["cpu_sys_s"] for r in rows]),
        "peak_rss_kb": distribution([r["peak_rss_kb"] for r in rows]),
        "stdout_bytes": distribution([r["stdout_bytes"] for r in rows]),
        "stderr_bytes": distribution([r["stderr_bytes"] for r in rows]),
        "required_unit_presence": {
            "present": sum(r["required_present"] or 0 for r in rows),
            # ``total`` is every required unit the frozen cases declare for the
            # attempts made; ``assessed`` excludes units whose run produced no
            # artifact. A ratio over ``total`` is a lower bound, never a rate.
            "total": declared,
            "assessed": assessed,
            "unassessed": declared - assessed,
        },
        "raw_capped": sum(1 for r in rows if r["raw_capped"]),
    }


def _counts(values) -> dict:
    out: dict = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


# ── host / tool inventory ────────────────────────────────────────────────────

def host_inventory() -> dict:
    cpu, mem_kb, load = os.cpu_count(), None, None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    except OSError:
        pass
    try:
        load = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except (OSError, ValueError):
        pass
    return {
        "hostname": "single Linux host (name withheld)",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpus": cpu,
        "mem_total_kb": mem_kb,
        "loadavg_at_start": load,
        "python": platform.python_version(),
        "measurement_host_note": (
            "one host; per-run load is recorded so a reader can see whether the "
            "runs shared the machine with other work"
        ),
    }


def tool_inventory(agent_reach: str) -> dict:
    exe = Path(agent_reach).resolve()
    dist_dir = exe.parents[1] / "lib"
    version, direct_url, dist_name = "", "", ""
    for meta in dist_dir.glob("python*/site-packages/agent_reach-*.dist-info/METADATA"):
        text = meta.read_text(errors="replace")
        match = re.search(r"^Version:\s*(\S+)", text, re.M)
        version = match.group(1) if match else ""
        name = re.search(r"^Name:\s*(\S+)", text, re.M)
        dist_name = name.group(1) if name else ""
        break
    for path in dist_dir.glob("python*/site-packages/agent_reach-*.dist-info/direct_url.json"):
        try:
            direct_url = json.loads(path.read_text()).get("url", "")
        except (json.JSONDecodeError, OSError):
            pass
    commit = ""
    match = re.search(r"/([0-9a-f]{40})\.zip", direct_url or "")
    if match:
        commit = match.group(1)
    try:
        exe_sha = sha256_file(exe)
    except OSError:
        exe_sha = ""
    trailhead_commit = ""
    try:
        trailhead_commit = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return {
        "trailhead": {
            "invocation": "python -m hermes_trailhead read <url> --format json --timeout 25",
            "python": platform.python_version(),
            "commit": trailhead_commit,
        },
        "agent_reach": {
            "executable_name": exe.name,
            "distribution_name": dist_name,
            "version": version,
            "pinned_commit": commit,
            "direct_url": direct_url,
            "executable_sha256": exe_sha,
            "install_source": "GitHub archive at a pinned commit (direct_url)",
        },
    }


def dependency_surface(agent_reach: str) -> dict:
    """On-disk env size / distribution count — setup cost, reported separately."""
    def env_root(python_exe: str) -> dict:
        root = Path(python_exe).absolute().parent.parent
        count, size = None, None
        try:
            out = subprocess.run(
                [python_exe, "-c",
                 "import importlib.metadata as m;"
                 "print(len({d.metadata['Name'] for d in m.distributions() "
                 "if d.metadata['Name']}))"],
                capture_output=True, text=True, timeout=60)
            count = int(out.stdout.strip() or 0)
        except (subprocess.SubprocessError, ValueError):
            pass
        total = 0
        try:
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    try:
                        total += os.lstat(os.path.join(dirpath, name)).st_size
                    except OSError:
                        pass
            size = total
        except OSError:
            pass
        return {"env_name": root.name, "distribution_count": count,
                "env_disk_bytes": size}

    return {
        "trailhead_env": env_root(sys.executable),
        "agent_reach_env": env_root(
            str(Path(agent_reach).resolve().parents[1] / "bin" / "python")),
        "note": (
            "both environments were already installed; on-disk size and "
            "distribution count are measured, install duration is not "
            "re-measured, and a dev venv is not a like-for-like runtime "
            "footprint"
        ),
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Frozen per-tool public artifact/resource campaign (P1+P3); no winner")
    parser.add_argument("--manifest", default=str(REPO / "docs" / "evidence"
                                                  / "public-remaining-manifest.json"))
    parser.add_argument("--agent-reach", help="pinned agent-reach executable")
    parser.add_argument("--scratch", help="directory for raw stdout/stderr + rusage")
    parser.add_argument("--out", help="sanitized evidence JSON")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--max-raw-bytes", type=int, default=DEFAULT_MAX_RAW_BYTES)
    parser.add_argument("--freeze", action="store_true",
                        help="write and hash the manifest (no measured run)")
    parser.add_argument("--refreeze", action="store_true",
                        help="overwrite an existing manifest: a new campaign")
    parser.add_argument("--frozen-by", default=DEFAULT_FROZEN_BY,
                        help="who froze the manifest, recorded verbatim")
    parser.add_argument("--verify-only", action="store_true",
                        help="verify the frozen manifest hash and exit")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if args.freeze:
        if manifest_path.exists() and not args.refreeze:
            print(f"manifest already frozen at {manifest_path.name}; "
                  "pass --refreeze for a new campaign", file=sys.stderr)
            return 2
        manifest = write_manifest(
            build_manifest(args.frozen_by, args.timeout, args.rounds),
            manifest_path)
        if args.frozen_by == DEFAULT_FROZEN_BY:
            print("warning: --frozen-by was not given; the manifest records "
                  "'unspecified', not an independent reviewer", file=sys.stderr)
        print(json.dumps({
            "manifest": manifest_path.name,
            "manifest_sha256": manifest[MANIFEST_HASH_FIELD],
            "cases": [c["case_id"] for c in manifest["cases"]],
            "frozen_at": manifest["frozen_at"],
            "frozen_by": manifest["frozen_by"],
        }, indent=2), file=sys.stderr)
        return 0

    if not manifest_path.exists():
        print(f"frozen manifest missing: {manifest_path}; run --freeze first",
              file=sys.stderr)
        return 2
    manifest = load_manifest(manifest_path)
    ok, why = verify_manifest(manifest)
    if not ok:
        print(f"refusing to run: {why}", file=sys.stderr)
        return 2
    if args.verify_only:
        print(json.dumps({"manifest": manifest_path.name,
                          "manifest_sha256": manifest[MANIFEST_HASH_FIELD],
                          "cases": len(manifest["cases"]),
                          "verified": True}, indent=2))
        return 0

    missing = [name for name, value in
               (("--agent-reach", args.agent_reach), ("--scratch", args.scratch),
                ("--out", args.out)) if not value]
    if missing:
        print(f"missing required: {', '.join(missing)}", file=sys.stderr)
        return 2
    agent_reach = str(Path(args.agent_reach).expanduser().resolve())
    if not Path(agent_reach).is_file() or not os.access(agent_reach, os.X_OK):
        print(f"agent-reach is not an executable file: {agent_reach}", file=sys.stderr)
        return 2
    scratch = Path(args.scratch).expanduser().resolve()
    rounds = max(1, min(args.rounds, 20))

    inventory_tools = tool_inventory(agent_reach)
    if not inventory_tools["agent_reach"]["pinned_commit"]:
        print("warning: agent-reach distribution has no pinned commit in direct_url",
              file=sys.stderr)

    campaign_started = now_utc()
    result = run_campaign(manifest, agent_reach, scratch, rounds,
                          args.timeout, args.max_raw_bytes)
    runs = result["runs"]

    by_case = {row["case_id"]: row for row in result["cases"]}
    per_case_tool = {
        case["case_id"]: {
            tool: dict(by_case[case["case_id"]]["tools"][tool]) for tool in TOOLS
        }
        for case in manifest["cases"]
    }

    # Aggregate per (case, tool, state) as well as globally per tool/state.
    global_rows = {
        tool: {state: _summarize([r for r in runs
                                  if r["tool"] == tool and r["state"] == state])
               for state in STATES}
        for tool in TOOLS
    }

    evidence = {
        "schema": SCHEMA,
        "generated_at": now_utc(),
        "campaign_started_at": campaign_started,
        "campaign_window_utc": {
            "start": campaign_started,
            "end": now_utc(),
            "note": "one window; this is not a multi-day reliability campaign (P2)",
        },
        "manifest": {
            "path": f"docs/evidence/{manifest_path.name}",
            "schema": manifest.get("schema"),
            "frozen_at": manifest.get("frozen_at"),
            "frozen_by": manifest.get("frozen_by"),
            "manifest_sha256": manifest.get(MANIFEST_HASH_FIELD),
            "recomputed_match": verify_manifest(manifest)[0],
            "cases": len(manifest["cases"]),
        },
        "host": host_inventory(),
        "tools": inventory_tools,
        "dependencies": dependency_surface(agent_reach),
        "design": {
            "evaluator_version": EVALUATOR_VERSION,
            "tools_per_invocation": 1,
            "deadline": f"{args.timeout:g}s killable process group, equal for both tools",
            "rounds_per_case_tool_state": rounds,
            "states": list(STATES),
            "cold": "fresh sandbox tree (HOME/HERMES_HOME/XDG/TMPDIR inside scratch)",
            "warm": "second run in the same sandbox tree of that round",
            "interleaving": "trailhead and agent_reach alternate inside every state",
            "sandbox": ("comparative.build_sandbox: environment isolation only, "
                        "not a filesystem sandbox"),
            "asr": "TRAILHEAD_DISABLE_ASR=1 exported and asserted for every child",
            "credentials": "none supplied; env keys validated against an allowlist",
            "raw_payloads": f"kept in scratch, capped at {args.max_raw_bytes} bytes/run",
        },
        "runs": runs,
        "per_case_tool_state": per_case_tool,
        "aggregates": global_rows,
        "totals": {
            "invocations": len(runs),
            "planned_invocations": (len(manifest["cases"]) * len(TOOLS)
                                    * len(STATES) * rounds),
            "by_tool": {
                tool: {
                    "invocations": sum(1 for r in runs if r["tool"] == tool),
                    "ok": sum(1 for r in runs if r["tool"] == tool and r["status"] == "ok"),
                    "timeouts": sum(1 for r in runs if r["tool"] == tool and r["timed_out"]),
                    "paid_calls": 0,
                    "auth_calls": 0,
                    "quota_calls": 0,
                }
                for tool in TOOLS
            },
            "verdicts": _counts(r["verdict"] for r in runs),
            "status": _counts(r["status"] for r in runs),
        },
        "claims": {
            "per_tool_resources": (
                "each row was measured in its own process by a wrapper that "
                "started exactly one child; no combined-tool RSS exists"
            ),
            "artifact_verdicts": (
                "marker presence with truncation and continuation gating; "
                "'markers_present' is not a completeness claim"
            ),
            "winner": "none — this record ranks nothing and names no faster or better tool",
            "completeness": "none",
            "superiority": "not established",
        },
        "limitations": [
            "One host, one UTC window: latency and RSS here describe this host at this moment, not general performance.",
            "3 public cases only; the wider public action surface is not exercised.",
            "Warm means the same sandbox tree on a second immediate run: origin/CDN and tool-internal HTTP caches are not controlled.",
            "Agent Reach stdout carries no truncation or pagination field, so its whole-artifact runs are recorded as truncation unverified and continuation unknown.",
            "Child rusage includes any descendant process the measured tool itself waited for; the wrapper starts exactly one tool process and never a comparator.",
            "Interpreter startup is inside the measured wall clock for both tools; RSS includes each tool's own interpreter.",
            "V2EX node listing is a first page of topics: the case declares pagination 'page', so a first page cannot be recorded as an exhausted artifact.",
            "No multi-day reliability (P2), consent lane, quota/ASR lane, GitHub issue/PR lane or account lifecycle is measured here.",
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"evidence written: {out_path} "
          f"({len(runs)} invocations, manifest {manifest[MANIFEST_HASH_FIELD][:12]}…)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
