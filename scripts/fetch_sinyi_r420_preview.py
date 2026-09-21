"""Build Preview-only snapshot for Sinyi R420 (板橋中山店).

Uses the same SSR __NEXT_DATA__ technique as the existing Sinyi monitor, but starts
from /publish-desc/1 so every page uses one consistent ordering. The snapshot is
independent from canonical sale/rental monitoring.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

STORE_CODE = "R420"
STORE_NAME = "板橋中山店"
BASE = f"https://www.sinyi.com.tw/buy/list/{STORE_CODE}-{quote(STORE_NAME)}-store"
OUT = Path("docs/preview/r420-store.json")
MAX_PAGES = 20
RECENT_REMOVED_DAYS = 10
WATCH_ROADS = ("中山路二段", "三民路一段", "三民路二段", "翠華街", "林森街", "萬安街", "光復街")
PUQIAN_ROADS = WATCH_ROADS + ("富山街", "懷仁街", "永豐街", "光環路一段", "光環路二段", "太和街", "民享街")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.sinyi.com.tw/",
    }


def parse_region(address):
    text = str(address or "").strip()
    m = re.match(r"^(.{2,3}[縣市])(.+?[區鄉鎮市])", text)
    if m:
        return {
            "city": m.group(1),
            "district": m.group(2),
            "region": f"{m.group(1)}{m.group(2)}",
        }
    return {"city": "", "district": "其他", "region": "其他"}


def fetch_page(page):
    url = f"{BASE}/publish-desc/{page}"
    r = requests.get(url, headers=headers(), timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        raise RuntimeError(f"R420 page {page}: __NEXT_DATA__ missing")
    payload = json.loads(script.string)
    reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
    rows = reducer.get("list") or []
    if not isinstance(rows, list):
        rows = []
    return url, rows, int(reducer.get("totalCnt") or 0)


def listing_row(item):
    hid = str(item.get("houseNo") or "").strip()
    region = parse_region(item.get("address"))
    price = item.get("totalPrice")
    try:
        price = float(price) if price is not None else None
        if price is not None and price.is_integer():
            price = int(price)
    except Exception:
        price = None
    area = item.get("areaBuilding")
    try:
        area = float(area) if area is not None else None
    except Exception:
        area = None
    address = str(item.get("address") or "").strip()
    core_road = next((road for road in WATCH_ROADS if road in address), None)
    puqian_road = next((road for road in PUQIAN_ROADS if road in address), None)
    market_area = (
        "埔墘區"
        if puqian_road
        else "板橋區"
        if region["region"] == "新北市板橋區"
        else "其他行政區"
    )
    return {
        "houseNo": hid,
        "name": str(item.get("name") or "").strip(),
        "address": address,
        "city": region["city"],
        "district": region["district"],
        "region": region["region"],
        "price": price,
        "areaBuilding": area,
        "layout": item.get("layout") or item.get("totalLayout"),
        "floor": item.get("floor"),
        "totalfloor": item.get("totalfloor"),
        "age": item.get("age"),
        "isParking": bool(item.get("isParking")),
        "parking": item.get("parking") or [],
        "community": item.get("commName"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "shareURL": item.get("shareURL"),
        "url": f"https://www.sinyi.com.tw/buy/house/{quote(hid)}?breadcrumb=list",
        "coreRoadMatch": core_road,
        "puqianRoadMatch": puqian_road,
        "marketArea": market_area,
    }


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def main():
    checked_at = now_iso()
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    prev_rows = {str(x.get("houseNo")): x for x in (previous.get("listings") or []) if x.get("houseNo")}
    baseline = not bool(prev_rows)

    current_raw = []
    seen = set()
    total_cnt = None
    pages = []
    for page in range(1, MAX_PAGES + 1):
        url, rows, total = fetch_page(page)
        if total_cnt is None:
            total_cnt = total
        ids = [str(x.get("houseNo") or "").strip() for x in rows if x.get("houseNo")]
        added = 0
        for item in rows:
            hid = str(item.get("houseNo") or "").strip()
            if not hid or hid in seen:
                continue
            seen.add(hid)
            current_raw.append(item)
            added += 1
        pages.append({"page": page, "url": url, "parsed": len(rows), "added": added, "uniqueTotal": len(seen)})
        print(f"R420 Preview page {page}: parsed={len(rows)} added={added} unique={len(seen)} totalCnt={total}")
        if total_cnt and len(seen) >= total_cnt:
            break
        if not rows:
            break

    if not total_cnt:
        raise RuntimeError("R420 totalCnt missing")
    if len(seen) != total_cnt:
        raise RuntimeError(f"R420 incomplete snapshot: expected {total_cnt}, unique {len(seen)}")

    listings = []
    new_ids = []
    price_changes = []
    for item in current_raw:
        row = listing_row(item)
        hid = row["houseNo"]
        old = prev_rows.get(hid)
        row["firstSeenAt"] = (old or {}).get("firstSeenAt") or checked_at
        row["lastSeenAt"] = checked_at
        row["newAt"] = None
        row["priceHistory"] = list((old or {}).get("priceHistory") or [])
        if not row["priceHistory"] and row["price"] is not None:
            row["priceHistory"] = [{"at": row["firstSeenAt"], "price": row["price"]}]

        if old is None and not baseline:
            row["newAt"] = checked_at
            new_ids.append(hid)

        old_price = (old or {}).get("price")
        if old is not None and row["price"] is not None and old_price is not None and float(row["price"]) != float(old_price):
            change = {"houseNo": hid, "from": old_price, "to": row["price"], "at": checked_at}
            row["priceHistory"].append({"at": checked_at, "price": row["price"]})
            row["priceChange"] = change
            price_changes.append(change)
        else:
            row["priceChange"] = None
        listings.append(row)

    current_ids = {x["houseNo"] for x in listings}
    newly_removed = []
    if not baseline:
        for hid, old in prev_rows.items():
            if hid in current_ids:
                continue
            gone = dict(old)
            gone["removedAt"] = checked_at
            gone["active"] = False
            newly_removed.append(gone)

    retained_removed = []
    cutoff_seconds = RECENT_REMOVED_DAYS * 86400
    now_dt = stamp(checked_at)
    for old in (previous.get("recentRemoved") or []):
        hid = str(old.get("houseNo") or "")
        if hid in current_ids:
            continue
        removed_dt = stamp(old.get("removedAt"))
        if now_dt and removed_dt and 0 <= (now_dt - removed_dt).total_seconds() <= cutoff_seconds:
            retained_removed.append(old)
    removed_map = {str(x.get("houseNo")): x for x in retained_removed}
    for row in newly_removed:
        removed_map[row["houseNo"]] = row
    recent_removed = list(removed_map.values())

    by_region = {}
    for row in listings:
        by_region[row["region"]] = by_region.get(row["region"], 0) + 1
    region_summary = [
        {"region": region, "count": count}
        for region, count in sorted(by_region.items(), key=lambda kv: (0 if kv[0] == "新北市板橋區" else 1, -kv[1], kv[0]))
    ]

    area_order = ("埔墘區", "板橋區", "其他行政區")
    area_counts = {name: 0 for name in area_order}
    for row in listings:
        area_counts[row.get("marketArea") or "其他行政區"] = area_counts.get(row.get("marketArea") or "其他行政區", 0) + 1
    area_summary = [{"area": name, "count": area_counts.get(name, 0)} for name in area_order]

    banqiao_count = sum(1 for x in listings if x.get("region") == "新北市板橋區")
    core_count = area_counts.get("埔墘區", 0)
    banqiao_other_count = area_counts.get("板橋區", 0)
    other_area_count = area_counts.get("其他行政區", 0)
    changes = {
        "newCount": len(new_ids),
        "newIds": new_ids,
        "priceChangeCount": len(price_changes),
        "priceChanges": price_changes,
        "removedCount": len(newly_removed),
        "removedIds": [x["houseNo"] for x in newly_removed],
        "currentChangeCount": len(new_ids) + len(price_changes) + len(newly_removed),
    }

    payload = {
        "storeCode": STORE_CODE,
        "storeName": STORE_NAME,
        "source": "信義房屋",
        "sourceUrl": BASE,
        "updatedAt": checked_at,
        "baseline": baseline,
        "baselineAt": previous.get("baselineAt") or checked_at,
        "totalCount": len(listings),
        "sourceTotalCount": total_cnt,
        "banqiaoCount": banqiao_count,
        "coreRoadCount": core_count,
        "puqianCount": core_count,
        "banqiaoOtherCount": banqiao_other_count,
        "otherAreaCount": other_area_count,
        "watchRoads": list(WATCH_ROADS),
        "puqianRoads": list(PUQIAN_ROADS),
        "recentRemovedRetentionDays": RECENT_REMOVED_DAYS,
        "regions": region_summary,
        "areas": area_summary,
        "changes": changes,
        "pages": pages,
        "listings": listings,
        "recentRemoved": recent_removed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "store": f"{STORE_CODE} {STORE_NAME}",
        "total": len(listings),
        "sourceTotal": total_cnt,
        "regions": len(region_summary),
        "banqiao": banqiao_count,
        "puqian": core_count,
        "banqiaoOther": banqiao_other_count,
        "otherArea": other_area_count,
        "baseline": baseline,
        "changes": changes,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
