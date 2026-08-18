import json
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import monitor_pages as core
from playwright.sync_api import sync_playwright

API_591_V1 = "bff-house.591.com.tw/v1/touch/sale/list"
API_591_V2 = "bff-house.591.com.tw/v2/php-api"


def build_api_url(template_url, street_id, first_row=0, page_no=1):
    parsed = urlparse(template_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": str(street_id),
        "firstRow": str(first_row),
        "newPage": str(page_no),
        "newPageSize": "30",
        "timestamp": str(int(time.time() * 1000)),
        "region_id": "3",
        "device": "touch",
    })
    return urlunparse(parsed._replace(query=urlencode(params)))


def new_mobile_context(browser):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )


def request_json(context, url, logs, label):
    last_error = ""
    for attempt, delay in enumerate((0, 1.0, 2.0), start=1):
        if delay:
            time.sleep(delay)
        try:
            response = context.request.get(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://m.591.com.tw/",
                    "Origin": "https://m.591.com.tw",
                },
                timeout=12000,
            )
            status = response.status
            text = response.text()
            if status == 200:
                return json.loads(text), True
            last_error = f"HTTP {status}"
        except Exception as exc:
            last_error = str(exc)
        logs.append(f"{label} 第 {attempt} 次失敗：{last_error}")
    return None, False


def warm_591_session(page, logs, bootstrap_url, road):
    v1_urls = []
    v2_urls = []

    def on_response(response):
        if response.status != 200:
            return
        url = response.url
        if API_591_V1 in url:
            v1_urls.append(url)
        elif API_591_V2 in url and "action=list" in url:
            v2_urls.append(url)

    page.on("response", on_response)

    for round_no in (1, 2):
        try:
            target = bootstrap_url
            if round_no == 2:
                separator = "&" if "?" in target else "?"
                target = f"{target}{separator}_r={int(time.time())}"
            page.goto(target, wait_until="domcontentloaded", timeout=25000)
        except Exception as exc:
            logs.append(f"{road} 暖機第 {round_no} 次導航訊息：{exc}")

        for tick in range(24):
            if v1_urls or v2_urls:
                break
            if tick in (8, 16):
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
            page.wait_for_timeout(500)

        if v1_urls or v2_urls:
            break

    if v1_urls:
        logs.append(f"{road} 獨立 session 暖機成功：取得 v1/touch/sale/list。")
        return v1_urls[-1]
    if v2_urls:
        logs.append(f"{road} 獨立 session 暖機成功：取得 v2/php-api list。")
        return v2_urls[-1]
    logs.append(f"{road} 獨立 session 暖機失敗：未取得列表 API。")
    return None


def fetch_one_591_road(browser, road, street_id, logs):
    context = new_mobile_context(browser)
    page = context.new_page()
    road_rows = []
    road_seen = set()

    try:
        bootstrap_url = core.build_591_page_url(road, street_id)
        template_url = warm_591_session(page, logs, bootstrap_url, road)
        if not template_url:
            return [], False

        verify_url = build_api_url(template_url, street_id, 0, 1)
        _, verified = request_json(
            context,
            verify_url,
            logs,
            f"{road} API 模板驗證",
        )
        if not verified:
            logs.append(f"{road} 獨立 session API 模板驗證失敗。")
            return [], False

        for page_no in range(1, 11):
            first_row = (page_no - 1) * 30
            api_url = build_api_url(template_url, street_id, first_row, page_no)
            payload, ok = request_json(
                context,
                api_url,
                logs,
                f"{road} streetid={street_id} 第 {page_no} 頁",
            )
            if not ok:
                logs.append(f"{road} 本輪未完整抓取。")
                return [], False

            page_rows, raw_count = core.parse_591_api_payload(payload, road)
            new_rows = [item for item in page_rows if item["id"] not in road_seen]

            for item in new_rows:
                road_seen.add(item["id"])
                road_rows.append(item)

            logs.append(
                f"{road} streetid={street_id} 第 {page_no} 頁："
                f"API {raw_count} 筆／路段符合 {len(page_rows)}／新增 {len(new_rows)}"
            )

            if raw_count == 0:
                break
            if page_no > 1 and not new_rows:
                break
            if raw_count < 30:
                break

            time.sleep(0.25)

        logs.append(f"{road} 獨立 session 完整成功，共 {len(road_rows)} 筆。")
        return road_rows, True

    finally:
        context.close()


def fast_fetch_591():
    logs = []
    rows = []
    global_seen = set()
    successful_roads = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--disable-dev-shm-usage"],
            )

            logs.append("591 改用 7 路段各自獨立 BrowserContext/session。")

            for index, (road, street_id) in enumerate(core.WATCH_591_STREETS.items(), start=1):
                logs.append(f"開始第 {index}/7 路段：{road}。")
                road_rows, ok = fetch_one_591_road(browser, road, street_id, logs)

                if ok:
                    successful_roads += 1
                    for item in road_rows:
                        if item["id"] not in global_seen:
                            global_seen.add(item["id"])
                            rows.append(item)
                else:
                    logs.append(f"{road} 本輪失敗，不計入成功路段。")

                # Give 591 a short gap before creating the next anonymous session.
                if index < len(core.WATCH_591_STREETS):
                    time.sleep(2.0)

            browser.close()

    except Exception as exc:
        return [], False, f"591 獨立 session 模式啟動失敗，保留上一輪資料：{exc}", logs

    rows = core.dedupe_by_id(rows)
    if successful_roads == len(core.WATCH_591_STREETS):
        return (
            rows,
            True,
            f"591 獨立 session 完成，成功 7/7 路段，共 {len(rows)} 筆板橋指定路段案件。",
            logs,
        )

    return (
        [],
        False,
        f"591 獨立 session 本輪僅完整成功 {successful_roads}/7 路段，保留上一輪資料。",
        logs,
    )


def main():
    core.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    checked_at = core.now_iso()
    state = core.load_state()

    rows_591, ok_591, msg_591, logs_591 = fast_fetch_591()
    rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi = core.fetch_sinyi()

    previous_591_run = (state.get("runs") or {}).get("591") or {}
    previous_was_full = "成功 7/7" in (previous_591_run.get("message") or "")

    if ok_591 and not previous_was_full:
        state["listings"] = [
            item for item in state.get("listings", [])
            if item.get("source") != "591"
        ]
        state.setdefault("runs", {})["591"] = {}

    new_591, _ = core.merge_source(
        state, "591", rows_591, ok_591, msg_591, logs_591, checked_at
    )
    new_sinyi, _ = core.merge_source(
        state, "信義房屋", rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi, checked_at
    )

    state["updatedAt"] = checked_at
    state["watchRoads"] = list(core.WATCH_ROADS.keys())
    state["listings"] = sorted(
        state["listings"],
        key=lambda item: (
            0 if item.get("active", True) else 1,
            -(item.get("postTime") or 0),
            item.get("firstSeenAt") or "",
        ),
    )[:600]

    core.DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    core.send_telegram(state, new_591 + new_sinyi)

    print("591:", msg_591)
    for line in logs_591:
        print(" -", line)
    print("信義:", msg_sinyi)
    for line in logs_sinyi:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


if __name__ == "__main__":
    main()
