"""Browser smoke test for the production homepage generated from verified canonical data."""

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

PORT = 8766
ROOT = Path('docs')
URL = f'http://127.0.0.1:{PORT}/'
SOURCE_DATA = ROOT / 'data' / 'listings.json'
GAP_DATA = ROOT / 'preview' / 'company-gap.json'
RENTAL_DATA = ROOT / 'preview' / 'rental-data.json'
AUG24_BASELINE = datetime.fromisoformat('2026-08-24T16:00:00+00:00')
TAIPEI = ZoneInfo('Asia/Taipei')


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


def parse_stamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def rental_expected(payload):
    configured = parse_stamp(payload.get('newListingBaselineAt')) or AUG24_BASELINE
    baseline = max(configured, AUG24_BASELINE)
    days = int(payload.get('newListingWindowDays') or 3)
    now = datetime.now(timezone.utc)
    today_taipei = now.astimezone(TAIPEI).date()
    new_count = 0
    today_count = 0
    for row in payload.get('listings') or []:
        first = parse_stamp((row or {}).get('firstSeenAt'))
        if first is None or first < baseline:
            continue
        age = (now - first).total_seconds()
        if 0 <= age < days * 86400:
            new_count += 1
            if first.astimezone(TAIPEI).date() == today_taipei:
                today_count += 1
    return new_count, today_count


def main():
    required = [
        ROOT / 'index.html',
        GAP_DATA,
        ROOT / 'preview' / 'scheme-a-verification.json',
        SOURCE_DATA,
        RENTAL_DATA,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError(f'Production smoke prerequisites missing: {missing}')

    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    gap_payload = json.loads(GAP_DATA.read_text(encoding='utf-8'))
    rental_payload = json.loads(RENTAL_DATA.read_text(encoding='utf-8'))
    offmarket_count = int(gap_payload.get('recentOffMarketCount') or 0)
    rental_count = len(rental_payload.get('listings') or [])
    rental_new_count, rental_today_count = rental_expected(rental_payload)

    assert gap_payload.get('recentOffMarketRetentionDays') == 10
    assert offmarket_count == len(gap_payload.get('recentOffMarketGroups') or [])
    assert rental_payload.get('market') == 'rent'
    assert int((rental_payload.get('counts') or {}).get('total') or 0) == rental_count

    # Static production contract: approved Preview features must survive promotion.
    assert 'noindex,nofollow' not in html
    assert 'PREVIEW 測試版本' not in html
    assert 'Banqiao House Monitor · Preview' not in html
    for fragment in (
        '`data/listings.json?ts=${Date.now()}`',
        '`preview/company-gap.json?ts=${Date.now()}`',
        '`preview/scheme-a-verification.json?ts=${Date.now()}`',
        '`preview/rental-data.json?ts=${Date.now()}`',
        '<option value="changed">本次異動</option>',
        '<option value="timeDesc" selected>上架時間：新 → 舊</option>',
        'function groupChangeInfo(g)',
        'function currentChangedGroups()',
        'function bindRoadAccordion()',
        'function rentalIsNew(x)',
        'function rentalIsTodayNew(x)',
        "timeZone:'Asia/Taipei'",
        '<span class="pill today-new">今日新案</span>',
        "sort.value='timeDesc';",
        '<span>已下架</span><strong id="cUnavailable">',
        '<option value="removed">已下架</option>',
    ):
        assert fragment in html, fragment

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

            assert 'PREVIEW 測試版本' not in page.locator('body').inner_text()
            updated = page.locator('#updated').inner_text()
            assert '讀取失敗' not in updated, updated
            assert '比對資料同步中' not in updated, updated
            assert '委託比對：' in updated, updated
            assert page.locator('#updated br').count() == 1

            for selector in ('#mRoads', '#mGroups', '#mNew', '#mMerged', '#cStock', '#cReview', '#cMissing', '#cUnavailable'):
                value = page.locator(selector).inner_text().strip()
                assert value not in ('', '-'), (selector, value)
                assert number(value) is not None, (selector, value)

            assert number(page.locator('#cUnavailable').inner_text()) == offmarket_count
            assert page.locator('.market-btn').count() == 2
            assert page.evaluate('VERIFY && VERIFY.valid === true') is True
            assert page.evaluate('verificationMatches(DATA, GAP, VERIFY)') is True
            assert page.evaluate("document.querySelector('#sort').value") == 'timeDesc'

            # Current-change filter must render exactly the groups the helper identifies.
            assert page.locator('#state option').count() == 5
            assert page.locator('#state option').nth(3).inner_text() == '本次異動'
            current_changed = int(page.evaluate('currentChangedGroups().length') or 0)
            page.select_option('#state', 'changed')
            assert page.locator('#groups .item').count() == current_changed
            assert page.locator('#groups .item[data-change="1"]').count() == current_changed
            page.select_option('#state', 'all')

            # Off-market history/filter.
            page.select_option('#state', 'removed')
            if offmarket_count:
                items = page.locator('#groups .item')
                assert items.count() == offmarket_count
                assert all('下架：' in (items.nth(i).text_content() or '') for i in range(items.count()))
            else:
                assert page.locator('#groups .road-group').count() == 0
            page.select_option('#state', 'all')

            # Outer road accordion: opening a second road closes the first.
            road_groups = page.locator('#groups > details.road-group')
            if road_groups.count() >= 2:
                road_groups.nth(0).locator(':scope > summary').click()
                assert road_groups.nth(0).get_attribute('open') is not None
                road_groups.nth(1).locator(':scope > summary').click()
                assert road_groups.nth(1).get_attribute('open') is not None
                assert road_groups.nth(0).get_attribute('open') is None

            # Rental: default newest-first, 3-day new count, and Taiwan-today badge.
            page.locator('.market-btn[data-market="rent"]').click()
            page.wait_for_function("MARKET_MODE === 'rent' && document.querySelector('#listTitle')?.textContent.includes('租屋')", timeout=5000)
            assert page.locator('#companyPanel').evaluate("el => getComputedStyle(el).display") == 'none'
            assert page.locator('#companyState').evaluate("el => getComputedStyle(el).display") == 'none'
            assert page.locator('#state option').count() == 2
            assert page.locator('#state option').nth(1).inner_text() == '新案'
            assert page.evaluate("document.querySelector('#sort').value") == 'timeDesc'
            assert '首次抓到：新 → 舊' in page.locator('#sort option').nth(3).inner_text()
            assert number(page.locator('#mGroups').inner_text()) == rental_count
            assert number(page.locator('#mNew').inner_text()) == rental_new_count
            assert page.evaluate("typeof rentalIsTodayNew === 'function'") is True
            assert page.locator('#groups .rent-item .today-new').count() == rental_today_count
            assert page.locator('#groups .rent-item .pill').filter(has_text='新案').count() == rental_new_count
            rental_updated = page.locator('#updated').inner_text()
            assert '今日新案依台灣日期判斷' in rental_updated
            assert '標籤保留' in rental_updated

            page.select_option('#state', 'new')
            assert page.locator('#groups .rent-item').count() == rental_new_count
            page.select_option('#state', 'all')
            assert page.locator('#groups .rent-item').count() == rental_count

            # Switching back to sale must restore newest-first sale sorting and filters.
            page.select_option('#sort', 'priceAsc')
            page.locator('.market-btn[data-market="sale"]').click()
            page.wait_for_function("MARKET_MODE === 'sale' && document.querySelector('#companyPanel')?.style.display !== 'none'", timeout=5000)
            assert page.evaluate("document.querySelector('#sort').value") == 'timeDesc'
            assert '上架時間：新 → 舊' in page.locator('#sort option').nth(3).inner_text()
            assert page.locator('#state option').count() == 5
            assert page.locator('#state option').nth(3).inner_text() == '本次異動'
            assert page.locator('#state option').nth(4).inner_text() == '已下架'

            assert not page_errors, page_errors
            meaningful_failed = [x for x in failed_requests if not any(k in x for k in ('favicon', 'icon-safe'))]
            assert not meaningful_failed, meaningful_failed
            assert not console_errors, console_errors

            # Stale canonical/source mismatch must suppress the list instead of showing mixed data.
            stale_page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-TW')
            stale_errors = []
            stale_page.on('pageerror', lambda exc: stale_errors.append(str(exc)))
            source_payload = json.loads(SOURCE_DATA.read_text(encoding='utf-8'))
            source_payload['updatedAt'] = '2099-01-01T00:00:00+00:00'

            def serve_newer_source(route):
                route.fulfill(status=200, content_type='application/json; charset=utf-8', body=json.dumps(source_payload, ensure_ascii=False))

            stale_page.route('**/data/listings.json*', serve_newer_source)
            stale_response = stale_page.goto(URL, wait_until='networkidle', timeout=30000)
            assert stale_response is not None and stale_response.status == 200
            stale_page.wait_for_function("document.querySelector('#updated')?.textContent.includes('公司比對資料同步中')", timeout=15000)
            assert '案件清單暫停顯示' in stale_page.locator('#groups').inner_text()
            assert stale_page.locator('#groups .road-group').count() == 0
            assert not stale_errors, stale_errors
            stale_page.close()

            browser.close()

        print(
            f'Production UI smoke test passed: {offmarket_count} off-market, '
            f'{current_changed} current-change, {rental_count} rental, '
            f'{rental_new_count} rental new, {rental_today_count} Taiwan-today new; '
            'newest-first defaults, accordion, market switching and stale suppression verified'
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
