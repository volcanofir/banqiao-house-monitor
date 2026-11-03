"""Smoke-test the isolated 591 preview in system Chrome using a local HTTP server.

Requires an already validated docs/591-preview/snapshot.json. The script
does not fetch 591 or alter any repository file.
"""
import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

DOCS = Path("docs").resolve()
DATA = DOCS / "591-preview" / "snapshot.json"


class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    snapshot = json.loads(DATA.read_text(encoding="utf-8"))
    expected = snapshot["counts"]["totalListings"]
    unseen = snapshot["counts"]["idNotInHistory"]
    assert expected > 0 and len(snapshot["roadCounts"]) == 7

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SilentHandler, directory=str(DOCS)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
            try:
                page = browser.new_page(
                    viewport={"width": 390, "height": 844},
                    locale="zh-TW", timezone_id="Asia/Taipei")
                url = "http://127.0.0.1:" + str(server.server_port) + "/591-preview/"
                response = page.goto(url, wait_until="load", timeout=18000)
                assert response and response.status == 200
                page.wait_for_function(
                    "document.querySelector('#total').textContent.trim() !== '—'",
                    timeout=15000)
                assert page.locator("#total").inner_text().replace(",", "") == str(expected)
                page.wait_for_selector("#cards .card", timeout=15000)
                assert page.locator("#cards .card").count() == min(expected, 40)
                areas = page.locator("#cards .card .area").all_inner_texts()
                assert areas and all(
                    float(re.search(r"[\d,.]+", x).group().replace(",", "")) > 0
                    for x in areas
                ), "Area text should be real positive 坪數, never 0"
                links = page.locator("#cards .card .card-footer a")
                assert links.count() > 0
                assert all(
                    "/v2/sale/" in href for href in
                    links.evaluate_all("(els) => els.map(el => el.href)")
                )
                page.locator("#status").select_option("id_not_in_history")
                page.wait_for_function(
                    "(count) => document.querySelector('#summary').textContent.includes('符合條件 ' + count + ' 筆')",
                    arg=unseen,
                    timeout=10000
                )
                assert page.locator("#cards .card").count() == min(unseen, 40)
                page.locator("#status").select_option("all")
                page.locator("#search").fill("不可能出現的字串S234")
                assert page.locator("#cards .card").count() == 0
                assert page.locator("#empty").is_visible()
                page.locator("#search").fill("")
                assert page.locator("#cards .card").count() > 0
                print(json.dumps({
                    "smoke": "pass", "browser": "system Chrome",
                    "mobileViewport": "390x844",
                    "listings": expected, "unseenFilter": unseen,
                    "allRenderedAreasPositive": True,
                    "searchFilter": "pass",
                    "existingPreviewUntouched": True
                }, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)


if __name__ == "__main__":
    main()
