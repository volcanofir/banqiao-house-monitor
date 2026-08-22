import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


OUT = Path("docs/preview/yungching-playwright-probe.json")
BASE = "https://buy.yungching.com.tw"
ROADS = [
    "板橋區中山路二段",
    "板橋區三民路一段",
    "板橋區三民路二段",
    "板橋區翠華街",
    "板橋區林森街",
    "板橋區萬安街",
    "板橋區光復街",
]


def road_url(road: str) -> str:
    keyword = road.replace("板橋區", "")
    return f"{BASE}/list/{quote('新北市-板橋區')}_c/{quote(keyword)}_kw?od=80"


def main():
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "network": {
            "surfsharkWorkflowOutcome": os.environ.get("YUNGCHING_PROBE_VPN_OUTCOME"),
            "vpnConnected": os.environ.get("VPN_CONNECTED") == "true",
            "beforeIp": os.environ.get("VPN_BEFORE_IP"),
            "exitIp": os.environ.get("VPN_EXIT_IP"),
        },
        "browser": {"engine": "chromium", "headless": True},
        "roadStatus": {},
        "apiResponses": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()
        payload["browser"]["userAgent"] = page.evaluate("navigator.userAgent")
        payload["browser"]["webdriver"] = page.evaluate("navigator.webdriver")

        def record_api(response):
            if "buy.yungching.com.tw/api/" not in response.url:
                return
            payload["apiResponses"].append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "contentType": response.headers.get("content-type"),
            })

        page.on("response", record_api)

        for road in ROADS:
            api_start = len(payload["apiResponses"])
            url = road_url(road)
            info = {"road": road, "url": url, "mainHttp": None, "available": False}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                info["mainHttp"] = response.status if response else None
                page.wait_for_timeout(5000)
                info["finalUrl"] = page.url
                info["title"] = page.title()[:160]
                info["contentLength"] = len(page.content())
                info["houseLinkCount"] = page.locator('a[href*="/house/"]').count()
                info["roadTextCount"] = page.get_by_text(road.replace("板橋區", ""), exact=False).count()
                new_api = payload["apiResponses"][api_start:]
                info["apiResponseCount"] = len(new_api)
                info["apiStatuses"] = sorted({x["status"] for x in new_api})
                info["listApiStatuses"] = [x["status"] for x in new_api if "/api/v2/list" in x["url"]]
                info["available"] = info["mainHttp"] == 200 and info["houseLinkCount"] > 0
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            payload["roadStatus"][road] = info
            print(
                f"chromium probe {road}: HTTP {info.get('mainHttp')} / "
                f"house links {info.get('houseLinkCount', 0)} / APIs {info.get('apiStatuses', [])}"
            )

        browser.close()

    payload["availableRoadCount"] = sum(1 for x in payload["roadStatus"].values() if x.get("available"))
    payload["apiResponseCount"] = len(payload["apiResponses"])
    payload["api200Count"] = sum(1 for x in payload["apiResponses"] if x.get("status") == 200)
    payload["note"] = "Preview-only Surfshark + standard Playwright Chromium probe. It does not alter the current company comparison source."
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "vpnConnected": payload["network"]["vpnConnected"],
        "availableRoadCount": payload["availableRoadCount"],
        "apiResponseCount": payload["apiResponseCount"],
        "api200Count": payload["api200Count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
