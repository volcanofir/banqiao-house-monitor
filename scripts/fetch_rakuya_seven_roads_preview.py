"""Preview-only Rakuya monitor for seven Banqiao sale roads.

Fetches all pages for each watched road from Rakuya public sale search, validates the
source-reported totals, and tracks new / removed / price-changed listings. It writes
only docs/preview/rakuya-seven-roads.json.
"""

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("docs/preview/rakuya-seven-roads.json")
RECENT_REMOVED_DAYS = 10
MAX_WORKERS = 4

ROADS = (
    "中山路二段",
    "三民路一段",
    "三民路二段",
    "翠華街",
    "林森街",
    "萬安街",
    "光復街",
)

BASE = "https://www.rakuya.com.tw/sell/result"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def search_url(road, page):
    return (
        f"{BASE}?zipcode=220&search=route&landmark={quote(road)}"
        f"&sort=11&page={int(page)}"
    )


def parse_sell_search(soup):
    for script in soup.find_all("script"):
        body = script.string or script.get_text() or ""
        if "window.sellSearch" not in body:
            continue
        m = re.search(r"window\.sellSearch\s*=\s*(\{.*?\});", body, re.S)
        if not m:
            continue
        return json.loads(m.group(1))
    raise RuntimeError("window.sellSearch metadata missing")


def parse_item_list(soup):
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        body = script.string or script.get_text() or ""
        if not body.strip():
            continue
        try:
            payload = json.loads(body)
        except Exception:
            continue
        nodes = []
        if isinstance(payload, dict):
            nodes = payload.get("@graph") or [payload]
        elif isinstance(payload, list):
            nodes = payload
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "ItemList":
                rows = node.get("itemListElement") or []
                return rows if isinstance(rows, list) else []
    raise RuntimeError("Rakuya JSON-LD ItemList missing")


def clean_url(url):
    if not url:
        return None
    return re.sub(r"([?&])from=[^&]+&?", lambda m: "?" if m.group(1) == "?" else "", str(url)).rstrip("?&")


def listing_id(url):
    try:
        q = parse_qs(urlparse(str(url)).query)
        ehid = (q.get("ehid") or [None])[0]
        if ehid:
            return str(ehid)
    except Exception:
        pass
    return str(url or "")


def card_text_for_id(soup, hid):
    if not hid:
        return ""
    for a in soup.find_all("a", href=True):
        if f"ehid={hid}" not in str(a.get("href") or ""):
            continue
        text = " ".join(a.stripped_strings)
        if len(text) >= 20:
            return text
    return ""


def number_from(pattern, text):
    m = re.search(pattern, text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def text_from(pattern, text):
    m = re.search(pattern, text or "")
    return m.group(1).strip() if m else None


def parse_product(entry, soup, road):
    product = entry.get("item") if isinstance(entry, dict) else None
    if not isinstance(product, dict):
        return None

    url = clean_url(product.get("url"))
    hid = listing_id(url)
    if not hid:
        return None

    offers = product.get("offers") or {}
    offered = offers.get("itemOffered") or {}
    floor_size = offered.get("floorSize") or {}
    addr = offered.get("address") or {}
    card = card_text_for_id(soup, hid)

    price_twd = offers.get("price")
    price_wan = None
    try:
        price_wan = round(float(price_twd) / 10000, 2)
        if float(price_wan).is_integer():
            price_wan = int(price_wan)
    except Exception:
        price_wan = None

    area = floor_size.get("value")
    try:
        area = float(area) if area is not None else None
        if area is not None and area.is_integer():
            area = int(area)
    except Exception:
        area = None

    bedrooms = offered.get("numberOfBedrooms")
    bathrooms = offered.get("numberOfBathroomsTotal")
    layout = None
    if bedrooms is not None or bathrooms is not None:
        bits = []
        if bedrooms is not None:
            bits.append(f"{bedrooms}房")
        if bathrooms is not None:
            bits.append(f"{bathrooms}衛")
        layout = "".join(bits)

    return {
        "listingId": hid,
        "road": road,
        "name": str(product.get("name") or "").strip(),
        "url": url,
        "price": price_wan,
        "areaBuilding": area,
        "layout": layout,
        "floor": text_from(r"((?:B?\d+(?:-\d+)?|B\d+)\/\d+樓)", card),
        "age": text_from(r"(\d+(?:\.\d+)?年|不詳)", card),
        "mainArea": number_from(r"主建\s*([\d.]+)坪", card),
        "unitPrice": number_from(r"([\d.]+)萬\/坪", card),
        "sourceUpdateText": text_from(r"(\d+(?:分鐘|小時|天|個月)前更新)", card),
        "sourceNewLabel": "新上架" in card,
        "addressRegion": str(addr.get("addressRegion") or "板橋區"),
        "addressLocality": str(addr.get("addressLocality") or "新北市"),
        "sourceCardText": card,
    }


def fetch_road(road):
    session = requests.Session()
    first_url = search_url(road, 1)
    r = session.get(first_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    meta = parse_sell_search(soup)
    pagination = meta.get("pagination") or {}
    total = int(pagination.get("total") or 0)
    page_count = int(pagination.get("pageCount") or 0)
    page_size = int(pagination.get("pageSize") or 0)

    if total < 0 or page_count < 0:
        raise RuntimeError(f"{road}: invalid pagination {pagination}")
    expected_pages = math.ceil(total / page_size) if total and page_size else page_count
    if expected_pages and page_count != expected_pages:
        raise RuntimeError(
            f"{road}: pageCount mismatch source={page_count} calculated={expected_pages}"
        )

    pages = []
    rows = []
    seen = set()

    for page in range(1, page_count + 1):
        if page == 1:
            page_soup = soup
            page_url = r.url
        else:
            page_url = search_url(road, page)
            rr = session.get(page_url, headers=HEADERS, timeout=30)
            rr.raise_for_status()
            page_soup = BeautifulSoup(rr.text, "html.parser")
            page_meta = parse_sell_search(page_soup)
            p = page_meta.get("pagination") or {}
            if int(p.get("currentPage") or 0) != page:
                raise RuntimeError(f"{road}: requested page {page}, got pagination {p}")
            if int(p.get("total") or -1) != total:
                raise RuntimeError(f"{road}: total changed during crawl {total} -> {p.get('total')}")

        entries = parse_item_list(page_soup)
        parsed = 0
        for entry in entries:
            row = parse_product(entry, page_soup, road)
            if not row:
                continue
            hid = row["listingId"]
            if hid in seen:
                continue
            seen.add(hid)
            rows.append(row)
            parsed += 1
        pages.append({
            "page": page,
            "url": page_url,
            "sourceItems": len(entries),
            "addedUnique": parsed,
            "uniqueTotal": len(seen),
        })

    if len(rows) != total:
        raise RuntimeError(
            f"{road}: incomplete crawl, source total={total}, unique parsed={len(rows)}, pages={pages}"
        )

    return {
        "road": road,
        "sourceTotal": total,
        "pageCount": page_count,
        "pageSize": page_size,
        "pages": pages,
        "listings": rows,
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

    prev_rows = {
        str(x.get("listingId")): x
        for x in (previous.get("listings") or [])
        if x.get("listingId")
    }
    baseline = not bool(prev_rows)

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_road, road): road for road in ROADS}
        for future in as_completed(futures):
            road = futures[future]
            results[road] = future.result()

    current_by_id = {}
    road_counts = []
    for road in ROADS:
        result = results[road]
        road_counts.append({
            "road": road,
            "count": result["sourceTotal"],
            "pages": result["pageCount"],
        })
        for row in result["listings"]:
            hid = row["listingId"]
            if hid not in current_by_id:
                current_by_id[hid] = row
                current_by_id[hid]["roads"] = [road]
            elif road not in current_by_id[hid]["roads"]:
                current_by_id[hid]["roads"].append(road)

    listings = []
    new_ids = []
    price_changes = []
    for hid, row in current_by_id.items():
        old = prev_rows.get(hid)
        row["firstSeenAt"] = (old or {}).get("firstSeenAt") or checked_at
        row["lastSeenAt"] = checked_at
        row["newAt"] = None
        row["priceHistory"] = list((old or {}).get("priceHistory") or [])
        if not row["priceHistory"] and row.get("price") is not None:
            row["priceHistory"] = [{"at": row["firstSeenAt"], "price": row["price"]}]

        if old is None and not baseline:
            row["newAt"] = checked_at
            new_ids.append(hid)

        old_price = (old or {}).get("price")
        if old is not None and row.get("price") is not None and old_price is not None and float(row["price"]) != float(old_price):
            change = {"listingId": hid, "from": old_price, "to": row["price"], "at": checked_at}
            row["priceHistory"].append({"at": checked_at, "price": row["price"]})
            row["priceChange"] = change
            price_changes.append(change)
        else:
            row["priceChange"] = None
        listings.append(row)

    current_ids = set(current_by_id)
    newly_removed = []
    if not baseline:
        for hid, old in prev_rows.items():
            if hid in current_ids:
                continue
            gone = dict(old)
            gone["active"] = False
            gone["removedAt"] = checked_at
            newly_removed.append(gone)

    retained_removed = []
    now_dt = stamp(checked_at)
    cutoff_seconds = RECENT_REMOVED_DAYS * 86400
    for old in (previous.get("recentRemoved") or []):
        hid = str(old.get("listingId") or "")
        if hid in current_ids:
            continue
        removed_dt = stamp(old.get("removedAt"))
        if now_dt and removed_dt and 0 <= (now_dt - removed_dt).total_seconds() <= cutoff_seconds:
            retained_removed.append(old)

    removed_map = {str(x.get("listingId")): x for x in retained_removed if x.get("listingId")}
    for row in newly_removed:
        removed_map[str(row["listingId"])] = row
    recent_removed = list(removed_map.values())

    listings.sort(key=lambda x: (ROADS.index(x["road"]) if x.get("road") in ROADS else 999, x.get("name") or ""))

    placement_count = sum(x["count"] for x in road_counts)
    payload = {
        "source": "樂屋網",
        "updatedAt": checked_at,
        "baseline": baseline,
        "baselineAt": previous.get("baselineAt") or checked_at,
        "roads": list(ROADS),
        "roadCounts": road_counts,
        "placementCount": placement_count,
        "uniqueListingCount": len(listings),
        "overlapCount": max(0, placement_count - len(listings)),
        "recentRemovedRetentionDays": RECENT_REMOVED_DAYS,
        "complete": True,
        "changes": {
            "newCount": len(new_ids),
            "newIds": sorted(new_ids),
            "priceChangeCount": len(price_changes),
            "priceChanges": price_changes,
            "removedCount": len(newly_removed),
            "removedIds": sorted(str(x.get("listingId")) for x in newly_removed if x.get("listingId")),
            "currentChangeCount": len(new_ids) + len(price_changes) + len(newly_removed),
        },
        "listings": listings,
        "recentRemoved": recent_removed,
        "roadDiagnostics": {road: results[road]["pages"] for road in ROADS},
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "complete": True,
        "roads": road_counts,
        "placementCount": placement_count,
        "uniqueListingCount": len(listings),
        "overlapCount": payload["overlapCount"],
        "baseline": baseline,
        "changes": payload["changes"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
