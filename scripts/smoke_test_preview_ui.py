"""Browser smoke test for the generated Preview UI.

Serves docs/ locally, opens /preview/ in Chromium, and verifies that the canonical
Preview renders without JavaScript/runtime-integrity errors before GitHub Pages
files are published. It also simulates a newer monitor snapshot and requires the UI
to hide stale grouped/comparison results while the canonical comparison catches up.
This is Preview-only and never mutates production data.
"""

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = 8765
ROOT = Path("docs")
URL = f"http://127.0.0.1:{PORT}/preview/"
SOURCE_DATA = ROOT / "data" / "listings.json"


def wait_server():
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Preview local HTTP server did not become ready")


def number(text):
    m = re.search(r"\d+", str(text or ""))
    return int(m.group(0)) if m else None


def main():
    required = [
        ROOT / "preview" / "index.html",
        ROOT / "preview" / "company-gap.json",
        ROOT / "preview" / "scheme-a-verification.json",
        SOURCE_DATA,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError(f"Preview smoke prerequisites missing: {missing}")

    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(ROOT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_server()
        console_errors = []
        page_errors = []
        failed_requests = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 390, "height": 844}, locale="zh-TW")

            def on_console(msg):
                # Local smoke serving does not mirror the GitHub Pages repository
                # prefix used by absolute icon paths. Ignore only browser resource
                # noise; application console.error messages still fail the gate.
                if msg.type != "error":
                    return
                text = msg.text or ""
                if text.startswith("Failed to load resource"):
                    return
                console_errors.append(text)

            page.on("console", on_console)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))

            response = page.goto(URL, wait_until="networkidle", timeout=30000)
            assert response is not None and response.status == 200, response.status if response else None
            page.wait_for_function("document.querySelector('#mGroups')?.textContent !== '-'", timeout=15000)

            updated = page.locator("#updated").inner_text()
            assert "讀取失敗" not in updated, updated
            assert "完整性驗證未通過" not in updated, updated
            assert "比對資料同步中" not in updated, updated

            for selector in ("#mRoads", "#mGroups", "#mNew", "#mMerged", "#cStock", "#cReview", "#cMissing", "#cUnavailable"):
                text = page.locator(selector).inner_text().strip()
                assert text not in ("", "-"), (selector, text)
                assert number(text) is not None, (selector, text)

            assert page.locator("#sources .source-card").count() >= 2
            assert page.locator("#groups .road-group").count() >= 1
            assert page.evaluate("VERIFY && VERIFY.valid === true") is True
            assert page.evaluate("verificationMatches(DATA, GAP, VERIFY)") is True

            # Exercise the main controls so event-handler regressions fail the publish.
            page.locator('.source-tab[data-source="591"]').click()
            assert "active" in (page.locator('.source-tab[data-source="591"]').get_attribute("class") or "")
            page.select_option("#sort", "priceDesc")
            page.select_option("#companyState", "missing")
            page.select_option("#companyState", "all")
            page.locator('.source-tab[data-source="all"]').click()

            assert not page_errors, page_errors
            meaningful_failed = [x for x in failed_requests if not any(k in x for k in ("favicon", "icon-safe"))]
            assert not meaningful_failed, meaningful_failed
            assert not console_errors, console_errors

            # Negative-path regression: make only listings.json appear newer than the
            # comparison output. The UI must refuse to show the previous grouping or
            # company counts as though they were current.
            stale_page = browser.new_page(viewport={"width": 390, "height": 844}, locale="zh-TW")
            stale_errors = []
            stale_page.on("pageerror", lambda exc: stale_errors.append(str(exc)))
            source_payload = json.loads(SOURCE_DATA.read_text(encoding="utf-8"))
            source_payload["updatedAt"] = "2099-01-01T00:00:00+00:00"

            def serve_newer_source(route):
                route.fulfill(
                    status=200,
                    content_type="application/json; charset=utf-8",
                    body=json.dumps(source_payload, ensure_ascii=False),
                )

            stale_page.route("**/data/listings.json*", serve_newer_source)
            stale_response = stale_page.goto(URL, wait_until="networkidle", timeout=30000)
            assert stale_response is not None and stale_response.status == 200
            stale_page.wait_for_function(
                "document.querySelector('#updated')?.textContent.includes('公司比對資料同步中')",
                timeout=15000,
            )
            assert "案件清單暫停顯示" in stale_page.locator("#groups").inner_text()
            for selector in ("#mGroups", "#mNew", "#mMerged", "#cStock", "#cReview", "#cMissing", "#cUnavailable"):
                assert stale_page.locator(selector).inner_text().strip() == "—", selector
            assert stale_page.locator("#groups .road-group").count() == 0
            assert not stale_errors, stale_errors
            stale_page.close()

            browser.close()

        print("Preview UI smoke test passed, including stale-source suppression")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
