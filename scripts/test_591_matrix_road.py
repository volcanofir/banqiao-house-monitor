import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright
import monitor_pages as core

API_591_V1 = "bff-house.591.com.tw/v1/touch/sale/list"
API_591_V2 = "bff-house.591.com.tw/v2/php-api"

ROAD = os.environ["ROAD"]
STREET_ID = os.environ["STREET_ID"]
OUTPUT = Path(os.environ.get("OUTPUT", "matrix-result.json"))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_api_url(template_url, first_row=0, page_no=1):
    parsed = urlparse(template_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": str(STREET_ID),
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


def warm_session(page, bootstrap_url, logs):
    found = []

    def on_response(response):
        if response.status != 200:
            return
        url = response.url
        if API_591_V1 in url or (API_591_V2 in url and "action=list" in url):
            found.append(url)

    page.on("response", on_response)

    for round_no in (1, 2, 3):
        try:
            target = bootstrap_url
            if round_no > 1:
                target += ("&" if "?" in target else "?") + f"_r={int(time.time())}-{round_no}"
            page.goto(target, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            logs.append(f"暖機第 {round_no} 次導航：{exc}")

        for tick in range(30):
            if found:
                break
            if tick in (8, 16, 24):
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
            page.wait_for_timeout(500)
        if found:
            break

    if found:
        logs.append("暖機成功")
        return found[-1]
    logs.append("暖機失敗")
    return None


def request_json(context, url, logs, label):
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
                timeout=15000,
            )
            if response.status == 200:
                return json.loads(response.text()), True
            logs.append(f"{label} 第 {attempt} 次 HTTP {response.status}")
        except Exception as exc:
            logs.append(f"{label} 第 {attempt} 次例外：{exc}")
    return None, False


def main():
    logs = []
    result = {
        "road": ROAD,
        "streetid": STREET_ID,
        "success": False,
        "count": 0,
        "pages": 0,
        "logs": logs,
        "startedAt": now_iso(),
        "vpnConnected": os.environ.get("VPN_CONNECTED", "").lower() == "true",
        "vpnExitIp": os.environ.get("VPN_EXIT_IP") or None,
        "_startedEpoch": time.time(),
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
            context = new_mobile_context(browser)
            page = context.new_page()
            seen = set()
            try:
                bootstrap_url = core.build_591_page_url(ROAD, STREET_ID)
                template = warm_session(page, bootstrap_url, logs)
                if not template:
                    return write_result(result)

                for page_no in range(1, 11):
                    payload, ok = request_json(
                        context,
                        build_api_url(template, (page_no - 1) * 30, page_no),
                        logs,
                        f"第 {page_no} 頁",
                    )
                    if not ok:
                        return write_result(result)

                    rows, raw_count = core.parse_591_api_payload(payload, ROAD)
                    new_rows = [x for x in rows if x["id"] not in seen]
                    for item in new_rows:
                        seen.add(item["id"])
                    result["count"] += len(new_rows)
                    result["pages"] += 1
                    logs.append(f"第 {page_no} 頁 raw={raw_count} match={len(rows)} new={len(new_rows)}")

                    if raw_count == 0 or raw_count < 30 or (page_no > 1 and not new_rows):
                        break
                    time.sleep(0.25)

                result["success"] = True
                return write_result(result)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        logs.append(f"啟動失敗：{exc}")
        return write_result(result)


def write_result(result):
    started_epoch = result.pop("_startedEpoch", time.time())
    result["finishedAt"] = now_iso()
    result["durationSeconds"] = round(max(0.0, time.time() - started_epoch), 2)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
