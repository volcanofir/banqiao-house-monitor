"""Isolated 591 desktop web API speed/coverage probe.

Uses the current public BFF observed in a user-provided Chrome HAR:
  /v1/web/sale/list
No canonical data is mutated. The probe compares the fresh API inventory with
currently-active 591 IDs in docs/data/listings.json.
"""
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path

import requests

import monitor_pages as core

ENDPOINT = "https://bff-house.591.com.tw/v1/web/sale/list"
OUT = Path("artifacts/591-web-api-fast-report.json")
SOURCE = Path("docs/data/listings.json")
DEVICE_ID = hashlib.md5(b"banqiao-house-monitor-591-web-api").hexdigest()
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


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
    r = requests.get(ENDPOINT, params=params, headers=headers, timeout=15)
    elapsed = time.perf_counter() - started
    if r.status_code != 200:
        raise RuntimeError(f"{road} firstRow={first_row}: HTTP {r.status_code}")
    payload = r.json()
    if payload.get("status") != 1 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(f"{road} firstRow={first_row}: invalid wrapper {str(payload)[:300]}")
    data = payload["data"]
    rows = data.get("house_list")
    if not isinstance(rows, list):
        raise RuntimeError(f"{road} firstRow={first_row}: house_list missing")
    return {
        "firstRow": first_row,
        "http": r.status_code,
        "elapsedSeconds": round(elapsed, 3),
        "total": int(data.get("total") or 0),
        "deviceIdReturned": data.get("device_id"),
        "houseList": rows,
    }


def fetch_road(road, street_id):
    started = time.perf_counter()
    first = request_page(road, street_id, 0)
    total = first["total"]
    offsets = list(range(30, total, 30))
    pages = [first]
    if offsets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(offsets))) as ex:
            futs = [ex.submit(request_page, road, street_id, x) for x in offsets]
            pages.extend(f.result() for f in futs)
    pages.sort(key=lambda x: x["firstRow"])

    by_id = {}
    raw_rows = 0
    exact_rows = []
    for page in pages:
        raw_rows += len(page["houseList"])
        parsed, _ = core.parse_591_api_payload(
            {"data": {"items": page["houseList"]}}, road
        )
        for row in parsed:
            by_id[row["id"]] = row
    exact_rows = list(by_id.values())
    return {
        "road": road,
        "streetId": street_id,
        "total": total,
        "pageCount": len(pages),
        "rawRows": raw_rows,
        "exactCount": len(exact_rows),
        "ids": sorted(x["id"] for x in exact_rows),
        "pages": [
            {
                "firstRow": x["firstRow"],
                "http": x["http"],
                "elapsedSeconds": x["elapsedSeconds"],
                "rawCount": len(x["houseList"]),
                "deviceIdReturnedMatches": x["deviceIdReturned"] == DEVICE_ID,
            }
            for x in pages
        ],
        "elapsedSeconds": round(time.perf_counter() - started, 3),
    }


def active_ids_by_road():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    out = {road: set() for road in core.WATCH_591_STREETS}
    for row in payload.get("listings") or []:
        if row.get("source") != "591" or row.get("active", True) is not True:
            continue
        road = row.get("road")
        if road in out and row.get("id"):
            out[road].add(str(row["id"]))
    return out, (payload.get("runs") or {}).get("591") or {}


def main():
    known, run = active_ids_by_road()
    started = time.perf_counter()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futs = {
            ex.submit(fetch_road, road, sid): road
            for road, sid in core.WATCH_591_STREETS.items()
        }
        for fut in concurrent.futures.as_completed(futs):
            results.append(fut.result())
    results.sort(key=lambda x: list(core.WATCH_591_STREETS).index(x["road"]))

    api_all = set()
    known_all = set()
    for item in results:
        road = item["road"]
        api_ids = set(item["ids"])
        known_ids = known.get(road, set())
        api_all |= api_ids
        known_all |= known_ids
        item["currentActiveCount"] = len(known_ids)
        item["currentActiveMissingIds"] = sorted(known_ids - api_ids)
        item["freshApiNewVsCurrentIds"] = sorted(api_ids - known_ids)

    report = {
        "mode": "591_desktop_web_api_direct_probe_v1",
        "endpoint": ENDPOINT,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "roadsTested": len(results),
        "apiExactUniqueCount": len(api_all),
        "currentActiveCount": len(known_all),
        "currentActiveMissingCount": len(known_all - api_all),
        "currentActiveMissingIds": sorted(known_all - api_all),
        "freshApiNewVsCurrentCount": len(api_all - known_all),
        "source591CheckedAt": run.get("checkedAt"),
        "source591Message": run.get("message"),
        "roads": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        k: report[k] for k in (
            "elapsedSeconds", "roadsTested", "apiExactUniqueCount",
            "currentActiveCount", "currentActiveMissingCount",
            "freshApiNewVsCurrentCount",
        )
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
