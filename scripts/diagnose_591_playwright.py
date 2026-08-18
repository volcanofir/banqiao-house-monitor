import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUTPUT = Path("docs/data/591-playwright-diagnostic.json")
TARGET_URL = (
    "https://m.591.com.tw/v2/sale?"
    "regionid=3&sectionidStr=26&o=32&streetid=27507&keywords=" + quote("中山路二段")
)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compact(text, limit=6000):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    captured = []
    console = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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

        def on_console(msg):
            if len(console) < 50:
                console.append({"type": msg.type, "text": compact(msg.text, 1000)})

        def on_page_error(error):
            if len(page_errors) < 30:
                page_errors.append(compact(str(error), 1200))

        def on_response(response):
            if len(captured) >= 120:
                return
            resource_type = response.request.resource_type
            content_type = (response.headers.get("content-type") or "").lower()
            if resource_type not in ("xhr", "fetch") and "json" not in content_type:
                return

            record = {
                "url": response.url,
                "status": response.status,
                "resourceType": resource_type,
                "contentType": content_type,
            }
            try:
                text = response.text()
                lowered = text.lower()
                record["bodyLength"] = len(text)
                record["containsHouseId"] = "houseid" in lowered or "house_id" in lowered
                record["containsPrice"] = "price" in lowered or "showprice" in lowered
                record["containsTargetRoad"] = "中山路二段" in text or "中山路2段" in text
                record["preview"] = compact(text, 5000)
            except Exception as exc:
                record["readError"] = compact(str(exc), 500)
            captured.append(record)

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("response", on_response)

        navigation_error = None
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            for fraction in (0.35, 0.7, 1.0):
                page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {fraction})")
                page.wait_for_timeout(2500)
        except Exception as exc:
            navigation_error = compact(str(exc), 1500)

        title = ""
        final_url = page.url
        html = ""
        body_text = ""
        anchors = []
        try:
            title = page.title()
        except Exception:
            pass
        try:
            html = page.content()
        except Exception:
            pass
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:
            pass
        try:
            anchors = page.locator("a[href]").evaluate_all(
                "els => els.map(a => ({text:(a.innerText||'').trim(), href:a.href}))"
            )
        except Exception:
            anchors = []

        listing_links = []
        seen_links = set()
        for item in anchors:
            href = item.get("href") or ""
            if re.search(r"/(?:v2/sale|home/house/detail/2)/\d+", href) and href not in seen_links:
                seen_links.add(href)
                listing_links.append({"text": compact(item.get("text") or "", 300), "href": href})

        browser.close()

    interesting = sorted(
        captured,
        key=lambda item: (
            item.get("containsHouseId", False),
            item.get("containsTargetRoad", False),
            item.get("containsPrice", False),
            item.get("bodyLength", 0),
        ),
        reverse=True,
    )

    result = {
        "checkedAt": now_iso(),
        "target": {
            "road": "板橋區中山路二段",
            "streetid": "27507",
            "url": TARGET_URL,
        },
        "page": {
            "finalUrl": final_url,
            "title": title,
            "htmlLength": len(html),
            "bodyTextLength": len(body_text),
            "bodyPreview": compact(body_text, 6000),
            "listingLinkCount": len(listing_links),
            "listingLinks": listing_links[:40],
            "navigationError": navigation_error,
        },
        "network": {
            "capturedCount": len(captured),
            "interesting": interesting[:60],
        },
        "console": console,
        "pageErrors": page_errors,
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "target": TARGET_URL,
        "finalUrl": final_url,
        "title": title,
        "htmlLength": len(html),
        "listingLinkCount": len(listing_links),
        "capturedNetworkResponses": len(captured),
        "houseIdResponses": sum(1 for item in captured if item.get("containsHouseId")),
        "roadResponses": sum(1 for item in captured if item.get("containsTargetRoad")),
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
