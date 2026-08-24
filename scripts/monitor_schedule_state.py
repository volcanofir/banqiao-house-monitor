"""Persist a separate successful full-check timestamp for monitor scheduling.

This keeps the canonical listings.updatedAt tied to actual listing-content changes while
allowing the cheap 10-minute heartbeat to run a full sale+rental refresh only about every
three hours. Failed source checks do not advance the schedule, so the next heartbeat retries.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("state/monitor-schedule.json")
TMP_STATE = Path("/tmp/monitor-schedule.json")
LISTINGS = Path("docs/data/listings.json")
THRESHOLD_MINUTES = 170


def utc_now():
    return datetime.now(timezone.utc)


def parse_stamp(value):
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def gate():
    source = "schedule state"
    stamp = None
    if STATE.exists():
        try:
            payload = json.loads(STATE.read_text(encoding="utf-8"))
            stamp = payload.get("lastSuccessfulFullCheckAt")
        except Exception as exc:
            print(f"schedule state unreadable: {exc}; falling back to listings timestamp")

    if not stamp:
        source = "listings fallback"
        payload = json.loads(LISTINGS.read_text(encoding="utf-8"))
        stamp = payload.get("updatedAt")

    t = parse_stamp(stamp)
    age = (utc_now() - t).total_seconds() / 60
    run = age >= THRESHOLD_MINUTES
    print(
        f"heartbeat full-check age={age:.1f} min; threshold={THRESHOLD_MINUTES}; "
        f"source={source} => {'run' if run else 'skip'}"
    )
    output("run", "true" if run else "false")


def prepare():
    payload = json.loads(LISTINGS.read_text(encoding="utf-8"))
    runs = payload.get("runs") or {}
    statuses = {
        "591": (runs.get("591") or {}).get("status"),
        "信義房屋": (runs.get("信義房屋") or {}).get("status"),
    }
    ok = all(statuses.get(name) == "ok" for name in ("591", "信義房屋"))
    output("success", "true" if ok else "false")
    if not ok:
        print(f"full-check schedule state not advanced; source statuses={statuses}")
        if TMP_STATE.exists():
            TMP_STATE.unlink()
        return

    now = utc_now().isoformat(timespec="seconds")
    state = {
        "lastSuccessfulFullCheckAt": now,
        "cadenceMinutes": THRESHOLD_MINUTES,
        "sourceStatuses": statuses,
        "policy": "advance only after both 591 and Sinyi sale sources complete successfully; rental is dispatched in parallel",
    }
    TMP_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True)


def persist():
    if not TMP_STATE.exists():
        print("No successful full-check state to persist.")
        return

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "fetch", "origin", "main"])
    run(["git", "reset", "--hard", "origin/main"])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TMP_STATE, STATE)
    run(["git", "add", str(STATE)])

    staged = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if staged.returncode == 0:
        print("Monitor schedule state already current.")
        return

    run(["git", "commit", "-m", "Record successful monitor full check"])
    for attempt in range(1, 4):
        push = subprocess.run(["git", "push", "origin", "HEAD:main"])
        if push.returncode == 0:
            print("Successful full-check schedule state persisted.")
            return
        subprocess.run(["git", "rebase", "--abort"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run(["git", "pull", "--rebase", "origin", "main"], check=False)
        time.sleep(3)
    raise RuntimeError("Failed to persist monitor schedule state after 3 attempts")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"gate", "prepare", "persist"}:
        raise SystemExit("usage: monitor_schedule_state.py gate|prepare|persist")
    {"gate": gate, "prepare": prepare, "persist": persist}[sys.argv[1]]()


if __name__ == "__main__":
    main()
