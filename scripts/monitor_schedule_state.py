"""Run approximately one full check per three hours, regardless of source outages.

The attempt clock prevents a blocked source (e.g. 591 returning 403) from
turning the ten-minute heartbeat into a ten-minute full scrape.  The separate
lastSuccessfulFullCheckAt field only advances after a verified, published run.
This module changes scheduling metadata only; it never changes listings or Preview.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("state/monitor-schedule.json")
TMP_STATE = Path("/tmp/monitor-schedule-attempt.json")
LISTINGS = Path("docs/data/listings.json")
THRESHOLD_MINUTES = 180


def utc_now():
    return datetime.now(timezone.utc)


def parse_stamp(value):
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def gate():
    state = read_json(STATE)
    stamp = state.get("lastFullCheckAttemptAt")
    source = "last full-check attempt"
    if not stamp:
        stamp = state.get("lastSuccessfulFullCheckAt")
        source = "legacy last successful check"
    if not stamp:
        stamp = read_json(LISTINGS).get("updatedAt")
        source = "listings fallback"
    if not stamp:
        raise ValueError("No timestamp available for safe scheduling")
    age = (utc_now() - parse_stamp(stamp)).total_seconds() / 60
    run = age >= THRESHOLD_MINUTES
    print(
        f"heartbeat attempt age={age:.1f} min; threshold={THRESHOLD_MINUTES}; "
        f"source={source} => {'run' if run else 'skip'}"
    )
    output("run", "true" if run else "false")


def begin():
    attempt = {
        "lastFullCheckAttemptAt": utc_now().isoformat(timespec="seconds"),
        "lastAttemptSourceStatuses": {},
    }
    TMP_STATE.write_text(
        json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Full-check attempt started; production and Preview are unchanged.")


def prepare():
    if not TMP_STATE.exists():
        raise RuntimeError("Missing attempt marker; refusing to record a check")
    runs = read_json(LISTINGS).get("runs") or {}
    statuses = {
        "591": (runs.get("591") or {}).get("status"),
        "信義房屋": (runs.get("信義房屋") or {}).get("status"),
    }
    ok = all(statuses.get(source) == "ok" for source in statuses)
    attempt = read_json(TMP_STATE)
    attempt["lastAttemptSourceStatuses"] = statuses
    TMP_STATE.write_text(
        json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output("success", "true" if ok else "false")
    print(f"Source check finished: statuses={statuses}; both_sources_ok={ok}")


def merge_attempt(latest, attempt, verified):
    """Pure state merge: incomplete runs can never advance successful-check time."""
    stamp = attempt.get("lastFullCheckAttemptAt")
    if not stamp:
        raise ValueError("Attempt timestamp missing")
    new_time = parse_stamp(stamp)
    previous = latest.get("lastFullCheckAttemptAt")
    if previous and parse_stamp(previous) > new_time:
        print("A newer attempt is already saved; refusing to regress schedule.")
        return dict(latest)
    out = dict(latest)
    out["lastFullCheckAttemptAt"] = stamp
    out["cadenceMinutes"] = THRESHOLD_MINUTES
    statuses = attempt.get("lastAttemptSourceStatuses") or {}
    out["lastAttemptSourceStatuses"] = statuses
    out["lastAttemptOutcome"] = "verified" if verified else "incomplete"
    if verified:
        if statuses.get("591") != "ok" or statuses.get("信義房屋") != "ok":
            raise ValueError("Cannot mark successful check without both sources")
        out["lastSuccessfulFullCheckAt"] = stamp
        out["sourceStatuses"] = statuses
    out["policy"] = (
        "one full-check attempt about every 180 minutes, even when a source fails; "
        "success advances only after both sources and publication validate"
    )
    return out


def verified_by_workflow():
    """Require source completeness and downstream validation/publish success."""
    source_ok = os.environ.get("SOURCE_OK") == "true"
    job_ok = os.environ.get("WORKFLOW_STATUS") == "success"
    changes = os.environ.get("LISTINGS_CHANGED")
    publish = os.environ.get("PUBLISH_OUTCOME")
    output_ok = changes == "false" or (changes == "true" and publish == "success")
    return source_ok and job_ok and output_ok


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True)


def persist():
    if not TMP_STATE.exists():
        raise RuntimeError("Missing attempt marker; no scheduling metadata written")
    attempt = read_json(TMP_STATE)
    verified = verified_by_workflow()
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    for retry in range(1, 4):
        run(["git", "fetch", "origin", "main"])
        run(["git", "reset", "--hard", "origin/main"])
        latest = read_json(STATE)
        next_state = merge_attempt(latest, attempt, verified)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(
            json.dumps(next_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        run(["git", "add", str(STATE)])
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            print("Schedule already current; no changes to commit.")
            return
        run(["git", "commit", "-m", "Record monitor attempt cadence and validated outcome"])
        if subprocess.run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            print(f"Schedule saved; attempt verified={verified}; no listing data changed.")
            return
        print(f"Schedule push conflict, retry {retry}/3")
        time.sleep(3)
    raise RuntimeError("Unable to persist full-check attempt after three retries")


def main():
    choices = {"gate": gate, "begin": begin, "prepare": prepare, "persist": persist}
    if len(sys.argv) != 2 or sys.argv[1] not in choices:
        raise SystemExit("usage: monitor_schedule_state.py gate|begin|prepare|persist")
    choices[sys.argv[1]]()


if __name__ == "__main__":
    main()
