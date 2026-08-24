"""Browser smoke test for the complete Preview UI.

The gate covers canonical sale data, rental switching, off-market history and stale-source
suppression. A Preview that fails any of these checks must not be promoted to production.
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
GAP_DATA = ROOT / "preview" / "company-gap.json"
RENTAL_DATA = ROOT / "preview" / "rental-data.json"


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
        GAP_DATA,
        ROOT / "preview" / "scheme-a-verification.json",
        SOURCE_DATA,
        RENTAL_DATA,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError(f"Preview smoke prerequisites missing: {missing}")

    gap_payload = json.loads(GAP_DATA.read_text(encoding="utf-8"))
    rental_payload = json.loads(RENTAL_DATA.read_text(encoding="utf-8"))
    offmarket_count = int(gap_payload.get("recentOffMarketCount") or 0)
    rental_count = len(rental_payload.get("listings") or [])
    assert gap_payload.get("recentOffMarketRetentionDays") == 10
    assert offmarket_count == len(gap_payload.get("recentOffMarketGroups") or [])
    assert rental_payload.get("market") == "rent"
    assert int((rental_payload.get("counts") or {}).get("total") or 0) == rental_count

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
            assert response is not None and response.status == 200
            page.wait_for_function("document.querySelector('#mGroups')?.textContent !== '-'", timeout=15000)

            updated = page.locator("#updated").inner_text()
            assert "讀取失敗" not in updated, updated
            assert "完整性驗證未通過" not in updated, updated
            assert "比對資料同步中" not in updated, updated

            for selector in ("#mRoads", "#mGroups", "#mNew", "#mMerged", "#cStock", "#cReview", "#cMissing", "#cUnavailable"):
                text = page.locator(selector).inner_text().strip()
                assert text not in ("", "-"), (selector, text)
                assert number(text) is not None, (selector, text)

            assert number(page.locator("#cUnavailable").inner_text()) == offmarket_count
            assert page.locator("#sources .source-card").count() >= 2
            assert page.locator("#groups .road-group").count() >= 1
            assert page.locator(".market-btn").count() == 2
            assert page.evaluate("VERIFY && VERIFY.valid === true") is True
            assert page.evaluate("verificationMatches(DATA, GAP, VERIFY)") is True

            # Sale controls.
            page.locator('.source-tab[data-source="591"]').click()
            assert "active" in (page.locator('.source-tab[data-source="591"]').get_attribute("class") or "")
            page.select_option("#sort", "priceDesc")
            page.select_option("#companyState", "missing")
            page.select_option("#companyState", "all")
            page.locator('.source-tab[data-source="all"]').click()

            # Off-market canonical history must be filterable and count-consistent.
            page.select_option("#state", "removed")
            if offmarket_count:
                page.wait_for_function("document.querySelectorAll('#groups .item').length > 0", timeout=5000)
                assert page.locator("#groups .item").count() == offmarket_count
                removed_text = page.locator("#groups").inner_text()
                assert "已下架" in removed_text
                assert "下架：" in removed_text
            else:
                assert page.locator("#groups .road-group").count() == 0
            page.select_option("#state", "all")

            # Rental mode must load the independent data file without mutating the sale UI.
            page.locator('.market-btn[data-market="rent"]').click()
            page.wait_for_function("MARKET_MODE === 'rent' && document.querySelector('#listTitle')?.textContent.includes('租屋')", timeout=5000)
            assert page.locator("#companyPanel").evaluate("el => getComputedStyle(el).display") == "none"
            assert number(page.locator("#mGroups").inner_text()) == rental_count
            assert page.locator("#sources .source-card").count() == 2
            assert "租屋資料最近更新" in page.locator("#updated").inner_text()
            assert "租金" in page.locator("#sort option").nth(1).inner_text()
            if rental_count:
                assert page.locator("#groups .rent-item").count() >= 1
            page.locator('.source-tab[data-source="591"]').click()
            page.select_option("#sort", "priceAsc")

            # Switching back to sale must restore company comparison and canonical integrity.
            page.locator('.market-btn[data-market="sale"]').click()
            page.wait_for_function("MARKET_MODE === 'sale' && document.querySelector('#companyPanel')?.style.display !== 'none'", timeout=5000)
            assert page.evaluate("verificationMatches(DATA, GAP, VERIFY)") is True
            assert "售價" in page.locator("#sort option").nth(1).inner_text()

            assert not page_errors, page_errors
            meaningful_failed = [x for x in failed_requests if not any(k in x for k in ("favicon", "icon-safe"))]
            assert not meaningful_failed, meaningful_failed
            assert not console_errors, console_errors

            # Negative path: a newer monitor snapshot must suppress stale sale comparison output.
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

        print(
            f"Preview UI smoke test passed: sale integrity, {offmarket_count} off-market group(s), "
            f"{rental_count} rental listing(s), market switching and stale-source suppression"
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
