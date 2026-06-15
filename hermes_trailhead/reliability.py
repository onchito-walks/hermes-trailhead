"""Hermes Trailhead historical reliability tracker.

Records per-channel health checks over time so the weekly product loop can
answer: which lanes are getting better, worse, or staying the same?
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path.home() / ".hermes" / "state" / "trailhead-reliability.json"


@dataclass
class ReliabilityRecord:
    channel: str
    status: str  # ok, warn, off, fail
    detail: str
    recorded_at: str  # ISO timestamp

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ReliabilityRecord:
        return cls(**d)


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"records": [], "updated_at": ""}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def record_check(
    channel: str,
    status: str,
    detail: str = "",
    *,
    path: Path | None = None,
) -> None:
    """Record a single channel health check result."""
    state_path = path or DEFAULT_STATE_PATH
    data = _load(state_path)

    record = ReliabilityRecord(
        channel=channel,
        status=status,
        detail=detail[:500],
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    data["records"].append(record.to_dict())
    data["updated_at"] = record.recorded_at

    # Keep last 1000 records to avoid unbounded growth
    if len(data["records"]) > 1000:
        data["records"] = data["records"][-1000:]

    _save(state_path, data)


def record_all_checks(
    rows: list[tuple[Any, Any]],
    *,
    path: Path | None = None,
) -> int:
    """Record results from a doctor check_all_live() or check_all() call.

    rows: list of (Channel, CheckResult) tuples from channels.py
    Returns number of records written.
    """
    count = 0
    for ch, res in rows:
        record_check(ch.key, res.status, res.detail, path=path)
        count += 1
    return count


def reliability_summary(
    *,
    path: Path | None = None,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Return per-channel reliability summary with trend signals.

    Returns dict with keys: channels, updated_at, total_records
    Each channel entry: key, recent_status, success_rate, trend, last_checked, details
    """
    state_path = path or DEFAULT_STATE_PATH
    data = _load(state_path)
    records_raw = data.get("records", [])

    if not records_raw:
        return {"channels": {}, "updated_at": "", "total_records": 0}

    # Parse records
    records = [ReliabilityRecord.from_dict(r) for r in records_raw]

    # Filter to lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = [r for r in records if _parse_ts(r.recorded_at) >= cutoff]

    # Group by channel
    by_channel: dict[str, list[ReliabilityRecord]] = {}
    for r in recent:
        by_channel.setdefault(r.channel, []).append(r)

    channels: dict[str, dict] = {}
    for ch_key, ch_records in sorted(by_channel.items()):
        successes = sum(1 for r in ch_records if r.status == "ok")
        total = len(ch_records)
        success_rate = round((successes / total) * 100) if total > 0 else 0

        # Trend: compare first half vs second half
        mid = total // 2
        first_half = ch_records[:mid]
        second_half = ch_records[mid:]
        first_rate = (sum(1 for r in first_half if r.status == "ok") / max(len(first_half), 1)) * 100
        second_rate = (sum(1 for r in second_half if r.status == "ok") / max(len(second_half), 1)) * 100

        if second_rate > first_rate + 10:
            trend = "improving"
        elif second_rate < first_rate - 10:
            trend = "declining"
        else:
            trend = "stable"

        latest = ch_records[-1]
        channels[ch_key] = {
            "key": ch_key,
            "recent_status": latest.status,
            "success_rate": success_rate,
            "trend": trend,
            "last_checked": latest.recorded_at,
            "check_count": total,
            "latest_detail": latest.detail[:200],
        }

    return {
        "channels": channels,
        "updated_at": data.get("updated_at", ""),
        "total_records": len(records_raw),
    }


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
