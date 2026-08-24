"""Fast Sinyi monitor fetch: crawl all watched roads concurrently, then merge once.

This keeps monitor_pages parsing/filtering semantics unchanged while removing the
serial seven-road network wait from the scheduled monitor workflow.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

import monitor_pages as core
import monitor_fast


MAX_WORKERS = 7


def fetch_road(road):
    rows = []
    logs = []
    pages_read = 0
    keyword = road.replace("板橋區", "")
    page = 1
    seen_search_ids = set()

    while True:
        url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/{page}"
        try:
            response = requests.get(
                url,
                headers=core.default_headers("https://www.sinyi.com.tw/"),
                timeout=30,
            )
        except Exception as exc:
            logs.append(f"{road} 第 {page} 頁連線失敗：{exc}")
            return rows, False, pages_read, logs

        if response.status_code != 200:
            logs.append(f"{road} 第 {page} 頁 HTTP {response.status_code}，停止此路段翻頁")
            return rows, False, pages_read, logs

        pages_read += 1
        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        parsed = []
        if script and script.string:
            try:
                payload = json.loads(script.string)
                reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
                parsed = reducer.get("list") or []
            except Exception:
                parsed = []

        if not isinstance(parsed, list) or not parsed:
            logs.append(f"{road} 第 {page} 頁：0 筆，已抓完整條路")
            return rows, True, pages_read, logs

        page_ids = {
            core.normalize_text(item.get("houseNo"))
            for item in parsed
            if core.normalize_text(item.get("houseNo"))
        }
        if page_ids and page_ids.issubset(seen_search_ids):
            logs.append(f"{road} 第 {page} 頁：全部為前頁重複案件，停止翻頁")
            return rows, True, pages_read, logs
        seen_search_ids.update(page_ids)

        added = 0
        for item in parsed:
            house_id = core.normalize_text(item.get("houseNo"))
            title = core.normalize_text(item.get("name"))
            address = core.normalize_text(item.get("address"))
            if not house_id or not title or not address or not core.is_banqiao_address(address):
                continue
            if not any(alias in address for alias in core.WATCH_ROADS[road]):
                continue
            rows.append({
                "id": f"信義房屋:{house_id}",
                "source": "信義房屋",
                "houseId": house_id,
                "road": road,
                "title": title,
                "address": address,
                "price": f"{item.get('totalPrice'):,}萬" if isinstance(item.get("totalPrice"), (int, float)) else None,
                "size": f"{item.get('areaBuilding')}坪" if isinstance(item.get("areaBuilding"), (int, float)) else None,
                "url": f"https://www.sinyi.com.tw/buy/house/{quote(house_id)}?breadcrumb=list",
                "postTime": core.to_unix(item.get("publishTime") or item.get("updateTime") or item.get("createTime")),
            })
            added += 1

        logs.append(f"{road} 第 {page} 頁：解析 {len(parsed)}／板橋 {added}")
        page += 1


def fetch_sinyi_parallel():
    road_order = list(core.WATCH_ROADS)
    results = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(road_order))) as pool:
        futures = {pool.submit(fetch_road, road): road for road in road_order}
        for future in as_completed(futures):
            road = futures[future]
            try:
                results[road] = future.result()
            except Exception as exc:
                results[road] = ([], False, 0, [f"{road} 並行工作失敗：{type(exc).__name__}: {exc}"])

    rows = []
    logs = []
    successful_roads = 0
    total_pages = 0
    for road in road_order:
        road_rows, ok, pages, road_logs = results.get(road, ([], False, 0, [f"{road} 無抓取結果"] ))
        rows.extend(road_rows)
        logs.extend(road_logs)
        total_pages += pages
        if ok:
            successful_roads += 1

    rows = core.dedupe_by_id(rows)
    ok = successful_roads == len(road_order)
    message = (
        f"信義並行完成 {successful_roads}/{len(road_order)} 路段，共讀取 {total_pages} 頁、{len(rows)} 筆板橋案件。"
        if ok else
        f"信義並行抓取僅完整 {successful_roads}/{len(road_order)} 路段；保留失敗路段上一輪資料。"
    )
    return rows, ok, message, logs


def main():
    checked_at = core.now_iso()
    state = core.load_state()
    rows, ok, message, logs = fetch_sinyi_parallel()
    core.merge_source(state, "信義房屋", rows, ok, message, logs, checked_at)
    monitor_fast.save_state(state, checked_at)

    print("信義:", message)
    for line in logs:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


if __name__ == "__main__":
    main()
