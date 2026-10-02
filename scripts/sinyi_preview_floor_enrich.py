"""Build a Preview-only external snapshot enriched with Sinyi official floor fields.

Reads the existing monitored listings but never rewrites docs/data/listings.json.
For every currently active Sinyi listing, re-fetch the official Sinyi list pages,
match by houseNo, and copy structured `floor` / `totalfloor` into a temporary
Preview snapshot used only by scheme A comparison.
"""

import copy
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

SOURCE = Path("docs/data/listings.json")
OUT = Path("docs/preview/scheme-a-external-enriched.json")
STATS = Path("docs/preview/sinyi-floor-enrichment.json")
PROBE = Path("docs/preview/591-offmarket-probe.json")

ROADS = [
    "板橋區中山路二段",
    "板橋區三民路二段",
    "板橋區光復街",
    "板橋區萬安街",
    "板橋區林森街",
    "板橋區三民路一段",
    "板橋區翠華街",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def list_url(road: str, page: int) -> str:
    keyword = road.replace("板橋區", "")
    return (
        "https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/"
        f"{quote(keyword)}-keyword/publish-desc/{page}"
    )


def parse_page(text: str):
    soup = BeautifulSoup(text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return [], None, None, "missing __NEXT_DATA__"
    try:
        payload = json.loads(script.string)
        reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
        rows = reducer.get("list")
        if not isinstance(rows, list):
            return [], reducer.get("houseLoading"), reducer.get("totalCnt"), "buyReducer.list is not a list"
        return rows, reducer.get("houseLoading"), reducer.get("totalCnt"), None
    except Exception as exc:
        return [], None, None, f"{type(exc).__name__}: {exc}"


def fetch_page_stable(session, road, page, expected_on_road):
    last_note = None
    for attempt in range(1, 7):
        r = session.get(list_url(road, page), headers=HEADERS, timeout=30)
        if r.status_code != 200:
            last_note = f"HTTP {r.status_code}"
            time.sleep(1.5 * attempt)
            continue
        rows, loading, total_cnt, err = parse_page(r.text)
        if err:
            last_note = err
            time.sleep(1.5 * attempt)
            continue
        if loading is True:
            last_note = f"houseLoading=true list={len(rows)} totalCnt={total_cnt}"
            time.sleep(1.5 * attempt)
            continue
        if page == 1 and not rows and expected_on_road:
            last_note = f"可疑空首頁；本路段仍有 {len(expected_on_road)} 筆 active id"
            time.sleep(1.5 * attempt)
            continue
        return r.status_code, rows, total_cnt, attempt
    raise RuntimeError(f"信義官方列表 {road} 第 {page} 頁連續重試仍不完整：{last_note}")


def floor_text(floor, total):
    floor = None if floor in (None, "", "null") else str(floor).strip()
    total = None if total in (None, "", "null") else str(total).strip()
    if floor and total:
        return f"{floor}/{total}樓"
    if floor:
        return f"{floor}樓"
    return None


def fetch_official(active_ids, active_ids_by_road):
    session = requests.Session()
    found = {}
    road_status = {}

    for road in ROADS:
        expected_on_road = set(active_ids_by_road.get(road) or [])
        if not expected_on_road:
            road_status[road] = {
                "pagesRead": 0,
                "lastHttp": None,
                "allHttp200": True,
                "matchedActiveCount": 0,
                "expectedActiveCount": 0,
                "complete": True,
            }
            continue

        road_best = {}
        last_status = None
        total_pages_read = 0
        complete = False
        attempts_used = 0

        # A whole-road retry is useful because Sinyi's SSR can return a valid-looking
        # HTTP 200 page before its search data has actually finished loading.
        for road_attempt in range(1, 5):
            attempts_used = road_attempt
            seen_page_ids = set()
            page = 1
            expected_total = None
            current_found = {}

            while page <= 30:
                status, rows, total_cnt, page_attempts = fetch_page_stable(
                    session, road, page, expected_on_road
                )
                last_status = status
                total_pages_read += 1
                if page == 1 and isinstance(total_cnt, int):
                    expected_total = total_cnt

                if not rows:
                    if expected_total is not None and len(seen_page_ids) < expected_total:
                        break
                    break

                page_ids = {str(x.get("houseNo") or "").strip() for x in rows if x.get("houseNo")}
                if page_ids and page_ids.issubset(seen_page_ids):
                    break
                seen_page_ids.update(page_ids)

                for item in rows:
                    hid = str(item.get("houseNo") or "").strip()
                    if not hid or hid not in active_ids:
                        continue
                    current_found[hid] = {
                        "houseId": hid,
                        "road": road,
                        "name": item.get("name"),
                        "address": item.get("address"),
                        "floor": item.get("floor"),
                        "totalFloor": item.get("totalfloor"),
                        "floorText": floor_text(item.get("floor"), item.get("totalfloor")),
                        "commId": item.get("commId"),
                        "commName": item.get("commName"),
                        "objectId": item.get("objectId"),
                        "objectType": item.get("objectType"),
                    }

                if expected_total is not None and len(seen_page_ids) >= expected_total:
                    break
                page += 1

            if len(current_found) > len(road_best):
                road_best = current_found
            missing_on_road = expected_on_road - set(road_best)
            if not missing_on_road:
                complete = True
                break
            time.sleep(2.0 * road_attempt)

        found.update(road_best)
        road_status[road] = {
            "pagesRead": total_pages_read,
            "lastHttp": last_status,
            "allHttp200": last_status == 200,
            "matchedActiveCount": len(road_best),
            "expectedActiveCount": len(expected_on_road),
            "missingActiveIds": sorted(expected_on_road - set(road_best)),
            "wholeRoadAttempts": attempts_used,
            "complete": complete,
        }

    return found, road_status


def main():
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    active_sinyi = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") == "信義房屋" and x.get("houseId")
    ]
    active_ids = {str(x.get("houseId")) for x in active_sinyi}
    active_ids_by_road = {}
    for item in active_sinyi:
        active_ids_by_road.setdefault(item.get("road"), set()).add(str(item.get("houseId")))
    official, road_status = fetch_official(active_ids, active_ids_by_road)

    missing = sorted(active_ids - set(official))
    if missing:
        raise RuntimeError(f"信義官方列表未找到 {len(missing)} 筆目前有效案件: {missing[:20]}")

    enriched = copy.deepcopy(state)
    applied = 0
    with_floor_value = 0
    without_floor_value = []
    for item in enriched.get("listings", []):
        if not (item.get("active", True) and item.get("source") == "信義房屋" and item.get("houseId")):
            continue
        hid = str(item.get("houseId"))
        src = official[hid]
        item["structuredFloor"] = src.get("floor")
        item["structuredTotalFloor"] = src.get("totalFloor")
        item["floorSourceMode"] = "sinyi_official_next_data_list"
        if src.get("floorText"):
            item["floor"] = src["floorText"]
            with_floor_value += 1
        else:
            without_floor_value.append(hid)
        if src.get("commId") is not None:
            item["sinyiCommId"] = src.get("commId")
        if src.get("commName"):
            item["sinyiCommName"] = src.get("commName")
        if src.get("objectId") is not None:
            item["sinyiObjectId"] = src.get("objectId")
        if src.get("objectType") is not None:
            item["sinyiObjectType"] = src.get("objectType")
        applied += 1

    stats = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "source": "Sinyi official list __NEXT_DATA__.props.initialReduxState.buyReducer.list",
        "activeSinyiCount": len(active_ids),
        "matchedOfficialCount": len(official),
        "appliedCount": applied,
        "withStructuredFloorValueCount": with_floor_value,
        "withoutStructuredFloorValueCount": len(without_floor_value),
        "withoutStructuredFloorValueIds": sorted(without_floor_value),
        "missingActiveIds": missing,
        "roadStatus": road_status,
        "complete": (
            len(official) == len(active_ids) == applied
            and not missing
            and all(x.get("complete") for x in road_status.values())
        ),
    }
    if not stats["complete"]:
        raise RuntimeError(f"信義樓層 enrichment 不完整: {stats}")

    OUT.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preview-only overlay: if the rendered 591 probe ran in the still-connected VPN
    # phase, apply only its explicitly confirmed inactive IDs to this temporary copy.
    # docs/data/listings.json remains untouched.
    if PROBE.exists():
        subprocess.run([sys.executable, "scripts/apply_preview_591_offmarket_probe.py"], check=True)

    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
