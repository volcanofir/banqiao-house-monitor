"""Build a separate, read-only 591 wareList Preview from verified public list pages.

Writes ONLY docs/591-preview/snapshot.json after a complete seven-road crawl.
Existing docs/data, docs/preview, state, and production UI are never modified.
A failed or partial crawl raises before writing, preserving last good Preview.

Labels reflect identity observations, NOT confirmed new properties or delistings.
"""
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

import dedupe_listings_v2 as dedupe
import track_price_changes as prices
from diagnose_591_warelist_integrity import HOME, ROADS, UA
from diagnose_591_warelist_dryrun_merge import fetch_current

SOURCE = Path("docs/data/listings.json")
OUTPUT = Path("docs/591-preview/snapshot.json")
MAX_RECORDS = 1500


def build_snapshot(current, stats, previous, now=None):
    if set(current) != set(ROADS):
        raise ValueError("Seven-road source set is incomplete")
    if stats["roads_ok"] != len(ROADS):
        raise ValueError("Not every 591 road passed complete-page validation")
    if any(not isinstance(current[road], list) or not current[road] for road in ROADS):
        raise ValueError("Empty or malformed road source; keep previous snapshot")
    if not isinstance(previous, dict) or not isinstance(previous.get("listings"), list):
        raise ValueError("Historical state missing")
    historical = [x for x in previous["listings"] if x.get("source") == "591"]
    if not historical:
        raise ValueError("Empty 591 history; refuse to establish inaccurate baseline")
    history = {str(x["id"]): x for x in dedupe.flatten_591(historical) if x.get("id")}
    parents = [x for x in historical if x.get("active", True)]
    seen = set()
    rows = []
    road_counts = []
    for road in ROADS:
        source_rows = current[road]
        road_counts.append({"road": road.replace("板橋區", ""),
                            "count": len(source_rows)})
        for raw in source_rows:
            item_id = raw.get("id")
            if not item_id or item_id in seen:
                # An ID found on two streets cannot be trusted for road-specific alerts.
                raise ValueError("Duplicate/malformed ID across roads; refusing preview publish")
            seen.add(item_id)
            if raw.get("source") != "591" or raw.get("road") != road:
                raise ValueError("Source or road mismatch")
            if not raw.get("title") or not raw.get("address") or not raw.get("url"):
                raise ValueError("Missing required listing identity/details")
            if raw.get("price") is None or raw.get("size") is None or raw.get("postTime") is None:
                raise ValueError("Incomplete listing fields")
            old = history.get(item_id)
            if old:
                status = "history_inactive_reappeared" if old.get("active") is False else "history_seen"
                match = "same_id"
            else:
                matches = [x for x in parents if prices.same_property(raw, x)]
                match = ("possibly_same_property" if len(matches) == 1
                         else "ambiguous_property" if len(matches) > 1
                         else "no_history_match")
                status = "id_not_in_history"
            old_price = prices.number(old.get("price")) if old else None
            new_price = prices.number(raw.get("price"))
            difference = None
            if old_price is not None and new_price is not None:
                diff = round(new_price - old_price, 1)
                if abs(diff) >= 0.1:
                    difference = diff
            rows.append({
                "id": item_id,
                "houseId": str(raw.get("houseId") or ""),
                "road": road.replace("板橋區", ""),
                "title": str(raw["title"])[:160],
                "address": str(raw["address"])[:180],
                "price": raw["price"],
                "size": raw["size"],
                "postTime": raw["postTime"],
                "url": raw["url"],
                "identityStatus": status,
                "propertyMatch": match,
                "sameIdPriceDifference": difference
            })
    if not rows or len(rows) > MAX_RECORDS:
        raise ValueError("Implausible record count, no data written")

    groups, _, _ = dedupe.dedupe([
        {
            "id": r["id"], "source": "591",
            "houseId": r["houseId"], "road": "板橋區" + r["road"],
            "title": r["title"], "address": r["address"], "price": r["price"],
            "size": r["size"], "postTime": r["postTime"], "url": r["url"],
            "active": True
        } for r in rows
    ])
    counts = Counter(x["identityStatus"] for x in rows)
    matches = Counter(x["propertyMatch"] for x in rows)
    rows.sort(key=lambda x: (-(int(x["postTime"]) if str(x["postTime"]).isdigit() else 0), x["id"]))
    result = {
        "schemaVersion": 1,
        "mode": "preview_only",
        "source": "591_public_warelist_initial_state",
        "updatedAt": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "complete": True,
        "noOffmarketDecision": True,
        "noAutomaticNewPropertyDecision": True,
        "historyReferenceStatus": (previous.get("runs") or {}).get("591", {}).get("status"),
        "counts": {
            "rawSourceRows": stats["raw"],
            "totalListings": len(rows),
            "estimatedPropertyGroups": len(groups),
            "historicalIdSeen": counts["history_seen"],
            "historicallyInactiveReappeared": counts["history_inactive_reappeared"],
            "idNotInHistory": counts["id_not_in_history"],
            "possiblySameProperty": matches["possibly_same_property"],
            "ambiguousProperty": matches["ambiguous_property"],
            "noHistoryMatch": matches["no_history_match"],
            "sameIdPriceDifference": sum(x["sameIdPriceDifference"] is not None for x in rows),
        },
        "roadCounts": road_counts,
        "listings": rows,
    }
    return result


async def capture():
    previous = json.loads(SOURCE.read_text(encoding="utf-8"))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(
                user_agent=UA, viewport={"width": 390, "height": 844},
                is_mobile=True, has_touch=True,
                locale="zh-TW", timezone_id="Asia/Taipei")
            try:
                page = await context.new_page()
                home = await page.goto(HOME, wait_until="domcontentloaded", timeout=25000)
                if not home or home.status != 200:
                    raise RuntimeError("591 public homepage did not return HTTP 200")
                current, stats = await fetch_current(page)
            finally:
                await context.close()
        finally:
            await browser.close()
    return build_snapshot(current, stats, previous)


def main():
    snapshot = asyncio.run(capture())
    # Write only after every record and road has passed validation.
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(OUTPUT)
    print(json.dumps({
        "preview": True,
        "complete": snapshot["complete"],
        "roadCount": len(snapshot["roadCounts"]),
        "listingCount": snapshot["counts"]["totalListings"],
        "historicalIdSeen": snapshot["counts"]["historicalIdSeen"],
        "idNotInHistory": snapshot["counts"]["idNotInHistory"],
        "propertyGroupsEstimated": snapshot["counts"]["estimatedPropertyGroups"],
        "noOffmarketDecision": True,
        "productionAndExistingPreviewUnchanged": True
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
