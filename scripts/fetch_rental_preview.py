import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright

OUT = Path('docs/preview/rental-data.json')

WATCH_ROADS = {
    '板橋區中山路二段': ('中山路二段', '中山路2段'),
    '板橋區三民路二段': ('三民路二段', '三民路2段'),
    '板橋區光復街': ('光復街',),
    '板橋區萬安街': ('萬安街',),
    '板橋區林森街': ('林森街',),
    '板橋區三民路一段': ('三民路一段', '三民路1段'),
    '板橋區翠華街': ('翠華街',),
}

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def norm(v):
    text = '' if v is None else str(v)
    text = re.sub(r'\s+', ' ', text).strip().replace('臺', '台')
    return text.replace('中山路2段', '中山路二段').replace('三民路1段', '三民路一段').replace('三民路2段', '三民路二段')


def road_for(text):
    text = norm(text)
    if '板橋區' not in text:
        return None
    for road, aliases in WATCH_ROADS.items():
        if any(alias in text for alias in aliases):
            return road
    return None


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'[\d,]+(?:\.\d+)?', norm(v))
    return float(m.group(0).replace(',', '')) if m else None


def browser_json(page, url):
    return page.evaluate(
        """async (url) => {
          const r = await fetch(url, {credentials: 'include'});
          const text = await r.text();
          return {status: r.status, text};
        }""",
        url,
    )


def mutate_591_url(url, first_row, total_rows):
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q['region'] = '3'
    q['section'] = '26'
    q['firstRow'] = str(first_row)
    q['totalRows'] = str(total_rows or 0)
    q['order'] = q.get('order') or 'posttime'
    q['orderType'] = q.get('orderType') or 'desc'
    q['_'] = str(int(time.time() * 1000))
    return urlunparse(p._replace(query=urlencode(q)))


def parse_591_items(items, seen):
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        hid = norm(item.get('id') or item.get('post_id'))
        title = norm(item.get('title'))
        address = norm(item.get('address'))
        section = norm(item.get('section_name') or item.get('section'))
        combined = address if '板橋區' in address else f'{section}-{address}'
        road = road_for(combined)
        if not hid or not road or hid in seen:
            continue
        seen.add(hid)
        url = norm(item.get('url'))
        if not url.startswith('http'):
            url = f'https://rent.591.com.tw/{hid}'
        rows.append({
            'id': f'591租屋:{hid}',
            'source': '591',
            'houseId': hid,
            'road': road,
            'title': title or f'591租屋 {hid}',
            'address': combined,
            'rent': num(item.get('price')),
            'size': num(item.get('area')),
            'url': url,
            'floor': norm(item.get('floor_name')) or None,
            'kind': norm(item.get('kind_name')) or None,
            'postTime': item.get('posttime'),
        })
    return rows


def fetch_591(browser):
    logs, rows, seen = [], [], set()
    context = browser.new_context(user_agent=UA, viewport={'width': 1280, 'height': 900}, locale='zh-TW', timezone_id='Asia/Taipei')
    page = context.new_page()
    captured = []
    captured_urls = []

    def on_response(response):
        url = response.url
        if 'bff-house.591.com.tw' not in url or '/rent/list' not in url:
            return
        captured_urls.append(f'{response.status} {url}')
        if response.status != 200:
            return
        try:
            data = response.json()
        except Exception:
            return
        if isinstance(data, dict) and data.get('status') in (1, '1', True):
            captured.append((url, data))

    page.on('response', on_response)
    try:
        page.goto('https://rent.591.com.tw/list?region=3&section=26', wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(6000)
    except Exception as exc:
        logs.append(f'591租屋官方列表載入：{type(exc).__name__}')

    if not captured:
        logs.append('591租屋沒有捕捉到成功的官方 rent/list API')
        logs.extend(['API ' + x for x in captured_urls[-10:]])
        context.close()
        return [], False, logs

    api_url, payload = captured[-1]
    inner = payload.get('data') or {}
    total_rows = int(inner.get('total') or 0)
    items = inner.get('items') or []
    rows.extend(parse_591_items(items, seen))
    logs.append(f'591租屋官方 API 第1頁：原始 {len(items)}／指定路段 {len(rows)}／total={total_rows}')

    offset = len(items) if items else 30
    page_no = 2
    while items and page_no <= 70 and (not total_rows or offset < total_rows):
        next_url = mutate_591_url(api_url, offset, total_rows)
        try:
            result = browser_json(page, next_url)
            if result.get('status') != 200:
                logs.append(f'591租屋第{page_no}頁 HTTP {result.get("status")}')
                break
            data = json.loads(result.get('text') or '{}')
        except Exception as exc:
            logs.append(f'591租屋第{page_no}頁 {type(exc).__name__}')
            break
        if data.get('status') not in (1, '1', True):
            logs.append(f'591租屋第{page_no}頁 status={data.get("status")}')
            break
        inner = data.get('data') or {}
        items = inner.get('items') or []
        if not items:
            break
        before = len(rows)
        rows.extend(parse_591_items(items, seen))
        logs.append(f'591租屋官方 API 第{page_no}頁：原始 {len(items)}／指定路段新增 {len(rows)-before}')
        offset += len(items)
        page_no += 1

    context.close()
    return rows, True, logs


def clean_sinyi_title(text):
    text = norm(text)
    text = re.sub(r'^店長推薦\s*\d+\s*', '', text)
    parts = re.split(r'\s+成屋\s+', text, maxsplit=1)
    return parts[0].strip()[:120] if parts else text[:120]


def fetch_sinyi(browser):
    logs, rows, seen = [], [], set()
    context = browser.new_context(user_agent=UA, viewport={'width': 1280, 'height': 1000}, locale='zh-TW', timezone_id='Asia/Taipei')
    page = context.new_page()
    url = 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/index.html'

    for page_no in range(1, 9):
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2500)
        except Exception as exc:
            logs.append(f'信義租屋第{page_no}頁載入 {type(exc).__name__}')
            break

        cards = page.evaluate("""() => [...document.querySelectorAll('a[href*="/rent/list/"][href*="/houseno/"]')].map(a=>({href:a.href,text:(a.innerText||'').replace(/\s+/g,' ').trim()}))""")
        added = 0
        for card in cards:
            href = norm(card.get('href'))
            text = norm(card.get('text'))
            m = re.search(r'/houseno/([^/?#]+)', href)
            if not m:
                continue
            hid = m.group(1)
            if hid in seen:
                continue
            road = road_for(text)
            if not road:
                continue
            seen.add(hid)
            rent_match = re.search(r'([\d,]+)\s*元/月', text)
            area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', text)
            addr_match = re.search(r'新北市板橋區[^ ]*(?:中山路二段|三民路二段|三民路一段|光復街|萬安街|林森街|翠華街)[^ ]*', norm(text))
            rows.append({
                'id': f'信義租屋:{hid}',
                'source': '信義房屋',
                'houseId': hid,
                'road': road,
                'title': clean_sinyi_title(text),
                'address': addr_match.group(0) if addr_match else road,
                'rent': float(rent_match.group(1).replace(',', '')) if rent_match else None,
                'size': float(area_match.group(1)) if area_match else None,
                'url': href,
            })
            added += 1
        logs.append(f'信義租屋第{page_no}頁：案件卡 {len(cards)}／指定路段新增 {added}')

        next_text = str(page_no + 1)
        next_href = page.evaluate("""(nextText) => {
          const links=[...document.querySelectorAll('a[href]')];
          const a=links.find(x => (x.innerText||'').trim()===nextText && x.href.includes('/rent/list/NewTaipei-city/220-zip/'));
          return a ? a.href : null;
        }""", next_text)
        if not next_href or next_href == url:
            break
        url = next_href

    context.close()
    if not rows:
        logs.append('信義官方租屋頁有載入，但指定路段案件卡解析為 0')
    return rows, bool(rows), logs


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--disable-dev-shm-usage'])
        try:
            r591, r591_ok, r591_logs = fetch_591(browser)
            sinyi, sinyi_ok, sinyi_logs = fetch_sinyi(browser)
        finally:
            browser.close()

    listings = r591 + sinyi
    payload = {
        'updatedAt': now_iso(),
        'previewOnly': True,
        'market': 'rent',
        'watchRoads': list(WATCH_ROADS),
        'runs': {
            '591': {'status': 'ok' if r591_ok else 'error', 'totalCount': len(r591), 'logs': r591_logs},
            '信義房屋': {'status': 'ok' if sinyi_ok else 'error', 'totalCount': len(sinyi), 'logs': sinyi_logs},
        },
        'counts': {
            'total': len(listings),
            'sinyi': len(sinyi),
            '591': len(r591),
            'roads': {road: sum(1 for x in listings if x.get('road') == road) for road in WATCH_ROADS},
        },
        'listings': listings,
        'elapsedSeconds': round(time.time() - started, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'updatedAt': payload['updatedAt'],
        'counts': payload['counts'],
        'runs': {k:v['status'] for k,v in payload['runs'].items()},
        'elapsedSeconds': payload['elapsedSeconds'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
