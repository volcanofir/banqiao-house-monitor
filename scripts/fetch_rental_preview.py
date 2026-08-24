import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

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


def pick(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ''):
            return d.get(k)
    return None


def find_listing_array(obj):
    best = []
    best_score = -1
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            score = sum(
                1 for x in cur
                if isinstance(x, dict)
                and (x.get('houseNo') or x.get('houseId') or x.get('address'))
                and (x.get('name') or x.get('title'))
            )
            if score > best_score:
                best = cur
                best_score = score
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
        elif isinstance(cur, dict):
            stack.extend(cur.values())
    return best if best_score > 0 else []


def fetch_sinyi():
    rows, logs, seen = [], [], set()
    success_pages = 0
    for page in range(1, 9):
        candidates = [
            f'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/publish-desc/{page}',
            f'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/{page}',
            'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/index.html' if page == 1 else '',
        ]
        parsed = None
        used_url = None
        for url in [x for x in candidates if x]:
            try:
                r = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.sinyi.com.tw/'}, timeout=25)
            except Exception as exc:
                logs.append(f'信義第{page}頁 {type(exc).__name__}')
                continue
            if r.status_code != 200:
                logs.append(f'信義第{page}頁 HTTP {r.status_code}')
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            script = soup.find('script', id='__NEXT_DATA__')
            if not script or not script.string:
                continue
            try:
                payload = json.loads(script.string)
            except Exception:
                continue
            arr = find_listing_array(payload)
            if arr:
                parsed = arr
                used_url = url
                break
        if not parsed:
            if page == 1:
                logs.append('信義租屋未取得結構化列表')
            break

        success_pages += 1
        before_seen = set(seen)
        page_ids = set()
        added = 0
        for item in parsed:
            if not isinstance(item, dict):
                continue
            hid = norm(pick(item, 'houseNo', 'houseId', 'id', 'objectId'))
            title = norm(pick(item, 'name', 'title', 'caseName'))
            address = norm(pick(item, 'address', 'fullAddress', 'addr'))
            road = road_for(address)
            if not hid or not title:
                continue
            page_ids.add(hid)
            if not road or hid in seen:
                continue
            seen.add(hid)
            rent = num(pick(item, 'rentPrice', 'rent', 'price', 'totalPrice', 'amount'))
            area = num(pick(item, 'areaBuilding', 'area', 'buildingArea'))
            updated = pick(item, 'publishTime', 'updateTime', 'createTime', 'lastUpdateTime')
            rows.append({
                'id': f'信義租屋:{hid}',
                'source': '信義房屋',
                'houseId': hid,
                'road': road,
                'title': title,
                'address': address,
                'rent': rent,
                'size': area,
                'url': f'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/houseno/{quote(hid)}',
                'sourceUpdatedAt': updated,
            })
            added += 1
        logs.append(f'信義租屋第{page}頁：結構化 {len(parsed)} 筆／指定路段新增 {added}，來源 {used_url}')
        if page > 1 and page_ids and page_ids.issubset(before_seen):
            logs.append(f'信義租屋第{page}頁與前頁完全重複，停止翻頁')
            break
        if len(parsed) < 20:
            break
    return rows, success_pages > 0, logs


def fetch_591():
    api = 'https://bff-house.591.com.tw/v3/web/rent/list'
    session = requests.Session()
    headers = {
        **HEADERS,
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://rent.591.com.tw/',
        'Origin': 'https://rent.591.com.tw',
    }
    rows, logs, seen = [], [], set()
    total_rows = 0
    successful_pages = 0
    first_page_districts = set()

    for page in range(60):
        first_row = page * 30
        params = {
            'region': '3',
            'section': '26',
            'firstRow': first_row,
            'totalRows': total_rows,
            'order': 'posttime',
            'orderType': 'desc',
        }
        payload = None
        for attempt in range(1, 4):
            try:
                r = session.get(api, params=params, headers=headers, timeout=20)
                if r.status_code == 200:
                    payload = r.json()
                    break
                logs.append(f'591租屋 API 第{page+1}頁第{attempt}次 HTTP {r.status_code}')
            except Exception as exc:
                logs.append(f'591租屋 API 第{page+1}頁第{attempt}次 {type(exc).__name__}')
            time.sleep(0.5 * attempt)
        if not isinstance(payload, dict):
            logs.append(f'591租屋 API 第{page+1}頁未取得 JSON，停止翻頁')
            break
        if payload.get('status') not in (1, '1', True):
            logs.append(f"591租屋 API 第{page+1}頁 status={payload.get('status')}，停止翻頁")
            break

        inner = payload.get('data') or {}
        if page == 0:
            total_rows = int(inner.get('total') or 0)
        items = inner.get('items') or []
        if not isinstance(items, list) or not items:
            logs.append(f'591租屋 API 第{page+1}頁 0 筆，抓取完成')
            break
        successful_pages += 1
        added = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            hid = norm(item.get('id'))
            title = norm(item.get('title'))
            address = norm(item.get('address'))
            section_name = norm(item.get('section_name'))
            if page == 0 and section_name:
                first_page_districts.add(section_name)
            combined = address if '板橋區' in address else f'{section_name}-{address}'
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
            added += 1
        logs.append(f'591租屋 API 第{page+1}頁：原始 {len(items)}／指定路段新增 {added}／total={total_rows}')

        if len(items) < 30:
            break
        if total_rows and first_row + len(items) >= total_rows:
            break

    if successful_pages and first_page_districts and first_page_districts != {'板橋區'}:
        logs.append('591租屋 section=26 回傳非單一板橋區，視為篩選異常')
        return [], False, logs
    return rows, successful_pages > 0, logs


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    sinyi, sinyi_ok, sinyi_logs = fetch_sinyi()
    r591, r591_ok, r591_logs = fetch_591()

    listings = sinyi + r591
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
