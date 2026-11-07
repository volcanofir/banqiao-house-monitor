"""Throttle independent Preview source refreshes by successful source age and failed attempts.

Three-hour normal cadence; once stale, failed source attempts retry after 30 minutes.
Neither the scheduler nor a missing ID decides that any property is off-market.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("docs")
SOURCES = {
    "591": ("591-preview/snapshot.json", "591-warelist-preview.yml"),
    "sinyi": ("preview/sinyi-source.json", "preview-source-refresh.yml"),
    "rakuya": ("preview/rakuya-seven-roads.json", "preview-source-refresh.yml"),
    "houseprice": ("preview/houseprice-seven-roads.json", "preview-source-refresh.yml"),
}
NORMAL_MINUTES = 180
FAILED_RETRY_MINUTES = 30
ACTIVE = {"queued", "in_progress", "pending", "waiting", "requested"}


def timestamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def last_run_for(source, runs):
    matches = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if source != "591" and run.get("displayTitle") != "preview-source:" + source:
            continue
        when = timestamp(run.get("createdAt"))
        if when:
            matches.append((when, run))
    return max(matches, key=lambda pair: pair[0])[1] if matches else None


def decision(source, snapshot, runs, now=None):
    if source not in SOURCES:
        raise ValueError("Unsupported source")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    snap_ok = isinstance(snapshot, dict) and snapshot.get("complete") is True
    if source == "591":
        snap_ok = snap_ok and snapshot.get("source") == "591_public_warelist_initial_state"
    elif source == "sinyi":
        snap_ok = snap_ok and snapshot.get("source") == "信義房屋" and (snapshot.get("runs") or {}).get("信義房屋", {}).get("status") == "ok"
    elif source == "rakuya":
        snap_ok = snap_ok and snapshot.get("source") == "樂屋網"
    else:
        snap_ok = snap_ok and snapshot.get("source") == "5168"

    last_success = timestamp(snapshot.get("updatedAt")) if snap_ok else None
    success_age = (now - last_success).total_seconds() / 60 if last_success else None
    # A valid, recent independent source snapshot is enough; never scrape on
    # every ten-minute heartbeat merely because an unrelated workflow failed.
    if success_age is not None and -5 <= success_age < NORMAL_MINUTES:
        return False, "verified snapshot still fresh"

    run = last_run_for(source, runs)
    if run:
        if str(run.get("status") or "").lower() in ACTIVE:
            return False, "previous refresh still running"
        age = (now - timestamp(run["createdAt"])).total_seconds() / 60
        if age < -5:
            return False, "future timestamp"
        if age < 0:
            age = 0
        cooldown = NORMAL_MINUTES if str(run.get("conclusion") or "").lower() == "success" else FAILED_RETRY_MINUTES
        if age < cooldown:
            return False, f"attempt cooldown {cooldown} minutes ({age:.1f} elapsed)"
    return True, "source stale or missing; independent attempt permitted"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=SOURCES)
    args = parser.parse_args()
    path = ROOT / SOURCES[args.source][0]
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    try:
        runs = json.loads(os.environ["PREVIEW_SOURCE_RUNS"])
        if not isinstance(runs, list):
            raise ValueError("Not a list")
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"Fail closed; cannot inspect prior attempts: {exc}")
    due, reason = decision(args.source, snapshot, runs)
    print(f"{args.source}: due={due}; {reason}")
    raise SystemExit(0 if due else 1)


if __name__ == "__main__":
    main()
