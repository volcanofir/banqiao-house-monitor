import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path('docs/preview/rental-data.json')

WATCH_ROADS = {
    '板橋區中山路二段': ('中山路二段', '中山路2段'),
    '板橋區三民路一段': ('三民路一段', '三民路1段'),
    '板橋區光復街': ('光復街',),
    '板橋區三民路二段': ('三民路二段', '三民路2段'),
    '板橋區萬安街': ('萬安街',),
    '板橋區翠華街': ('翠華街',),
    '板橋區林森街': ('林森街',),
}

SEARCH_591 = {
    '板橋區中山路二段': 'https://rent.591.com.tw/list?region=3&section=26&keywords=中山路二段',
    '板橋區三民路一段': 'https://rent.591.com.tw/list?region=3&section=26&keywords=三民路一段',
    '板橋區光復街': 'https://rent.591.com.tw/list?region=3&section=26&keywords=光復街',
    '板橋區三民路二段': 'https://rent.591.com.tw/list?region=3&section=26&keywords=三民路二段',
    '板橋區萬安街': 'https://rent.591.com.tw/list?region=3&section=26&keywords=萬安街',
    '板橋區翠華街': 'https://rent.591.com.tw/list?region=3&section=26&keywords=翠華街',
    '板橋區林森街': 'https://rent.591.com.tw/list?region=3&section=26&keywords=林森街',
}

SEARCH_SINYI = {
    '板橋區中山路二段': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/中山路二段-keyword/index.html',
    '板橋區三民路一段': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/三民路一段-keyword/index.html',
    '板橋區三民路二段': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/三民路二段-keyword/index.html',
    '板橋區光復街': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/光復街-keyword/index.html',
    '板橋區萬安街': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/萬安街-keyword/index.html',
    '板橋區翠華街': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/翠華街-keyword/index.html',
    '板橋區林森街': 'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/林森街-keyword/index.html',
}

HEADERS = {
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.7',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def norm(v):
    text = '' if v is None else str(v)
    text = re.sub(r'\s+', ' ', text).strip().replace('臺', '台')
    return text.replace('中山路2段', '中山路二段').replace('三民路1段', '三民路一段').replace('三民路2段', '三民路二段')


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'[\d,]+(?:\.\d+)?', norm(v))
    return float(m.group(0).replace(',', '')) if m else None


def road_text_matches(text, road):
    text = norm(text)
    return '板橋區' in text and any(alias in text for alias in WATCH_ROADS[road])


def dedupe(rows):
    out, seen = [], set()
    for row in rows:
        key = row.get('id')
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def choose_card_text(anchor, road):
    best = ''
    node = anchor
    for _ in range(8):
        node = getattr(node, 'parent', None)
        if node is None or not hasattr(node, 'get_text'):
            break
        text = norm(node.get_text(' ', strip=True))
        if not road_text_matches(text, road):
            continue
        if '元/月' not in text:
            continue
        if not best or len(text) < len(best):
            best = text
    return best


def fetch_sinyi():
    rows, logs = [], []
    successful_pages = 0
    session = requests.Session()

    for road, url in SEARCH_SINYI.items():
        try:
            response = session.get(url, headers={**HEADERS, 'Referer': 'https://www.sinyi.com.tw/'}, timeout=30)
        except Exception as exc:
            logs.append(f'{road} 信義租屋連線失敗：{type(exc).__name__}')
            continue
        if response.status_code != 200:
            logs.append(f'{road} 信義租屋 HTTP {response.status_code}')
            continue
        successful_pages += 1
        soup = BeautifulSoup(response.text, 'html.parser')
        before = len(rows)
        road_ids = set()
        for anchor in soup.find_all('a', href=True):
            href = anchor.get('href') or ''
            m = re.search(r'/houseno/([A-Za-z0-9_-]+)', href)
            if not m:
                continue
            house_id = m.group(1)
            if house_id in road_ids:
                continue
            card_text = choose_card_text(anchor, road)
            if not card_text:
                continue
            road_ids.add(house_id)
            title = norm(anchor.get_text(' ', strip=True))
            if not title or title in ('快速收藏', '預約看屋') or len(title) > 100:
                title_match = re.search(r'(?:店長推薦\s*\d+\s*)?(.{2,45}?)(?:\s+成屋|\s+預售屋|\s+\d+(?:\.\d+)?坪)', card_text)
                title = norm(title_match.group(1)) if title_match else f'信義租屋 {house_id}'
            rents = [float(x.replace(',', '')) for x in re.findall(r'([\d,]+)\s*元/月', card_text)]
            area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', card_text)
            updated_match = re.search(r'更新日期[:：]\s*([0-9/ :]+)', card_text)
            rows.append({
                'id': f'信義租屋:{house_id}',
                'source': '信義房屋',
                'houseId': house_id,
                'road': road,
                'title': title,
                'address': road,
                'rent': rents[0] if rents else None,
                'size': float(area_match.group(1)) if area_match else None,
                'url': urljoin('https://www.sinyi.com.tw', href),
                'sourceUpdatedAt': norm(updated_match.group(1)) if updated_match else None,
            })
        logs.append(f'{road} 信義租屋：HTTP 200／解析 {len(rows)-before} 筆')

    rows = dedupe(rows)
    # The provided exact keyword pages are the source of truth. A reachable page with
    # zero matching cards is valid; the source is considered failed only if all seven
    # pages themselves failed.
    return rows, successful_pages == len(SEARCH_SINYI), logs


def mutate_api_url(api_url, first_row, total_rows):
    parsed = urlparse(api_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params['firstRow'] = str(first_row)
    if total_rows:
        params['totalRows'] = str(total_rows)
    params['timestamp'] = str(int(time.time() * 1000))
    return urlunparse(parsed._replace(query=urlencode(params)))


def browser_fetch_json(page, url):
    return page.evaluate(
        """async (url) => {
          const r = await fetch(url, {credentials: 'include'});
          const text = await r.text();
          return {status:r.status, text};
        }""",
        url,
    )


def rental_items(payload):
    if not isinstance(payload, dict) or payload.get('status') not in (1, '1', True):
        return [], 0
    data = payload.get('data') or {}
    items = data.get('items') or []
    if not isinstance(items, list):
        items = []
    total = int(data.get('total') or data.get('totalRows') or 0)
    return items, total


def parse_591_items(items, road):
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        house_id = norm(item.get('id') or item.get('post_id') or item.get('postId'))
        title = norm(item.get('title') or item.get('name'))
        address = norm(item.get('address') or item.get('address_new'))
        section = norm(item.get('section_name') or item.get('section'))
        combined = address if '板橋區' in address else f'{section}-{address}'
        if not house_id or not road_text_matches(combined, road):
            continue
        url = norm(item.get('url'))
        if not url.startswith('http'):
            url = f'https://rent.591.com.tw/{house_id}'
        rows.append({
            'id': f'591租屋:{house_id}',
            'source': '591',
            'houseId': house_id,
            'road': road,
            'title': title or f'591租屋 {house_id}',
            'address': combined,
            'rent': num(item.get('price')),
            'size': num(item.get('area') or item.get('area_name')),
            'url': url,
            'floor': norm(item.get('floor_name')) or None,
            'kind': norm(item.get('kind_name')) or None,
            'postTime': item.get('posttime'),
        })
    return dedupe(rows)


def fetch_591():
    rows, logs = [], []
    successful_roads = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--disable-dev-shm-usage'])
        context = browser.new_context(
            user_agent=HEADERS['User-Agent'],
            viewport={'width': 390, 'height': 844},
            locale='zh-TW',
            timezone_id='Asia/Taipei',
        )
        try:
            for road, search_url in SEARCH_591.items():
                page = context.new_page()
                captured = []

                def on_response(response):
                    if 'bff-house.591.com.tw' not in response.url or '/rent/list' not in response.url or response.status != 200:
                        return
                    try:
                        payload = response.json()
                    except Exception:
                        return
                    items, _ = rental_items(payload)
                    if items:
                        captured.append((response.url, payload))

                page.on('response', on_response)
                try:
                    page.goto(search_url, wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(4500)
                except Exception as exc:
                    logs.append(f'{road} 591租屋搜尋頁載入失敗：{type(exc).__name__}')

                if not captured:
                    logs.append(f'{road} 591租屋：未攔截到官方租屋列表 API')
                    page.close()
                    continue

                api_url, payload = captured[-1]
                road_rows = []
                seen = set()
                page_no = 1
                while page_no <= 20:
                    items, total_rows = rental_items(payload)
                    parsed = parse_591_items(items, road)
                    new_rows = [x for x in parsed if x['id'] not in seen]
                    for row in new_rows:
                        seen.add(row['id'])
                        road_rows.append(row)
                    logs.append(f'{road} 591租屋第{page_no}頁：API {len(items)} 筆／路段符合 {len(parsed)}／新增 {len(new_rows)}')
                    if not items or len(items) < 30 or (page_no > 1 and not new_rows):
                        break
                    next_first = page_no * 30
                    if total_rows and next_first >= total_rows:
                        break
                    page_no += 1
                    next_url = mutate_api_url(api_url, next_first, total_rows)
                    try:
                        result = browser_fetch_json(page, next_url)
                        if result.get('status') != 200:
                            logs.append(f'{road} 591租屋第{page_no}頁 HTTP {result.get("status")}')
                            break
                        payload = json.loads(result.get('text') or '{}')
                    except Exception as exc:
                        logs.append(f'{road} 591租屋第{page_no}頁讀取失敗：{type(exc).__name__}')
                        break

                rows.extend(road_rows)
                successful_roads += 1
                logs.append(f'{road} 591租屋完整成功，共 {len(road_rows)} 筆')
                page.close()
        finally:
            context.close()
            browser.close()

    rows = dedupe(rows)
    return rows, successful_roads == len(SEARCH_591), logs


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    sinyi, sinyi_ok, sinyi_logs = fetch_sinyi()
    try:
        r591, r591_ok, r591_logs = fetch_591()
    except Exception as exc:
        r591, r591_ok, r591_logs = [], False, [f'591租屋 Playwright 啟動失敗：{type(exc).__name__}: {exc}']

    listings = dedupe(sinyi + r591)
    counts = {
        'total': len(listings),
        'sinyi': len(sinyi),
        '591': len(r591),
        'roads': {road: sum(1 for x in listings if x.get('road') == road) for road in WATCH_ROADS},
    }
    payload = {
        'updatedAt': now_iso(),
        'previewOnly': True,
        'market': 'rent',
        'watchRoads': list(WATCH_ROADS),
        'searchPages': {'591': SEARCH_591, '信義房屋': SEARCH_SINYI},
        'runs': {
            '591': {'status': 'ok' if r591_ok else 'error', 'totalCount': len(r591), 'logs': r591_logs},
            '信義房屋': {'status': 'ok' if sinyi_ok else 'error', 'totalCount': len(sinyi), 'logs': sinyi_logs},
        },
        'counts': counts,
        'listings': listings,
        'elapsedSeconds': round(time.time() - started, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'updatedAt': payload['updatedAt'],
        'counts': counts,
        'runs': {k: v['status'] for k, v in payload['runs'].items()},
        'elapsedSeconds': payload['elapsedSeconds'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
