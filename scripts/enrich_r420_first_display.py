"""Preview-only firstDisplay enrichment for Sinyi R420 listings.

Reuses the same rendered-browser network capture used by the canonical Sinyi
firstDisplay enrichment, but writes only docs/preview/r420-store.json.
"""

import asyncio
import json
from pathlib import Path

from enrich_sinyi_first_display import fetch_missing, load_json

R420 = Path("docs/preview/r420-store.json")
CACHE = Path("docs/data/sinyi-first-display-cache.json")


def main():
    payload = load_json(R420, {})
    rows = payload.get("listings") or []
    cache = load_json(CACHE, {})
    if not isinstance(cache, dict):
        cache = {}

    by_id = {str(x.get("houseNo")): x for x in rows if x.get("houseNo")}
    missing = []

    for hid, row in by_id.items():
        if row.get("firstDisplay"):
            continue
        hit = cache.get(hid) or {}
        if hit.get("firstDisplay"):
            row["firstDisplay"] = hit.get("firstDisplay")
            row["firstDisplayTimestamp"] = hit.get("timestamp")
        else:
            missing.append(hid)

    fetched = 0
    errors = []
    if missing:
        results = asyncio.run(fetch_missing(sorted(missing)))
        for hid, value, error in results:
            if value:
                row = by_id.get(str(hid))
                if row is not None:
                    row["firstDisplay"] = value.get("firstDisplay")
                    row["firstDisplayTimestamp"] = value.get("timestamp")
                    fetched += 1
            elif error:
                errors.append(f"{hid}: {error}")

    still_missing = [
        hid for hid, row in by_id.items()
        if not row.get("firstDisplay")
    ]
    payload["firstDisplayComplete"] = not still_missing
    payload["firstDisplayFetchedThisRun"] = fetched
    payload["firstDisplayMissingIds"] = sorted(still_missing)
    payload["firstDisplayMode"] = "playwright_getObjectContent_firstDisplay"

    if still_missing:
        raise RuntimeError(
            f"R420 firstDisplay enrichment incomplete: {len(still_missing)} missing: "
            f"{still_missing[:20]} | errors={errors[-10:]}"
        )

    R420.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "total": len(by_id),
        "fetched": fetched,
        "missing": len(still_missing),
        "complete": payload["firstDisplayComplete"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
