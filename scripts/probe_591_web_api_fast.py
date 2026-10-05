"""Isolated 591 desktop web API speed/coverage probe.

Pure requests version: no Chrome, Playwright, BeautifulSoup, or canonical mutation.
The endpoint and request shape come from the user-provided Chrome HAR.
"""
import concurrent.futures
import hashlib
import json
import re
import time
from pathlib import Path

import requests

ENDPOINT = "https://bff-house.591.com.tw/v1/web/sale/list"
OUT = Path("artifacts/591-web-api-fast-report.json")
SOURCE = Path("docs/data/listings.json")

ROADS = {
    "板橋區中山路二段": ("27507", ("中山路二段", "中山路2段")),
    "板橋區三民路二段": ("27485", ("三民路二段", "三民路2段")),
    "板橋區光復街": ("27550", ("光復街",)),
    "板橋區萬安街": ("27630", ("萬安街",)),
    "板橋區林森街": ("27574", ("林森街",)),
    "板橋區三民路一段": ("27484", ("三民路一段", "三民路1段")),
    "板橋區翠華街": ("27644", ("翠華街",)),
}

DEVICE_ID = hashlib.md5(b"banqiao-house-monitor-591-web-api").hexdigest()
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def norm(value):
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip().replace("臺", "台")
    return (
        text.replace("中山路2段", "中山路二段")
        .replace("三民路1段", "三民路一段")
        .replace("三民路2段", "三民路二段")
    )


def format_price(value):
    if value in (None, ""):
        return None
    try:
        return f"{float(value):g}萬"
    except Exception:
        return norm(value) or None


def format_area(item):
    value = item.get("area")
    if value not in (None, ""):
        try:
            return f"{float(value):g}坪"
        except Exception:
            pass
    text = norm(item.get("showarea"))
    m = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)", text)
    return f"{m.group(1)}坪" if m else None


def request_page(road, street_id, first_row):
    keyword = road.replace("板橋區", "")
    params = {
        "timestamp": str(int(time.time() * 1000)),
        "type": "2",
        "category": "1",
        "keywords": keyword,
        "regionid": "3",
        "firstRow": str(first_row),
        "shType": "list",
        "streetid": str(street_id),
        "match_type": "3",
    }
    headers = {
        "Accept": "*/*",
        "Origin": "https://sale.591.com.tw",
        "Referer": "https://sale.591.com.tw/",
        "User-Agent": UA,
        "device": "pc",
        "deviceid": DEVICE_ID,
    }
    started = time.perf_counter()
    response = requests.get(ENDPOINT, params=params, headers=headers, timeout=15)
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        raise RuntimeError(f"{road} firstRow={first_row}: HTTP {response.status_code}")
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if payload.get("status") != 1 or not isinstance(data, dict):
        raise RuntimeError(f"{road} firstRow={first_row}: invalid wrapper {str(payload)[:300]}")
    rows = data.get("house_list")
    if not isinstance(rows, list):
        raise RuntimeError(f"{road} firstRow={first_row}: house_list missing")
    return {
        "firstRow": first_row,
        "elapsedSeconds": round(elapsed, 3),
        "total": int(data.get("total") or 0),
        "rows": rows,
    }


def parse_exact(road, aliases, raw_rows):
    out = {}
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        if item.get("is_newhouse") == 1:
            continue
        if norm(item.get("region_name")) not in ("", "新北市"):
            continue
        if norm(item.get("section_name")) not in ("", "板橋區"):
            continue
        address = norm(item.get("street_name") or item.get("address"))
        if not any(norm(alias) in address for alias in aliases):
            continue
        hid = norm(item.get("houseid") or item.get("houseId"))
        if not re.fullmatch(r"\d{6,}", hid):
            continue
        out[f"591:{hid}"] = {
            "id": f"591:{hid}",
            "houseId": hid,
            "road": road,
            "title": norm(item.get("title") or item.get("name")) or f"591案件 {hid}",
            "address": address,
            "price": format_price(item.get("show_price") or item.get("price")),
            "size": format_area(item),
            "postTime": item.get("posttime"),
        }
    return out


def fetch_road(road, street_id, aliases):
    started = time.perf_counter()
    first = request_page(road, street_id, 0)
    total = first["total"]

    # 591 may mix promoted/new-house rows into house_list, so fetch enough offsets
    # to cover the advertised total and one extra page as a completeness guard.
    offsets = list(range(30, total + 30, 30))
    pages = [first]
    if offsets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(offsets))) as ex:
            pages.extend(ex.map(lambda x: request_page(road, street_id, x), offsets))
    pages.sort(key=lambda x: x["firstRow"])

    all_raw = []
    for p in pages:
        all_raw.extend(p["rows"])
    exact = parse_exact(road, aliases, all_raw)

    return {
        "road": road,
        "streetId": street_id,
        "advertisedTotal": total,
        "pageCount": len(pages),
        "rawRows": len(all_raw),
        "exactCount": len(exact),
        "ids": sorted(exact),
        "rows": list(exact.values()),
        "pageTimings": [
            {
                "firstRow": p["firstRow"],
                "seconds": p["elapsedSeconds"],
                "rawCount": len(p["rows"]),
            }
            for p in pages
        ],
        "elapsedSeconds": round(time.perf_counter() - started, 3),
    }


def current_active():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    out = {road: set() for road in ROADS}
    for row in payload.get("listings") or []:
        if row.get("source") != "591" or row.get("active", True) is not True:
            continue
        road = row.get("road")
        rid = row.get("id")
        if road in out and rid:
            out[road].add(str(rid))
    return out, (payload.get("runs") or {}).get("591") or {}


def main():
    known, run = current_active()
    started = time.perf_counter()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        future_map = {
            ex.submit(fetch_road, road, cfg[0], cfg[1]): road
            for road, cfg in ROADS.items()
        }
        for fut in concurrent.futures.as_completed(future_map):
            results.append(fut.result())

    order = list(ROADS)
    results.sort(key=lambda x: order.index(x["road"]))

    api_all = set()
    known_all = set()
    for item in results:
        api_ids = set(item["ids"])
        known_ids = known.get(item["road"], set())
        api_all |= api_ids
        known_all |= known_ids
        item["currentActiveCount"] = len(known_ids)
        item["currentActiveMissingIds"] = sorted(known_ids - api_ids)
        item["freshApiNewVsCurrentIds"] = sorted(api_ids - known_ids)

    report = {
        "mode": "591_desktop_web_api_direct_pure_requests_v2",
        "endpoint": ENDPOINT,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "roadsTested": len(results),
        "apiExactUniqueCount": len(api_all),
        "currentActiveCount": len(known_all),
        "currentActiveMissingCount": len(known_all - api_all),
        "currentActiveMissingIds": sorted(known_all - api_all),
        "freshApiNewVsCurrentCount": len(api_all - known_all),
        "freshApiNewVsCurrentIds": sorted(api_all - known_all),
        "source591CheckedAt": run.get("checkedAt"),
        "source591Message": run.get("message"),
        "roads": results,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "elapsedSeconds": report["elapsedSeconds"],
        "roadsTested": report["roadsTested"],
        "apiExactUniqueCount": report["apiExactUniqueCount"],
        "currentActiveCount": report["currentActiveCount"],
        "currentActiveMissingCount": report["currentActiveMissingCount"],
        "freshApiNewVsCurrentCount": report["freshApiNewVsCurrentCount"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
