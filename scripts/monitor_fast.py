import asyncio
import json
import os
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import monitor_pages as core
from playwright.async_api import async_playwright

API_591_V1 = "bff-house.591.com.tw/v1/touch/sale/list"
API_591_V2 = "bff-house.591.com.tw/v2/php-api"
ROAD_RETRY_DELAY_SECONDS = 5


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


async def fetch_one_591_road(browser, road, street_id):
    logs = []
    road_rows = []
    road_seen = set()
    context = await browser.new_context(
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
    page = await context.new_page()

    async def route_handler(route):
        if route.request.resource_type in {"image", "font", "media"}:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)
    captured = []

    def on_response(response):
        url = response.url
        if response.status == 200 and (
            API_591_V1 in url or (API_591_V2 in url and "action=list" in url)
        ):
            captured.append(url)

    page.on("response", on_response)

    try:
        bootstrap_url = core.build_591_page_url(road, street_id)
        for round_no in (1, 2):
            target = bootstrap_url
            if round_no == 2:
                target += f"&_r={int(time.time())}-{round_no}"
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                logs.append(f"{road} 暖機第 {round_no} 次導航：{type(exc).__name__}")

            for tick in range(24):
                if captured:
                    break
                if tick in (6, 12, 18):
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass
                await page.wait_for_timeout(250)
            if captured:
                break

        if not captured:
            logs.append(f"{road} 暖機失敗：未取得列表 API。")
            return road_rows, False, logs

        logs.append(f"{road} 暖機成功。")
        template_url = captured[-1]

        for page_no in range(1, 11):
            first_row = (page_no - 1) * 30
            api_url = build_api_url(template_url, street_id, first_row, page_no)
            payload = None

            for attempt, delay in enumerate((0, 0.5, 1.0), start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await context.request.get(
                        api_url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Referer": "https://m.591.com.tw/",
                            "Origin": "https://m.591.com.tw",
                        },
                        timeout=12000,
                    )
                    if response.status == 200:
                        payload = await response.json()
                        break
                    logs.append(
                        f"{road} streetid={street_id} 第 {page_no} 頁第 {attempt} 次 HTTP {response.status}"
                    )
                except Exception as exc:
                    logs.append(
                        f"{road} streetid={street_id} 第 {page_no} 頁第 {attempt} 次：{type(exc).__name__}"
                    )

            if payload is None:
                logs.append(f"{road} 本輪未完整抓取。")
                return [], False, logs

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

        logs.append(f"{road} 完整成功，共 {len(road_rows)} 筆。")
        return road_rows, True, logs
    finally:
        await context.close()


async def launch_591_browser(playwright):
    return await playwright.chromium.launch(
        channel="chrome",
        headless=True,
        args=["--disable-dev-shm-usage"],
    )


async def fast_fetch_591():
    started = time.time()
    road_items = list(core.WATCH_591_STREETS.items())
    orchestration_logs = []
    retry_results = {}

    try:
        async with async_playwright() as p:
            browser = await launch_591_browser(p)
            try:
                first_results = await asyncio.gather(
                    *(fetch_one_591_road(browser, road, street_id) for road, street_id in road_items)
                )
            finally:
                await browser.close()

            failed_indexes = [
                index for index, (_, ok, _) in enumerate(first_results) if not ok
            ]

            if failed_indexes:
                failed_names = [road_items[index][0] for index in failed_indexes]
                orchestration_logs.append(
                    "591 第一輪有 " + str(len(failed_indexes)) + " 條路段未完整："
                    + "、".join(failed_names)
                    + f"；{ROAD_RETRY_DELAY_SECONDS} 秒後以全新 Chrome/session 整條路重抓。"
                )
                await asyncio.sleep(ROAD_RETRY_DELAY_SECONDS)

                retry_browser = None
                try:
                    retry_browser = await launch_591_browser(p)
                    retry_items = [road_items[index] for index in failed_indexes]
                    second_results = await asyncio.gather(
                        *(fetch_one_591_road(retry_browser, road, street_id) for road, street_id in retry_items)
                    )
                    retry_results = {
                        index: result for index, result in zip(failed_indexes, second_results)
                    }
                except Exception as exc:
                    orchestration_logs.append(
                        f"591 自動補抓的新 Chrome/session 啟動或執行失敗：{type(exc).__name__}: {exc}"
                    )
                finally:
                    if retry_browser is not None:
                        await retry_browser.close()
    except Exception as exc:
        return [], False, f"591 單一 Chrome 並行模式啟動失敗，保留上一輪資料：{exc}", []

    rows = []
    logs = list(orchestration_logs)
    global_seen = set()
    successful_roads = 0
    recovered_roads = 0

    for index, ((road, _), first_result) in enumerate(zip(road_items, first_results)):
        first_rows, first_ok, first_logs = first_result
        logs.extend(first_logs)

        final_rows = first_rows
        final_ok = first_ok

        if not first_ok:
            logs.append(f"{road} 第一輪失敗，啟動整條路自動補抓。")
            retry_result = retry_results.get(index)
            if retry_result is not None:
                retry_rows, retry_ok, retry_logs = retry_result
                logs.append(f"{road} 自動補抓：使用全新 Chrome/session，從第 1 頁重新抓取。")
                logs.extend(retry_logs)
                final_rows = retry_rows
                final_ok = retry_ok
                if retry_ok:
                    recovered_roads += 1
                    logs.append(f"{road} 自動補抓成功，本輪採用補抓的完整結果。")
                else:
                    logs.append(f"{road} 自動補抓仍失敗，本輪不使用殘缺結果。")
            else:
                logs.append(f"{road} 未取得自動補抓結果，本輪不使用殘缺結果。")

        if not final_ok:
            logs.append(f"{road} 本輪最終失敗，不計入成功路段。")
            continue

        successful_roads += 1
        for item in final_rows:
            if item["id"] not in global_seen:
                global_seen.add(item["id"])
                rows.append(item)

    rows = core.dedupe_by_id(rows)
    elapsed = round(time.time() - started, 2)

    if successful_roads == len(core.WATCH_591_STREETS):
        recovery_note = (
            f"；其中 {recovered_roads} 路段首次失敗後已自動補抓成功"
            if recovered_roads
            else ""
        )
        return (
            rows,
            True,
            f"591 Surfshark 單一 Chrome 並行完成，成功 7/7 路段，共 {len(rows)} 筆{recovery_note}；核心耗時 {elapsed} 秒。",
            logs,
        )

    return (
        [],
        False,
        f"591 Surfshark 自動補抓後仍僅完整成功 {successful_roads}/7 路段，保留上一輪資料；核心耗時 {elapsed} 秒。",
        logs,
    )


def save_state(state, checked_at):
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


def run_sinyi():
    checked_at = core.now_iso()
    state = core.load_state()
    rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi = core.fetch_sinyi()
    core.merge_source(
        state, "信義房屋", rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi, checked_at
    )
    save_state(state, checked_at)

    print("信義:", msg_sinyi)
    for line in logs_sinyi:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


def run_591():
    checked_at = core.now_iso()
    state = core.load_state()
    rows_591, ok_591, msg_591, logs_591 = asyncio.run(fast_fetch_591())

    previous_591_run = (state.get("runs") or {}).get("591") or {}
    previous_was_full = "成功 7/7" in (previous_591_run.get("message") or "")

    if ok_591 and not previous_was_full:
        state["listings"] = [
            item for item in state.get("listings", [])
            if item.get("source") != "591"
        ]
        state.setdefault("runs", {})["591"] = {}

    core.merge_source(
        state, "591", rows_591, ok_591, msg_591, logs_591, checked_at
    )
    save_state(state, checked_at)

    print("591:", msg_591)
    for line in logs_591:
        print(" -", line)
    print("寫入:", core.DATA_PATH)


def main():
    core.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    source = os.environ.get("MONITOR_SOURCE", "all").strip().lower()

    if source == "sinyi":
        run_sinyi()
        return
    if source == "591":
        run_591()
        return

    # Local/manual fallback. Production workflow deliberately runs Sinyi before VPN,
    # then 591 after Surfshark is connected.
    run_sinyi()
    run_591()


if __name__ == "__main__":
    main()
