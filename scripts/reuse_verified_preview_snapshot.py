"""Reusable, fail-closed source cache gate for expensive full Preview crawls.

An independent source JSON may replace a duplicate same-day fetch ONLY when:
1. It is complete, from the expected source, and recent enough.
2. Its existing strict seven-road/ID/source-date release validator passes.
This gate never changes data, listing dates, merge rules or off-market status.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "rakuya": {
        "path": Path("docs/preview/rakuya-seven-roads.json"),
        "label": "樂屋網",
        "validator": "scripts/validate_rakuya_preview_snapshot.py",
    },
    "houseprice": {
        "path": Path("docs/preview/houseprice-seven-roads.json"),
        "label": "5168",
        "validator": "scripts/validate_houseprice_preview_snapshot.py",
    },
}
MAX_AGE_MINUTES = 150


def timestamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            return None
        return d.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def recent_snapshot(source, payload, now=None, max_age_minutes=MAX_AGE_MINUTES):
    now = now or datetime.now(timezone.utc)
    settings = SOURCES[source]
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        return False, "missing or incomplete"
    if payload.get("source") != settings["label"]:
        return False, "unexpected source"
    checked = timestamp(payload.get("updatedAt"))
    if not checked:
        return False, "missing/invalid capture time"
    age = (now - checked).total_seconds() / 60
    if age < -5 or age > max_age_minutes:
        return False, f"out of reuse window ({age:.1f} minutes)"
    if not isinstance(payload.get("listings"), list) or not payload["listings"]:
        return False, "empty source rows"
    return True, f"verified freshness window ({age:.1f} minutes)"


def should_reuse(source, now=None, max_age_minutes=MAX_AGE_MINUTES):
    conf = SOURCES[source]
    try:
        payload = json.loads(conf["path"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "missing or malformed JSON"
    ok, reason = recent_snapshot(source, payload, now, max_age_minutes)
    if not ok:
        return False, reason
    # Reuse the same strict validators as independent publication. Do not bypass them.
    proc = subprocess.run([sys.executable, conf["validator"]], capture_output=True, text=True)
    if proc.returncode != 0:
        return False, f"source validator failed: {(proc.stderr or proc.stdout)[-350:]}"
    return True, reason


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=SOURCES)
    parser.add_argument("--max-age-minutes", type=int, default=MAX_AGE_MINUTES)
    args = parser.parse_args()
    if not 1 <= args.max_age_minutes <= 180:
        parser.error("Reuse age must be 1 to 180 minutes")
    ok, reason = should_reuse(args.source, max_age_minutes=args.max_age_minutes)
    print(f"{args.source} independent Preview source cache: reuse={ok}; {reason}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
