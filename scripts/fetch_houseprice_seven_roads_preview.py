"""Preview-only 5168 Android-app API monitor for seven Banqiao sale roads.

Uses the public API used by the 5168 Android app (app.houseprice.tw), not the
buy.houseprice.tw HTML pages that reject GitHub runner IPs. No auth secret is stored:
a short-lived anonymous app token is obtained with a deterministic deviceId each run.
"""

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("docs/preview/houseprice-seven-roads.json")
API = "https://app.houseprice.tw"
DEVICE_ID = "banqiao-house-monitor-preview"
RECENT_REMOVED_DAYS = 10
DETAIL_WORKERS = 6

ROADS = (
    "中山路二段",
    "三民路一段",
    "三民路二段",
    "翠華街",
    "林森街",
    "萬安街",
    "光復街",
)

BASE_HEADERS = {
    "User-Agent": "5168/4.0.1 Android",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def find_token(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"token", "accesstoken", "access_token", "authtoken"}:
                if isinstance(item, str) and len(item) > 10:
                    return item
        for item in value.values():
            token = find_token(item)
            if token:
                return token
    elif isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return None


def get_token():
    r = requests.get(
        f"{API}/api/AuthToken",
        params={"deviceId": DEVICE_ID},
        headers=BASE_HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if int(payload.get("code") or 0) != 200:
        raise RuntimeError(f"5168 AuthToken API failed: {payload}")
    token = find_token(payload)
    if not token:
        raise RuntimeError("5168 AuthToken API returned no token")
    return token


def headers(token):
    return {**BASE_HEADERS, "Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_page(token, road, page):
    payload = {
        "city": "新北市",
        "district": ["板橋區"],
        "keyword": road,
        "page": int(page),
    }
    r = requests.post(f"{API}/api/Case/List", headers=headers(token), json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if int(data.get("code") or 0) != 200 or not isinstance(data.get("data"), dict):
        raise RuntimeError(f"5168 Case/List failed road={road} page={page}: {data}")
    body = data["data"]
    rows = body.get("list") or []
    return int(body.get("resultCount") or 0), rows


def fetch_road(token, road):
    total, first = fetch_page(token, road, 1)
    page_size = len(first) or 10
    pages = int(math.ceil(total / page_size)) if total else 0
    rows = []
    seen = set()
    status = []

    for page in range(1, pages + 1):
        if page == 1:
            page_total, items = total, first
        else:
            page_total, items = fetch_page(token, road, page)
        if page_total != total:
            raise RuntimeError(f"5168 {road}: resultCount changed {total} -> {page_total}")
        added = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("caseSid") or "").strip()
            if not sid or sid in seen:
                continue
            # The monitored contract is exact road matching. If the keyword API ever
            # becomes fuzzy, fail rather than silently mixing neighboring roads.
            if str(item.get("city") or "") != "新北市" or str(item.get("district") or "") != "板橋區":
                raise RuntimeError(f"5168 {road}: out-of-area item {sid}: {item.get('city')} {item.get('district')}")
            if str(item.get("road") or "").strip() != road:
                raise RuntimeError(f"5168 {road}: keyword API returned different road {sid}: {item.get('road')}")
            seen.add(sid)
            rows.append(dict(item))
            added += 1
        status.append({"page": page, "returned": len(items), "addedUnique": added})

    if len(rows) != total:
        raise RuntimeError(f"5168 {road}: incomplete pagination source={total}, unique={len(rows)}, pages={status}")
    return {"road": road, "sourceTotal": total, "pageCount": pages, "pageSize": page_size, "pages": status, "listings": rows}


def best_publish_tag(list_row, detail):
    tag = str(list_row.get("publishDaysTag") or "").strip()
    if tag:
        return tag
    for row in detail.get("agent_list") or []:
        if isinstance(row, dict):
            tag = str(row.get("publishDaysTag") or "").strip()
            if tag:
                return tag
    return None


def fetch_detail(token, row):
    sid = str(row.get("caseSid") or "")
    r = requests.get(
        f"{API}/api/Case/Info",
        params={"caseSid": sid},
        headers={k: v for k, v in headers(token).items() if k != "Content-Type"},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if int(payload.get("code") or 0) != 200 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(f"5168 Case/Info failed {sid}: {payload}")
    d = payload["data"]
    if str(d.get("caseSid") or "") != sid:
        raise RuntimeError(f"5168 Case/Info id mismatch {sid} -> {d.get('caseSid')}")
    return d


def normalize_row(list_row, detail, road):
    sid = str(list_row.get("caseSid") or "")
    price = detail.get("totalPrice")
    if price is None:
        price = list_row.get("totalPrice")
    area = detail.get("buildPin")
    if area is None:
        area = list_row.get("buildPin")

    floor = detail.get("floor")
    total_floor = detail.get("totalFloor")
    floor_text = None
    if floor not in (None, "") and total_floor not in (None, ""):
        floor_text = f"{floor}/{total_floor}樓"
    elif floor not in (None, ""):
        floor_text = f"{floor}樓"

    publish_tag = best_publish_tag(list_row, detail)
    return {
        "listingId": sid,
        "groupSid": detail.get("groupSid"),
        "road": road,
        "name": detail.get("caseName") or list_row.get("caseName"),
        "url": detail.get("caseUrl") or list_row.get("caseUrl"),
        "price": price,
        "unitPrice": detail.get("unitPrice"),
        "areaBuilding": area,
        "mainArea": detail.get("mainPin"),
        "attachedArea": detail.get("attachedPin"),
        "publicArea": detail.get("publicPin"),
        "landArea": detail.get("landPin"),
        "floor": floor_text,
        "floorNumber": floor,
        "totalFloor": total_floor,
        "buildingAge": detail.get("buildAge"),
        "caseType": detail.get("caseType"),
        "rooms": detail.get("rm"),
        "livingRooms": detail.get("livingRm"),
        "bathrooms": detail.get("bathRm"),
        "balconies": detail.get("balcony"),
        "hasParkingLot": detail.get("hasParkingLot"),
        "parkingLotType": detail.get("parkingLotType"),
        "parkingLotArea": detail.get("parkingLotPin"),
        "city": detail.get("city") or "新北市",
        "district": detail.get("district") or "板橋區",
        "lng": detail.get("lng"),
        "lat": detail.get("lat"),
        "agentCount": detail.get("agent_count"),
        "sourcePublishText": publish_tag,
        # 5168 app API exposes source-relative labels such as "2天前新上架", not
        # an exact original timestamp. Never substitute our monitor firstSeenAt.
        "sourcePublishedAt": None,
        "sourcePublishedAtType": "housepriceRelativePublishTag" if publish_tag else "housepriceListingDateUnavailable",
        "detailComplete": True,
    }


def main():
    checked_at = now_iso()
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    prev_rows = {
        str(x.get("listingId")): x
        for x in (previous.get("listings") or [])
        if x.get("listingId")
    }
    baseline = not bool(prev_rows)

    token = get_token()
    road_results = [fetch_road(token, road) for road in ROADS]

    raw_by_id = {}
    road_counts = []
    for result in road_results:
        road = result["road"]
        road_counts.append({
            "road": road,
            "count": result["sourceTotal"],
            "pages": result["pageCount"],
        })
        for item in result["listings"]:
            sid = str(item.get("caseSid"))
            if sid not in raw_by_id:
                raw_by_id[sid] = {"list": item, "road": road, "roads": [road]}
            elif road not in raw_by_id[sid]["roads"]:
                raw_by_id[sid]["roads"].append(road)

    normalized = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        futures = {
            pool.submit(fetch_detail, token, rec["list"]): (sid, rec)
            for sid, rec in raw_by_id.items()
        }
        for future in as_completed(futures):
            sid, rec = futures[future]
            try:
                detail = future.result()
                row = normalize_row(rec["list"], detail, rec["road"])
                row["roads"] = rec["roads"]
                normalized[sid] = row
            except Exception as exc:
                failures[sid] = f"{type(exc).__name__}: {exc}"

    if failures:
        raise RuntimeError(f"5168 detail enrichment incomplete: {len(failures)} failures; sample={list(failures.items())[:5]}")
    if len(normalized) != len(raw_by_id):
        raise RuntimeError(f"5168 normalized count mismatch {len(normalized)} != {len(raw_by_id)}")

    listings = []
    new_ids = []
    price_changes = []
    for sid, row in normalized.items():
        old = prev_rows.get(sid)
        row["firstSeenAt"] = (old or {}).get("firstSeenAt") or checked_at
        row["lastSeenAt"] = checked_at
        row["newAt"] = None
        row["active"] = True
        row["priceHistory"] = list((old or {}).get("priceHistory") or [])
        if not row["priceHistory"] and row.get("price") is not None:
            row["priceHistory"] = [{"at": row["firstSeenAt"], "price": row["price"]}]
        if old is None and not baseline:
            row["newAt"] = checked_at
            new_ids.append(sid)
        old_price = (old or {}).get("price")
        if old is not None and old_price is not None and row.get("price") is not None and float(old_price) != float(row["price"]):
            change = {"listingId": sid, "from": old_price, "to": row["price"], "at": checked_at}
            row["priceHistory"].append({"at": checked_at, "price": row["price"]})
            row["priceChange"] = change
            price_changes.append(change)
        else:
            row["priceChange"] = None
        listings.append(row)

    current_ids = set(normalized)
    newly_removed = []
    if not baseline:
        for sid, old in prev_rows.items():
            if sid in current_ids:
                continue
            gone = dict(old)
            gone["active"] = False
            gone["removedAt"] = checked_at
            newly_removed.append(gone)

    retained_removed = []
    now_dt = stamp(checked_at)
    cutoff = RECENT_REMOVED_DAYS * 86400
    for old in previous.get("recentRemoved") or []:
        sid = str(old.get("listingId") or "")
        if sid in current_ids:
            continue
        removed_dt = stamp(old.get("removedAt"))
        if now_dt and removed_dt and 0 <= (now_dt - removed_dt).total_seconds() <= cutoff:
            retained_removed.append(old)
    removed_map = {str(x.get("listingId")): x for x in retained_removed if x.get("listingId")}
    for row in newly_removed:
        removed_map[str(row.get("listingId"))] = row
    recent_removed = list(removed_map.values())

    listings.sort(key=lambda x: (ROADS.index(x["road"]), x.get("name") or ""))
    placement_count = sum(x["count"] for x in road_counts)

    payload = {
        "source": "5168",
        "apiSource": "https://app.houseprice.tw/api/Case/List",
        "updatedAt": checked_at,
        "baseline": baseline,
        "baselineAt": previous.get("baselineAt") or checked_at,
        "roads": list(ROADS),
        "roadCounts": road_counts,
        "placementCount": placement_count,
        "uniqueListingCount": len(listings),
        "detailSummary": {
            "requestedCount": len(raw_by_id),
            "completeCount": len(normalized),
            "failedCount": 0,
            "allComplete": True,
        },
        "sourceTimePolicy": {
            "exactDateExposed": False,
            "relativeTagField": "publishDaysTag",
            "monitorFirstSeenUsedAsSourceTime": False,
        },
        "listings": listings,
        "recentRemoved": recent_removed,
        "changes": {
            "newIds": new_ids,
            "newCount": len(new_ids),
            "removedIds": [str(x.get("listingId")) for x in newly_removed],
            "removedCount": len(newly_removed),
            "priceChanges": price_changes,
            "priceChangeCount": len(price_changes),
        },
        "complete": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "source": "5168",
        "roadCounts": road_counts,
        "placementCount": placement_count,
        "uniqueListingCount": len(listings),
        "detailComplete": len(normalized),
        "baseline": baseline,
        "changes": payload["changes"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
