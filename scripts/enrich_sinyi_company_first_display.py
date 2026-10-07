"""Enrich the 16-store competitor snapshot with Sinyi's original firstDisplay time.

Uses the same rendered-browser network capture already proven by the canonical
Sinyi monitor. Resolved values are persisted into the shared cache so future
runs do not need to revisit the same listing.
"""

import asyncio
import json
from pathlib import Path

from enrich_sinyi_first_display import fetch_missing, load_json

DATA = Path("docs/company/sinyi-banqiao-stores.json")
CACHE = Path("docs/data/sinyi-first-display-cache.json")
BATCH_SIZE = 120
MAX_PASSES = 2


def apply_cache(rows, cache):
    resolved = 0
    missing = []
    for row in rows:
        hid = str(row.get("houseNo") or "").strip()
        if not hid:
            continue
        if row.get("firstDisplay"):
            resolved += 1
            continue
        hit = cache.get(hid) or {}
        if hit.get("firstDisplay"):
            row["firstDisplay"] = hit.get("firstDisplay")
            row["firstDisplayTimestamp"] = hit.get("timestamp")
            resolved += 1
        else:
            missing.append(hid)
    return resolved, sorted(set(missing))


def main():
    payload = load_json(DATA, {})
    rows = payload.get("listings") or []
    cache = load_json(CACHE, {})
    if not isinstance(cache, dict):
        cache = {}

    _, missing = apply_cache(rows, cache)
    fetched = 0
    errors = []

    for pass_no in range(1, MAX_PASSES + 1):
        if not missing:
            break
        next_missing = []
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start:start + BATCH_SIZE]
            print(
                f"firstDisplay pass={pass_no} batch={start // BATCH_SIZE + 1} "
                f"size={len(batch)} remaining_before={len(missing)}"
            )
            try:
                results = asyncio.run(fetch_missing(batch))
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                errors.append(f"batch {start}: {type(exc).__name__}: {exc}")
                next_missing.extend(batch)
                continue

            for hid, value, error in results:
                if value and value.get("firstDisplay"):
                    cache[str(hid)] = value
                    fetched += 1
                else:
                    next_missing.append(str(hid))
                    if error:
                        errors.append(f"{hid}: {error}")

            # Persist progress after every batch. If a workflow is interrupted,
            # the next run can continue from already resolved IDs.
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        missing = sorted(set(next_missing))
        apply_cache(rows, cache)
        print(f"firstDisplay pass={pass_no} unresolved={len(missing)}")

    resolved, still_missing = apply_cache(rows, cache)

    # Preserve original publish time on recently removed rows too whenever
    # the shared cache already knows it.
    for row in payload.get("recentRemoved") or []:
        hid = str(row.get("houseNo") or "").strip()
        hit = cache.get(hid) or {}
        if not row.get("firstDisplay") and hit.get("firstDisplay"):
            row["firstDisplay"] = hit.get("firstDisplay")
            row["firstDisplayTimestamp"] = hit.get("timestamp")

    payload["firstDisplayMode"] = "playwright_getObjectContent_firstDisplay"
    payload["firstDisplayTotal"] = len(
        {str(x.get("houseNo")) for x in rows if x.get("houseNo")}
    )
    payload["firstDisplayResolved"] = resolved
    payload["firstDisplayFetchedThisRun"] = fetched
    payload["firstDisplayMissing"] = len(still_missing)
    payload["firstDisplayMissingIds"] = still_missing
    payload["firstDisplayErrors"] = errors[-50:]
    payload["firstDisplayComplete"] = not still_missing

    DATA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "total": payload["firstDisplayTotal"],
                "resolved": resolved,
                "fetched": fetched,
                "missing": len(still_missing),
                "complete": payload["firstDisplayComplete"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
