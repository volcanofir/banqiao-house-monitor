"""Fast Sinyi monitor fetch: crawl all watched roads concurrently, then merge once.

This keeps monitor_pages parsing/filtering semantics unchanged while removing the
serial seven-road network wait from the scheduled monitor workflow.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

import monitor_pages as core
import monitor_fast


MAX_WORKERS = 7
MAX_PAGE_RETRIES = 6
RETRY_DELAY_SECONDS = 1.5


def parse_response_state(text):
    soup = BeautifulSoup(text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return [], None, None, "missing __NEXT_DATA__"
    try:
        payload = json.loads(script.string)
        reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
        parsed = reducer.get("list")
        if not isinstance(parsed, list):
            return [], reducer.get("houseLoading"), reducer.get("totalCnt"), "buyReducer.list is not a list"
        return parsed, reducer.get("houseLoading"), reducer.get("totalCnt"), None
    except Exception as exc:
        return [], None, None, f"{type(exc).__name__}: {exc}"


def request_page(session, url, road, page, previous_count, logs):
    last = None
    for attempt in range(1, MAX_PAGE_RETRIES + 1):
        try:
            response = session.get(
                url,
                headers=core.default_headers("https://www.sinyi.com.tw/"),
                timeout=30,
            )
        except Exception as exc:
            logs.append(f"{road} 第 {page} 頁第 {attempt}/{MAX_PAGE_RETRIES} 次連線失敗：{exc}")
            last = ("network", None, None, None)
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        if response.status_code != 200:
            logs.append(f"{road} 第 {page} 頁第 {attempt}/{MAX_PAGE_RETRIES} 次 HTTP {response.status_code}")
            last = ("http", None, None, response.status_code)
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        parsed, loading, total_cnt, parse_error = parse_response_state(response.text)
        if parse_error:
            logs.append(f"{road} 第 {page} 頁第 {attempt}/{MAX_PAGE_RETRIES} 次解析異常：{parse_error}")
            last = ("parse", parsed, loading, total_cnt)
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        # Sinyi now intermittently returns HTTP 200 with buyReducer.list=[] while
        # houseLoading=true. That is an incomplete SSR snapshot, not an empty road.
        if loading is True:
            logs.append(
                f"{road} 第 {page} 頁第 {attempt}/{MAX_PAGE_RETRIES} 次仍在 houseLoading；"
                f"list={len(parsed)} totalCnt={total_cnt}，等待重試"
            )
            last = ("loading", parsed, loading, total_cnt)
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        # Page 1 suddenly becoming empty while the previous verified snapshot had
        # active listings is also suspicious. Never convert that into mass removals.
        if page == 1 and not parsed and previous_count > 0:
            logs.append(
                f"{road} 第 1 頁第 {attempt}/{MAX_PAGE_RETRIES} 次回 0 筆，"
                f"但上一輪有 {previous_count} 筆；視為可疑空頁並重試"
            )
            last = ("suspicious-empty", parsed, loading, total_cnt)
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        return parsed, total_cnt, True

    state = last[0] if last else "unknown"
    logs.append(f"{road} 第 {page} 頁重試 {MAX_PAGE_RETRIES} 次仍不完整（{state}），本路段判定失敗")
    return [], None, False



def fetch_road(road, previous_count=0):
    rows = []
    logs = []
    pages_read = 0
    keyword = road.replace("板橋區", "")
    page = 1
    seen_search_ids = set()
    expected_total = None
    session = requests.Session()

    while True:
        url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/{page}"
        parsed, total_cnt, ok = request_page(session, url, road, page, previous_count, logs)
        if not ok:
            return rows, False, pages_read, logs

        pages_read += 1
        if page == 1 and isinstance(total_cnt, int):
            expected_total = total_cnt

        if not parsed:
            if expected_total is not None and len(seen_search_ids) < expected_total:
                logs.append(
                    f"{road} 第 {page} 頁為空，但只收齊 {len(seen_search_ids)}/{expected_total} 筆；"
                    "視為不完整，不接受本輪資料"
                )
                return rows, False, pages_read, logs
            logs.append(f"{road} 第 {page} 頁：0 筆，已確認抓完整條路")
            return rows, True, pages_read, logs

        page_ids = {
            core.normalize_text(item.get("houseNo"))
            for item in parsed
            if core.normalize_text(item.get("houseNo"))
        }
        if page_ids and page_ids.issubset(seen_search_ids):
            if expected_total is not None and len(seen_search_ids) < expected_total:
                logs.append(
                    f"{road} 第 {page} 頁全為重複，但目前僅 {len(seen_search_ids)}/{expected_total} 筆；"
                    "視為不完整"
                )
                return rows, False, pages_read, logs
            logs.append(f"{road} 第 {page} 頁：全部為前頁重複案件，已確認抓取結束")
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

        logs.append(
            f"{road} 第 {page} 頁：解析 {len(parsed)}／板橋 {added}／"
            f"累計 raw {len(seen_search_ids)}"
            + (f"/{expected_total}" if expected_total is not None else "")
        )

        if expected_total is not None and len(seen_search_ids) >= expected_total:
            logs.append(f"{road} 已依 totalCnt 收齊 {len(seen_search_ids)}/{expected_total} 筆")
            return rows, True, pages_read, logs

        page += 1
        if page > 30:
            logs.append(f"{road} 超過 30 頁仍未完成，視為失敗")
            return rows, False, pages_read, logs


def fetch_sinyi_parallel(state=None):
    road_order = list(core.WATCH_ROADS)
    previous_counts = {road: 0 for road in road_order}
    for item in ((state or {}).get("listings") or []):
        if item.get("source") != "信義房屋" or not item.get("active", True):
            continue
        road = item.get("road")
        if road in previous_counts:
            previous_counts[road] += 1

    results = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(road_order))) as pool:
        futures = {pool.submit(fetch_road, road, previous_counts.get(road, 0)): road for road in road_order}
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
    rows, ok, message, logs = fetch_sinyi_parallel(state)
    core.merge_source(state, "信義房屋", rows, ok, message, logs, checked_at)
    monitor_fast.save_state(state, checked_at)

    print("信義:", message)
    for line in logs:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


if __name__ == "__main__":
    main()
