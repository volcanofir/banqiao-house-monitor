import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright
import monitor_pages as core

ROADS = {
    "板橋區中山路二段": "27507",
    "板橋區三民路二段": "27485",
    "板橋區光復街": "27550",
    "板橋區萬安街": "27630",
    "板橋區林森街": "27574",
    "板橋區三民路一段": "27484",
    "板橋區翠華街": "27644",
}
API_V1 = "bff-house.591.com.tw/v1/touch/sale/list"
API_V2 = "bff-house.591.com.tw/v2/php-api"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def api_url(template, street_id, first_row, page_no):
    parsed = urlparse(template)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": street_id,
        "firstRow": str(first_row),
        "newPage": str(page_no),
        "newPageSize": "30",
        "timestamp": str(int(time.time() * 1000)),
        "region_id": "3",
        "device": "touch",
    })
    return urlunparse(parsed._replace(query=urlencode(params)))


async def fetch_road(browser, road, street_id):
    started = time.time()
    logs = []
    result = {
        "road": road,
        "streetid": street_id,
        "success": False,
        "count": 0,
        "pages": 0,
        "logs": logs,
        "startedAt": now_iso(),
        "vpnConnected": os.environ.get("VPN_CONNECTED", "").lower() == "true",
        "vpnExitIp": os.environ.get("VPN_EXIT_IP") or None,
    }

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
        if response.status == 200 and (API_V1 in url or (API_V2 in url and "action=list" in url)):
            captured.append(url)

    page.on("response", on_response)

    try:
        bootstrap = core.build_591_page_url(road, street_id)
        for round_no in (1, 2):
            target = bootstrap if round_no == 1 else bootstrap + f"&_r={int(time.time())}-{round_no}"
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                logs.append(f"暖機導航 {round_no}：{type(exc).__name__}")

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
            logs.append("暖機失敗")
            return result

        logs.append("暖機成功")
        template = captured[-1]
        seen = set()

        for page_no in range(1, 11):
            url = api_url(template, street_id, (page_no - 1) * 30, page_no)
            payload = None
            for attempt, delay in enumerate((0, 0.5, 1.0), start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await context.request.get(
                        url,
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
                    logs.append(f"第 {page_no} 頁第 {attempt} 次 HTTP {response.status}")
                except Exception as exc:
                    logs.append(f"第 {page_no} 頁第 {attempt} 次 {type(exc).__name__}")

            if payload is None:
                return result

            rows, raw_count = core.parse_591_api_payload(payload, road)
            new_rows = [x for x in rows if x["id"] not in seen]
            for item in new_rows:
                seen.add(item["id"])
            result["count"] += len(new_rows)
            result["pages"] += 1
            logs.append(f"第 {page_no} 頁 raw={raw_count} match={len(rows)} new={len(new_rows)}")

            if raw_count == 0 or raw_count < 30 or (page_no > 1 and not new_rows):
                break

        result["success"] = result["count"] > 0
        return result
    finally:
        result["finishedAt"] = now_iso()
        result["durationSeconds"] = round(time.time() - started, 2)
        await context.close()


async def main():
    started = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        try:
            rows = await asyncio.gather(*(fetch_road(browser, road, sid) for road, sid in ROADS.items()))
        finally:
            await browser.close()

    report = {
        "checkedAt": now_iso(),
        "mode": "surfshark_one_chrome_seven_contexts_parallel",
        "vpnExpected": True,
        "vpnVerifiedForAllResults": len(rows) == 7 and all(r.get("vpnConnected") and r.get("vpnExitIp") for r in rows),
        "vpnExitIps": sorted({r.get("vpnExitIp") for r in rows if r.get("vpnExitIp")}),
        "successCount": sum(bool(r.get("success")) for r in rows),
        "totalRoads": 7,
        "receivedResults": len(rows),
        "allSucceeded": len(rows) == 7 and all(bool(r.get("success")) for r in rows),
        "wallSeconds": round(time.time() - started, 2),
        "results": rows,
        "productionDataModified": False,
    }
    out = Path("docs/data/591-one-browser-test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
