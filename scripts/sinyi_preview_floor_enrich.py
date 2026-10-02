"""Build the Preview Sinyi floor snapshot from the canonical filterObject API rows.

The main Sinyi monitor now obtains floor/totalfloor/community fields directly from
Sinyi's official filterObject.php response after rendered Chrome obtains short-lived
auth headers. Re-fetching unstable Next.js SSR pages is therefore unnecessary.
"""

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("docs/data/listings.json")
OUT = Path("docs/preview/scheme-a-external-enriched.json")
STATS = Path("docs/preview/sinyi-floor-enrichment.json")
PROBE = Path("docs/preview/591-offmarket-probe.json")


def main():
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    active_sinyi = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") == "信義房屋" and x.get("houseId")
    ]

    enriched = copy.deepcopy(state)
    applied = 0
    with_floor_value = 0
    without_floor_value = []
    missing_api_verified = []

    for item in enriched.get("listings", []):
        if not (item.get("active", True) and item.get("source") == "信義房屋" and item.get("houseId")):
            continue

        hid = str(item.get("houseId"))
        if item.get("sinyiApiSource") != "filterObject.php" or not item.get("sinyiApiVerifiedAt"):
            missing_api_verified.append(hid)

        # New canonical rows already contain structured fields from filterObject.
        fl = item.get("structuredFloor")
        tf = item.get("structuredTotalFloor")
        if fl not in (None, ""):
            item["structuredFloor"] = str(fl)
        if tf not in (None, ""):
            item["structuredTotalFloor"] = str(tf)
        item["floorSourceMode"] = "sinyi_official_filterObject_api"

        if item.get("floor"):
            with_floor_value += 1
        else:
            without_floor_value.append(hid)
        applied += 1

    active_ids = {str(x.get("houseId")) for x in active_sinyi}
    run = (state.get("runs") or {}).get("信義房屋") or {}
    complete = (
        applied == len(active_ids)
        and not missing_api_verified
        and all(
            x.get("floorSourceMode") == "sinyi_official_filterObject_api"
            for x in enriched.get("listings", [])
            if x.get("active", True) and x.get("source") == "信義房屋" and x.get("houseId")
        )
    )

    stats = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "source": "Sinyi official filterObject.php API via runtime browser-issued auth",
        "sourceRunMode": run.get("mode"),
        "sourceRunStatus": run.get("status"),
        "sourceRunCheckedAt": run.get("checkedAt"),
        "activeSinyiCount": len(active_ids),
        "matchedOfficialCount": applied,
        "appliedCount": applied,
        "withStructuredFloorValueCount": with_floor_value,
        "withoutStructuredFloorValueCount": len(without_floor_value),
        "withoutStructuredFloorValueIds": sorted(without_floor_value),
        "missingActiveIds": [],
        "missingApiVerifiedIds": sorted(missing_api_verified),
        "roadStatus": {},
        "complete": complete,
    }
    if not complete:
        raise RuntimeError(f"信義 filterObject API 樓層資料尚未完整轉換: {stats}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preview-only overlay: keep existing 591 stale-listing confirmation behavior.
    if PROBE.exists():
        try:
            subprocess.run([sys.executable, "scripts/apply_preview_591_offmarket_probe.py"], check=True)
        except subprocess.CalledProcessError:
            # A stale probe from an older source snapshot must not invalidate the
            # fresh Sinyi API/floor snapshot. The CLEAN workflow will apply a fresh
            # 591 probe when one exists for the same source timestamp.
            print("略過過期的 591 Preview probe；信義 API/floor snapshot 保持有效。")

    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
