"""Append Preview-only Rakuya seven-road listings into Scheme A external snapshot.

Reads docs/preview/rakuya-seven-roads.json and docs/preview/scheme-a-external-enriched.json.
Production monitor data is never modified.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEME = Path("docs/preview/scheme-a-external-enriched.json")
RAKUYA = Path("docs/preview/rakuya-seven-roads.json")

def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def mapped(row, active=True):
    hid = str(row.get("listingId") or "").strip()
    road = str(row.get("road") or "").strip()
    if road and not road.startswith("板橋區"):
        road = "板橋區" + road
    price = row.get("price")
    area = row.get("areaBuilding")
    return {
        "id": f"樂屋:{hid}",
        "houseId": hid,
        "source": "樂屋網",
        "road": road,
        "title": row.get("name"),
        "address": f"新北市{road}" if road else "新北市板橋區",
        "url": row.get("url"),
        "price": None if price is None else f"{price}萬",
        "effectivePrice": price,
        "size": None if area is None else f"{area}坪",
        "area": area,
        "floor": row.get("floor"),
        "sourcePublishedAt": row.get("firstSeenAt"),
        "sourcePublishedAtType": "monitorFirstSeen",
        "newAt": row.get("newAt"),
        "active": bool(active),
        "removedAt": row.get("removedAt") if not active else None,
        "priceHistory": row.get("priceHistory") or [],
        "rakuyaSourceUpdateText": row.get("sourceUpdateText"),
        "rakuyaSourceNewLabel": row.get("sourceNewLabel"),
        "rakuyaMainArea": row.get("mainArea"),
        "rakuyaUnitPrice": row.get("unitPrice"),
    }

def main():
    state = json.loads(SCHEME.read_text(encoding="utf-8"))
    rakuya = json.loads(RAKUYA.read_text(encoding="utf-8"))

    if rakuya.get("complete") is not True:
        raise RuntimeError("Rakuya seven-road snapshot incomplete")
    if len(rakuya.get("roads") or []) != 7:
        raise RuntimeError(f"Rakuya road count mismatch: {rakuya.get('roads')}")

    updated = parse_dt(rakuya.get("updatedAt"))
    if updated is None:
        raise RuntimeError("Rakuya updatedAt missing")
    age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
    if age_hours < -0.25 or age_hours > 8:
        raise RuntimeError(f"Rakuya snapshot stale: ageHours={age_hours:.2f}")

    rows = [x for x in state.get("listings", []) if x.get("source") != "樂屋網"]
    active = [mapped(x, True) for x in (rakuya.get("listings") or [])]
    removed = [mapped(x, False) for x in (rakuya.get("recentRemoved") or [])]

    ids = [x.get("id") for x in active]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Rakuya active IDs are not unique")

    rows.extend(active)
    rows.extend(removed)
    state["listings"] = rows
    state.setdefault("previewSources", {})["樂屋網"] = {
        "updatedAt": rakuya.get("updatedAt"),
        "status": "ok",
        "totalCount": int(rakuya.get("placementCount") or 0),
        "uniqueListingCount": int(rakuya.get("uniqueListingCount") or len(active)),
        "roadCounts": rakuya.get("roadCounts") or [],
        "changes": rakuya.get("changes") or {},
        "complete": True,
    }

    SCHEME.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "rakuyaActive": len(active),
        "rakuyaRecentRemoved": len(removed),
        "placementCount": rakuya.get("placementCount"),
        "snapshotAgeHours": round(age_hours, 2),
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
