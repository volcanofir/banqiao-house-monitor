import json
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import monitor_pages as core
from playwright.sync_api import sync_playwright

API_591_V1 = "bff-house.591.com.tw/v1/touch/sale/list"


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


def browser_fetch_json(page, url, timeout_ms=12000):
    return page.evaluate(
        """async ({url, timeoutMs}) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), timeoutMs);
          try {
            const response = await fetch(url, {
              credentials: 'include',
              signal: controller.signal,
              cache: 'no-store'
            });
            const text = await response.text();
            return {status: response.status, text, error: null};
          } catch (error) {
            return {status: 0, text: '', error: String(error)};
          } finally {
            clearTimeout(timer);
          }
        }""",
        {"url": url, "timeoutMs": timeout_ms},
    )


def fast_fetch_591():
    logs = []
    rows = []
    global_seen = set()
    successful_roads = 0

    try:
        with sync_playwright() as p:
            # GitHub-hosted ubuntu runners already include Google Chrome.
            # Using the installed Chrome avoids downloading Chromium on every run.
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(
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
            page = context.new_page()
            captured_urls = []

            def on_response(response):
                if API_591_V1 in response.url and response.status == 200:
                    captured_urls.append(response.url)

            page.on("response", on_response)

            # Bootstrap only once. After this, all seven roads reuse the same
            # browser session and the same discovered 591 API URL shape.
            bootstrap_road = "板橋區中山路二段"
            bootstrap_street = core.WATCH_591_STREETS[bootstrap_road]
            bootstrap_url = core.build_591_page_url(bootstrap_road, bootstrap_street)
            try:
                page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=25000)
            except Exception as exc:
                logs.append(f"591 bootstrap 導航訊息：{exc}")

            for _ in range(20):
                if captured_urls:
                    break
                page.wait_for_timeout(500)

            if not captured_urls:
                browser.close()
                return [], False, "591 無法取得列表 API，保留上一輪資料。", logs

            template_url = captured_urls[-1]
            logs.append("591 已建立單一瀏覽器 session，開始直接查詢 7 路段 API。")

            for road, street_id in core.WATCH_591_STREETS.items():
                road_seen = set()
                road_ok = False

                for page_no in range(1, 11):
                    first_row = (page_no - 1) * 30
                    api_url = build_api_url(template_url, street_id, first_row, page_no)
                    result = browser_fetch_json(page, api_url)

                    if result.get("status") != 200:
                        logs.append(
                            f"{road} streetid={street_id} 第 {page_no} 頁 API 失敗："
                            f"HTTP {result.get('status')} {result.get('error') or ''}".strip()
                        )
                        break

                    try:
                        payload = json.loads(result.get("text") or "{}")
                    except Exception as exc:
                        logs.append(f"{road} 第 {page_no} 頁 JSON 解析失敗：{exc}")
                        break

                    if page_no == 1:
                        road_ok = True
                        successful_roads += 1

                    page_rows, raw_count = core.parse_591_api_payload(payload, road)
                    new_rows = [item for item in page_rows if item["id"] not in road_seen]

                    for item in new_rows:
                        road_seen.add(item["id"])
                        if item["id"] not in global_seen:
                            global_seen.add(item["id"])
                            rows.append(item)

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

                if not road_ok:
                    logs.append(f"{road} 本輪 API 未成功。")

            browser.close()

    except Exception as exc:
        return [], False, f"591 快速模式啟動失敗，保留上一輪資料：{exc}", logs

    rows = core.dedupe_by_id(rows)
    if successful_roads:
        return (
            rows,
            True,
            f"591 快速 API 完成，成功 {successful_roads}/7 路段，共 {len(rows)} 筆板橋指定路段案件。",
            logs,
        )
    return [], False, "591 七路段皆未成功取得 API，保留上一輪資料。", logs


def main():
    core.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    checked_at = core.now_iso()
    state = core.load_state()

    rows_591, ok_591, msg_591, logs_591 = fast_fetch_591()
    rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi = core.fetch_sinyi()

    # Remove the old experimental 591 baseline once, so bad legacy rows
    # (including the old incorrect area parsing) do not survive the switch.
    previous_591_run = (state.get("runs") or {}).get("591") or {}
    if ok_591 and previous_591_run.get("mode") != "playwright_api":
        state["listings"] = [
            item for item in state.get("listings", [])
            if item.get("source") != "591"
        ]

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
