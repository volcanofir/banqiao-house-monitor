from urllib.parse import quote

from playwright.sync_api import sync_playwright


ROAD = "中山路二段"
URL = f"https://buy.yungching.com.tw/list/{quote('新北市-板橋區')}_c/{quote(ROAD)}_kw?od=80"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()
        try:
            response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else None
            page.wait_for_timeout(1500)
            title = page.title()
            text = page.locator("body").inner_text(timeout=5000)[:2000]
            ok = status == 200 and "request could not be satisfied" not in title.lower() and ROAD in text
            print(f"Yongching Chromium preflight: HTTP {status}, title={title!r}, roadText={ROAD in text}, ok={ok}")
            return 0 if ok else 2
        except Exception as exc:
            print(f"Yongching Chromium preflight failed: {type(exc).__name__}: {exc}")
            return 3
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
