"""Sinyi monitor using the official filterObject API discovered from the rendered site.

Why this exists:
- Sinyi's Next.js SSR (__NEXT_DATA__) now intermittently returns HTTP 200 with
  buyReducer.houseLoading=true and an empty list.
- The rendered browser then calls https://sinyiwebapi.sinyi.com.tw/filterObject.php
  and receives the actual structured listing data.
- The API requires short-lived browser-issued auth headers (code/sat/sid). We never
  persist those values: a system Chrome session obtains them at runtime, then the
  crawler replays the same official API with pageCnt=100.

The API gives houseNo/address/price/area/floor/totalfloor/community/status directly,
so one complete Banqiao crawl can be filtered locally to the seven watched roads.
"""

import json
import time
from copy import deepcopy

import requests
from playwright.sync_api import sync_playwright

import monitor_pages as core
import monitor_fast


API_URL = "https://sinyiwebapi.sinyi.com.tw/filterObject.php"
BOOTSTRAP_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip"
PAGE_SIZE = 100
MAX_PAGES = 30
BOOTSTRAP_TIMEOUT_MS = 90000
BOOTSTRAP_WAIT_MS = 12000
MAX_FULL_ATTEMPTS = 3

SAFE_HEADER_NAMES = {
    "accept", "content-type", "origin", "referer", "user-agent",
    "code", "sat", "sid",
}


def floor_text(floor, total):
    floor = None if floor in (None, "", "null") else str(floor).strip()
    total = None if total in (None, "", "null") else str(total).strip()
    if floor and total:
        return f"{floor}/{total}樓"
    if floor:
        return f"{floor}樓"
    return None


def bootstrap_api_session():
    """Let the rendered Sinyi site mint the current auth headers and payload template."""
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1000},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
        )
        page = context.new_page()

        def on_request(req):
            if API_URL not in req.url or captured:
                return
            try:
                all_headers = req.all_headers()
                safe_headers = {
                    k: v for k, v in all_headers.items()
                    if k.lower() in SAFE_HEADER_NAMES
                }
                payload = json.loads(req.post_data or "{}")
                captured.append((safe_headers, payload))
            except Exception:
                return

        page.on("request", on_request)
        try:
            page.goto(BOOTSTRAP_URL, wait_until="domcontentloaded", timeout=BOOTSTRAP_TIMEOUT_MS)
            deadline = time.time() + (BOOTSTRAP_WAIT_MS / 1000)
            while not captured and time.time() < deadline:
                page.wait_for_timeout(250)
        finally:
            browser.close()

    if not captured:
        raise RuntimeError("信義 rendered browser 未取得 filterObject.php 認證請求")

    headers, payload = captured[0]
    lowered = {str(k).lower(): v for k, v in headers.items()}
    missing = [k for k in ("code", "sat", "sid") if not lowered.get(k)]
    if missing:
        raise RuntimeError(f"信義 filterObject.php 缺少 browser-issued auth headers: {missing}")

    # Never log or persist auth values. Return only in-memory copies.
    return dict(headers), deepcopy(payload)


def call_api(session, headers, payload):
    response = session.post(API_URL, json=payload, headers=headers, timeout=35)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("信義 filterObject.php 非 JSON object")
    if body.get("retResult") is not True or str(body.get("retCode") or "") != "200":
        raise RuntimeError(
            f"信義 filterObject.php API error retCode={body.get('retCode')} retMsg={body.get('retMsg')}"
        )
    content = body.get("content") or {}
    rows = content.get("object") or []
    if not isinstance(rows, list):
        raise RuntimeError("信義 filterObject.php content.object 不是 list")
    return content, rows


def fetch_all_banqiao(headers, template, logs):
    session = requests.Session()
    seen = set()
    all_rows = []
    expected_total = None

    base = deepcopy(template)
    filt = dict(base.get("filter") or {})
    # Keep the site's official Banqiao zip filter and listing-return mode.
    filt["retRange"] = ["220"]
    filt["retType"] = 2
    filt["objectStatus"] = 0
    base["filter"] = filt
    base["pageCnt"] = PAGE_SIZE
    base["isReturnTotal"] = True

    for page_no in range(1, MAX_PAGES + 1):
        payload = deepcopy(base)
        payload["page"] = page_no
        content, rows = call_api(session, headers, payload)

        total = content.get("totalCnt")
        if isinstance(total, int):
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise RuntimeError(
                    f"信義 totalCnt 在同一輪變動：{expected_total} -> {total}（page {page_no}）"
                )

        new_count = 0
        for item in rows:
            hid = str(item.get("houseNo") or "").strip()
            if not hid or hid in seen:
                continue
            seen.add(hid)
            all_rows.append(item)
            new_count += 1

        logs.append(
            f"信義 API 第 {page_no} 頁：raw {len(rows)}／新增 {new_count}／"
            f"累計 {len(seen)}"
            + (f"/{expected_total}" if expected_total is not None else "")
        )

        if expected_total is not None and len(seen) >= expected_total:
            break
        if not rows:
            break
        if len(rows) < PAGE_SIZE and expected_total is None:
            break
    else:
        raise RuntimeError(f"信義 API 超過 {MAX_PAGES} 頁仍未完成")

    if expected_total is None:
        raise RuntimeError("信義 API 未提供 totalCnt")
    if len(seen) != expected_total:
        raise RuntimeError(f"信義 API 分頁不完整：取得 {len(seen)}/{expected_total}")

    logs.append(f"信義 API 板橋區完整抓取：{len(all_rows)}/{expected_total}")
    return all_rows, expected_total


def road_for_address(address):
    text = core.normalize_text(address)
    if not core.is_banqiao_address(text):
        return None
    for road, aliases in core.WATCH_ROADS.items():
        if any(alias in text for alias in aliases):
            return road
    return None


def normalize_item(item, checked_at):
    road = road_for_address(item.get("address"))
    if not road:
        return None
    house_id = core.normalize_text(item.get("houseNo"))
    title = core.normalize_text(item.get("name"))
    address = core.normalize_text(item.get("address"))
    if not house_id or not title or not address:
        return None

    fl = item.get("floor")
    tf = item.get("totalfloor")
    return {
        "id": f"信義房屋:{house_id}",
        "source": "信義房屋",
        "houseId": house_id,
        "road": road,
        "title": title,
        "address": address,
        "price": f"{item.get('totalPrice'):,}萬" if isinstance(item.get("totalPrice"), (int, float)) else None,
        "size": f"{item.get('areaBuilding')}坪" if isinstance(item.get("areaBuilding"), (int, float)) else None,
        "url": f"https://www.sinyi.com.tw/buy/house/{house_id}?breadcrumb=list",
        # filterObject does not currently expose publishTime; the existing
        # first-display enrichment/cache remains responsible for source time.
        "postTime": None,
        "floor": floor_text(fl, tf),
        "structuredFloor": None if fl in (None, "", "null") else str(fl).strip(),
        "structuredTotalFloor": None if tf in (None, "", "null") else str(tf).strip(),
        "floorSourceMode": "sinyi_official_filterObject_api",
        "sinyiCommId": item.get("commId"),
        "sinyiCommName": item.get("commName"),
        "sinyiObjectId": item.get("objectId"),
        "sinyiObjectType": item.get("objectType"),
        "sinyiIsOff": item.get("isOff"),
        "sinyiStatus": item.get("status"),
        "sinyiApiVerifiedAt": checked_at,
        "sinyiApiSource": "filterObject.php",
    }


def fetch_sinyi_api(checked_at):
    logs = []
    last_error = None

    for attempt in range(1, MAX_FULL_ATTEMPTS + 1):
        try:
            logs.append(f"信義官方 API 完整抓取 attempt {attempt}/{MAX_FULL_ATTEMPTS}")
            headers, template = bootstrap_api_session()
            raw_rows, raw_total = fetch_all_banqiao(headers, template, logs)

            rows = []
            road_counts = {road: 0 for road in core.WATCH_ROADS}
            for item in raw_rows:
                row = normalize_item(item, checked_at)
                if not row:
                    continue
                rows.append(row)
                road_counts[row["road"]] += 1

            rows = core.dedupe_by_id(rows)
            if not rows:
                raise RuntimeError("信義 API 完整板橋資料中，七條監控路段結果為 0")

            logs.append(
                "信義七路段：" +
                "、".join(f"{road.replace('板橋區','')} {road_counts[road]}" for road in core.WATCH_ROADS)
            )
            message = (
                f"信義官方 filterObject API 完成：板橋 raw {raw_total} 筆，"
                f"七條監控路段 {len(rows)} 筆；認證由 rendered Chrome 即時取得。"
            )
            return rows, True, message, logs
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logs.append(f"attempt {attempt} 失敗：{last_error}")
            time.sleep(2 * attempt)

    return [], False, f"信義官方 filterObject API 抓取失敗，保留上一輪資料：{last_error}", logs


def main():
    checked_at = core.now_iso()
    state = core.load_state()
    rows, ok, message, logs = fetch_sinyi_api(checked_at)

    # Preserve known source publish timestamps until the dedicated enrichment step
    # refreshes them, because filterObject intentionally focuses on live inventory.
    previous = {
        x.get("id"): x for x in state.get("listings", [])
        if x.get("source") == "信義房屋" and x.get("id")
    }
    if ok:
        for row in rows:
            old = previous.get(row.get("id")) or {}
            if row.get("postTime") is None and old.get("postTime") is not None:
                row["postTime"] = old.get("postTime")
            for key in ("sourcePublishedAt", "sourcePublishedDate", "sourcePublishedAtType",
                        "sourcePublishedRaw", "sourcePublishedEvidence"):
                if row.get(key) in (None, "") and old.get(key) not in (None, ""):
                    row[key] = old.get(key)

    core.merge_source(state, "信義房屋", rows, ok, message, logs, checked_at)
    run = (state.setdefault("runs", {}).setdefault("信義房屋", {}))
    run["mode"] = "official_filterObject_api_browser_auth" if ok else run.get("mode")
    run["apiSource"] = API_URL
    run["authMode"] = "runtime_browser_issued_not_persisted"
    monitor_fast.save_state(state, checked_at)

    print("信義:", message)
    for line in logs:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


if __name__ == "__main__":
    main()
