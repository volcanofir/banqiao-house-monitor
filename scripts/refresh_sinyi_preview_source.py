"""Independent, verified Sinyi source feed for the existing Preview status cards.

Does not modify docs/data, the Preview group comparison, or any delisting data.
Only a complete seven-road API read is published. Failed reads leave the last
successful source JSON untouched.
"""
import json
import os
from pathlib import Path

import monitor_pages as core
from monitor_sinyi_parallel import fetch_sinyi_api

OUT = Path("docs/preview/sinyi-source.json")


def build(checked_at, rows):
    roads = list(core.WATCH_ROADS)
    if not rows:
        raise ValueError("Empty Sinyi source; preserve previous verified snapshot")
    ids = [str(x.get("id") or "") for x in rows]
    if any(not i.startswith("信義房屋:") for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Sinyi missing/duplicate advertisement ID")
    if any(x.get("source") != "信義房屋" or x.get("road") not in roads or not x.get("sinyiApiVerifiedAt") for x in rows):
        raise ValueError("Sinyi invalid source/road/API verification")
    counts = [{"road": road, "count": sum(x["road"] == road for x in rows)} for road in roads]
    if sum(x["count"] for x in counts) != len(rows):
        raise ValueError("Sinyi seven-road coverage mismatch")
    return {
        "source": "信義房屋",
        "previewOnly": True,
        "complete": True,
        "updatedAt": checked_at,
        "noOffmarketDecision": True,
        "noAutomaticNewPropertyDecision": True,
        "roadCounts": counts,
        "uniqueListingCount": len(rows),
        "runs": {"信義房屋": {"status": "ok", "checkedAt": checked_at, "totalCount": len(rows)}},
        "listings": rows,
    }


def main():
    checked_at = core.now_iso()
    rows, ok, message, logs = fetch_sinyi_api(checked_at)
    for line in logs:
        print("Sinyi:", line)
    if not ok:
        raise RuntimeError(message)
    payload = build(checked_at, rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"Independent Sinyi Preview source verified: {len(rows)} IDs; no delisting changes")


if __name__ == "__main__":
    main()
