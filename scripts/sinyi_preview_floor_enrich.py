"""Build a Preview-only external snapshot enriched with Sinyi official floor fields.

Reads the existing monitored listings but never rewrites docs/data/listings.json.
For every currently active Sinyi listing, re-fetch the official Sinyi list pages,
match by houseNo, and copy structured `floor` / `totalfloor` into a temporary
Preview snapshot used only by scheme A comparison.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

SOURCE = Path("docs/data/listings.json")
OUT = Path("docs/preview/scheme-a-external-enriched.json")
STATS = Path("docs/preview/sinyi-floor-enrichment.json")

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
        return []
    payload = json.loads(script.string)
    reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
    rows = reducer.get("list") or []
    return rows if isinstance(rows, list) else []


def floor_text(floor, total):
    floor = None if floor in (None, "", "null") else str(floor).strip()
    total = None if total in (None, "", "null") else str(total).strip()
    if floor and total:
        return f"{floor}/{total}樓"
    if floor:
        return f"{floor}樓"
    return None


def fetch_official(active_ids):
    session = requests.Session()
    found = {}
    road_status = {}

    for road in ROADS:
        seen_page_ids = set()
        page = 1
        http_codes = []
        parsed_pages = 0
        while page <= 30:
            url = list_url(road, page)
            r = session.get(url, headers=HEADERS, timeout=30)
            http_codes.append(r.status_code)
            if r.status_code != 200:
                raise RuntimeError(f"信義官方列表 {road} 第 {page} 頁 HTTP {r.status_code}")
            rows = parse_page(r.text)
            parsed_pages += 1
            if not rows:
                break

            page_ids = {str(x.get("houseNo") or "").strip() for x in rows if x.get("houseNo")}
            if page_ids and page_ids.issubset(seen_page_ids):
                break
            seen_page_ids.update(page_ids)

            for item in rows:
                hid = str(item.get("houseNo") or "").strip()
                if not hid or hid not in active_ids:
                    continue
                found[hid] = {
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
            page += 1

        road_status[road] = {
            "pagesRead": parsed_pages,
            "lastHttp": http_codes[-1] if http_codes else None,
            "allHttp200": bool(http_codes) and all(x == 200 for x in http_codes),
            "matchedActiveCount": sum(1 for x in found.values() if x.get("road") == road),
        }

    return found, road_status


def main():
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    active_sinyi = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") == "信義房屋" and x.get("houseId")
    ]
    active_ids = {str(x.get("houseId")) for x in active_sinyi}
    official, road_status = fetch_official(active_ids)

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
        "complete": len(official) == len(active_ids) == applied and not missing and all(x.get("allHttp200") for x in road_status.values()),
    }
    if not stats["complete"]:
        raise RuntimeError(f"信義樓層 enrichment 不完整: {stats}")

    OUT.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
