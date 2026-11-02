"""Retry 591 desktop sale API using the runner's direct egress, not Surfshark.

Only call this after the first 591 attempt failed. A complete and plausible
seven-road snapshot is required before replacing canonical 591 observations.
"""
import asyncio

import monitor_fast
import monitor_pages as core
from monitor_591_web_fallback import fetch_web_sale_fallback


def validate_against_previous(rows, old_state):
    previous = [
        x for x in old_state.get("listings", [])
        if x.get("source") == "591" and x.get("active", True)
    ]
    before = {}
    after = {}
    for row in previous:
        road = row.get("road")
        before[road] = before.get(road, 0) + 1
    for row in rows:
        road = row.get("road")
        after[road] = after.get(road, 0) + 1

    minimum = max(1, int(len(previous) * 0.4))
    missing_roads = [
        road for road, count in before.items()
        if count >= 2 and after.get(road, 0) == 0
    ]
    if len(rows) < minimum or missing_roads:
        return False, (
            f"direct egress rejected partial data: {len(rows)} new, "
            f"{len(previous)} previous, minimum {minimum}, "
            f"missing roads {missing_roads}"
        )
    return True, str(after)


def main():
    state = core.load_state()
    old_run = (state.get("runs") or {}).get("591") or {}
    if old_run.get("status") == "ok":
        print("591 first route already succeeded; direct egress retry unnecessary.")
        return

    rows, ok, msg, diagnostic_logs = asyncio.run(fetch_web_sale_fallback())
    if ok:
        ok, validation_message = validate_against_previous(rows, state)
        diagnostic_logs.append("591 direct egress verification: " + validation_message)

    for line in diagnostic_logs:
        print("591 direct egress:", line)

    if ok:
        checked_at = core.now_iso()
        core.merge_source(
            state, "591", rows, True,
            f"591 GitHub 原始網路出口桌面 API 完整成功 7/7 路段，共 {len(rows)} 筆。",
            diagnostic_logs,
            checked_at,
        )
        monitor_fast.save_state(state, checked_at)
        print(f"591 direct egress successfully published {len(rows)} verified listings.")
    else:
        # Retain the Surfshark error and previous 591 listings; add the diagnosis.
        old_run["logs"] = list(old_run.get("logs") or []) + diagnostic_logs
        old_run["message"] = (
            str(old_run.get("message") or "591 更新失敗") +
            "；GitHub 原始網路出口桌面 API 亦未取得完整資料。"
        )
        state.setdefault("runs", {})["591"] = old_run
        monitor_fast.save_state(state, core.now_iso())
        print("591 direct egress failed; canonical listings were preserved.")


if __name__ == "__main__":
    main()
