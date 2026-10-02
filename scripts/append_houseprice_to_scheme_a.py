"""Append Preview-only 5168 seven-road listings into Scheme A external snapshot.

Runs after Rakuya append. Production docs/data/listings.json is never modified.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEME = Path("docs/preview/scheme-a-external-enriched.json")
SOURCE = Path("docs/preview/houseprice-seven-roads.json")


def parse_dt(value):
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def mapped(row, active=True):
    sid=str(row.get("listingId") or "").strip()
    road=str(row.get("road") or "").strip()
    full_road=road if road.startswith("板橋區") else ("板橋區"+road if road else "")
    price=row.get("price")
    area=row.get("areaBuilding")
    return {
        "id": f"5168:{sid}",
        "houseId": sid,
        "source": "5168",
        "road": full_road,
        "title": row.get("name"),
        "address": f"新北市{full_road}" if full_road else "新北市板橋區",
        "url": row.get("url"),
        "price": None if price is None else f"{price}萬",
        "effectivePrice": price,
        "size": None if area is None else f"{area}坪",
        "area": area,
        "floor": row.get("floor"),
        "sourcePublishedAt": None,
        "sourcePublishedAtType": row.get("sourcePublishedAtType") or "housepriceListingDateUnavailable",
        "monitorFirstSeenAt": row.get("firstSeenAt"),
        "housepricePublishDaysTag": row.get("sourcePublishText"),
        "housepriceGroupSid": row.get("groupSid"),
        "housepriceUnitPrice": row.get("unitPrice"),
        "housepriceMainArea": row.get("mainArea"),
        "housepriceBuildingAge": row.get("buildingAge"),
        "housepriceCaseType": row.get("caseType"),
        "housepriceAgentCount": row.get("agentCount"),
        "newAt": row.get("newAt"),
        "active": bool(active),
        "removedAt": row.get("removedAt") if not active else None,
        "priceHistory": row.get("priceHistory") or [],
    }


def main():
    state=json.loads(SCHEME.read_text(encoding="utf-8"))
    hp=json.loads(SOURCE.read_text(encoding="utf-8"))
    if hp.get("complete") is not True:
        raise RuntimeError("5168 seven-road snapshot incomplete")
    if len(hp.get("roads") or []) != 7:
        raise RuntimeError(f"5168 road count mismatch: {hp.get('roads')}")
    updated=parse_dt(hp.get("updatedAt"))
    if updated is None:
        raise RuntimeError("5168 updatedAt missing")
    age_hours=(datetime.now(timezone.utc)-updated).total_seconds()/3600
    if age_hours < -0.25 or age_hours > 8:
        raise RuntimeError(f"5168 snapshot stale: ageHours={age_hours:.2f}")

    rows=[x for x in state.get("listings",[]) if x.get("source")!="5168"]
    active=[mapped(x,True) for x in (hp.get("listings") or [])]
    removed=[mapped(x,False) for x in (hp.get("recentRemoved") or [])]
    ids=[x.get("id") for x in active]
    if len(ids)!=len(set(ids)):
        raise RuntimeError("5168 active IDs are not unique")

    rows.extend(active)
    rows.extend(removed)
    state["listings"]=rows
    state.setdefault("previewSources",{})["5168"]={
        "updatedAt": hp.get("updatedAt"),
        "status": "ok",
        "totalCount": int(hp.get("placementCount") or 0),
        "uniqueListingCount": int(hp.get("uniqueListingCount") or len(active)),
        "roadCounts": hp.get("roadCounts") or [],
        "changes": hp.get("changes") or {},
        "detailSummary": hp.get("detailSummary") or {},
        "sourceTimePolicy": hp.get("sourceTimePolicy") or {},
        "complete": True,
    }
    SCHEME.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "housepriceActive":len(active),
        "housepriceRecentRemoved":len(removed),
        "placementCount":hp.get("placementCount"),
        "snapshotAgeHours":round(age_hours,2),
    },ensure_ascii=False))


if __name__=="__main__":
    main()
