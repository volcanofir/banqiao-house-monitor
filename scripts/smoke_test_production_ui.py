"""Browser smoke test for the production homepage generated from verified canonical data."""

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = 8766
ROOT = Path('docs')
URL = f'http://127.0.0.1:{PORT}/'
SOURCE_DATA = ROOT / 'data' / 'listings.json'
GAP_DATA = ROOT / 'preview' / 'company-gap.json'


def wait_server():
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('Production local HTTP server did not become ready')


def number(text):
    m = re.search(r'\d+', str(text or ''))
    return int(m.group(0)) if m else None


def main():
    required = [
        ROOT / 'index.html',
        GAP_DATA,
        ROOT / 'preview' / 'scheme-a-verification.json',
        SOURCE_DATA,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError(f'Production smoke prerequisites missing: {missing}')

    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    gap_payload = json.loads(GAP_DATA.read_text(encoding='utf-8'))
    offmarket_count = int(gap_payload.get('recentOffMarketCount') or 0)
    assert gap_payload.get('recentOffMarketRetentionDays') == 10
    assert offmarket_count == len(gap_payload.get('recentOffMarketGroups') or [])

    assert 'noindex,nofollow' not in html
    assert 'PREVIEW 測試版本' not in html
    assert 'Banqiao House Monitor · Preview' not in html
    assert '`data/listings.json?ts=${Date.now()}`' in html
    assert '`preview/company-gap.json?ts=${Date.now()}`' in html
    assert '`preview/scheme-a-verification.json?ts=${Date.now()}`' in html
    assert '<span>已下架</span><strong id="cUnavailable">' in html
    assert '<option value="removed">已下架</option>' in html
    assert 'GAP.recentOffMarketCount??0' in html
    assert 'GAP.recentOffMarketGroups||[]' in html

    server = subprocess.Popen(
        [sys.executable, '-m', 'http.server', str(PORT), '--bind', '127.0.0.1', '--directory', str(ROOT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_server()
        console_errors = []
        page_errors = []
        failed_requests = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
            page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-TW')

            def on_console(msg):
                if msg.type != 'error':
                    return
                text = msg.text or ''
                if text.startswith('Failed to load resource'):
                    return
                console_errors.append(text)

            page.on('console', on_console)
            page.on('pageerror', lambda exc: page_errors.append(str(exc)))
            page.on('requestfailed', lambda req: failed_requests.append(f'{req.method} {req.url}: {req.failure}'))

            response = page.goto(URL, wait_until='networkidle', timeout=30000)
            assert response is not None and response.status == 200
            page.wait_for_function("document.querySelector('#mGroups')?.textContent !== '-'", timeout=15000)

            body_text = page.locator('body').inner_text()
            assert 'PREVIEW 測試版本' not in body_text
            updated = page.locator('#updated').inner_text()
            assert '讀取失敗' not in updated, updated
            assert '比對資料同步中' not in updated, updated

            for selector in ('#mRoads', '#mGroups', '#mNew', '#mMerged', '#cStock', '#cReview', '#cMissing', '#cUnavailable'):
                value = page.locator(selector).inner_text().strip()
                assert value not in ('', '-'), (selector, value)
                assert number(value) is not None, (selector, value)

            assert number(page.locator('#cUnavailable').inner_text()) == offmarket_count
            assert page.locator('#sources .source-card').count() >= 2
            assert page.locator('#groups .road-group').count() >= 1
            assert page.evaluate('VERIFY && VERIFY.valid === true') is True
            assert page.evaluate('verificationMatches(DATA, GAP, VERIFY)') is True

            # Exercise active filters.
            page.locator('.source-tab[data-source="591"]').click()
            page.select_option('#sort', 'priceDesc')
            page.select_option('#companyState', 'missing')
            page.select_option('#companyState', 'all')
            page.locator('.source-tab[data-source="all"]').click()

            # Exercise the new off-market history. It must show only canonical
            # groups retained for the configured ten-day window.
            page.select_option('#state', 'removed')
            if offmarket_count:
                page.wait_for_function("document.querySelectorAll('#groups .item').length > 0", timeout=5000)
                assert page.locator('#groups .item').count() == offmarket_count
                removed_text = page.locator('#groups').inner_text()
                assert '已下架' in removed_text
                assert '下架：' in removed_text
            else:
                assert page.locator('#groups .road-group').count() == 0
                assert '目前沒有符合條件' in page.locator('#groups').inner_text()
            page.select_option('#state', 'all')

            assert not page_errors, page_errors
            meaningful_failed = [x for x in failed_requests if not any(k in x for k in ('favicon', 'icon-safe'))]
            assert not meaningful_failed, meaningful_failed
            assert not console_errors, console_errors

            # Production must also hide stale group/company results if monitor data gets ahead.
            stale_page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-TW')
            stale_errors = []
            stale_page.on('pageerror', lambda exc: stale_errors.append(str(exc)))
            source_payload = json.loads(SOURCE_DATA.read_text(encoding='utf-8'))
            source_payload['updatedAt'] = '2099-01-01T00:00:00+00:00'

            def serve_newer_source(route):
                route.fulfill(
                    status=200,
                    content_type='application/json; charset=utf-8',
                    body=json.dumps(source_payload, ensure_ascii=False),
                )

            stale_page.route('**/data/listings.json*', serve_newer_source)
            stale_response = stale_page.goto(URL, wait_until='networkidle', timeout=30000)
            assert stale_response is not None and stale_response.status == 200
            stale_page.wait_for_function(
                "document.querySelector('#updated')?.textContent.includes('公司比對資料同步中')",
                timeout=15000,
            )
            assert '案件清單暫停顯示' in stale_page.locator('#groups').inner_text()
            for selector in ('#mGroups', '#mNew', '#mMerged', '#cStock', '#cReview', '#cMissing', '#cUnavailable'):
                assert stale_page.locator(selector).inner_text().strip() == '—', selector
            assert stale_page.locator('#groups .road-group').count() == 0
            assert not stale_errors, stale_errors
            stale_page.close()

            browser.close()

        print(f'Production UI smoke test passed, including {offmarket_count} off-market group(s) and stale-source suppression')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
