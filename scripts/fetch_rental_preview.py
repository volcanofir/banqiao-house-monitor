import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

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
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1',
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
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            score = sum(1 for x in cur if isinstance(x, dict) and (x.get('houseNo') or x.get('address')) and (x.get('name') or x.get('title')))
            if score > len(best):
                best = cur
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
        elif isinstance(cur, dict):
            stack.extend(cur.values())
    return best


def fetch_sinyi():
    rows, logs, seen = [], [], set()
    success_pages = 0
    # Fetch the full Banqiao rental result set, then strictly filter the seven roads.
    for page in range(1, 9):
        candidates = [
            f'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/publish-desc/{page}',
            f'https://www.sinyi.com.tw/rent/list/NewTaipei-city/220-zip/{page}',
        ]
        parsed = None
        used_url = None
        for url in candidates:
            try:
                r = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.sinyi.com.tw/'}, timeout=30)
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
        page_ids = set()
        added = 0
        for item in parsed:
            if not isinstance(item, dict):
                continue
            hid = norm(pick(item, 'houseNo', 'houseId', 'id', 'objectId'))
            title = norm(pick(item, 'name', 'title', 'caseName'))
            address = norm(pick(item, 'address', 'fullAddress', 'addr'))
            road = road_for(address)
            if not hid or not title or not road:
                continue
            page_ids.add(hid)
            if hid in seen:
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
                'url': f'https://www.sinyi.com.tw/rent/house/{quote(hid)}?breadcrumb=list',
                'sourceUpdatedAt': updated,
            })
            added += 1
        logs.append(f'信義租屋第{page}頁：結構化 {len(parsed)} 筆／指定路段新增 {added}，來源 {used_url}')
        # Duplicate page means the alternate route is not actually paginating.
        if page > 1 and page_ids and page_ids.issubset(seen - page_ids):
            break
        if len(parsed) < 20:
            break
    return rows, success_pages > 0, logs


async def fetch_591():
    rows, logs, seen = [], [], set()
    page_success = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome', headless=True, args=['--disable-dev-shm-usage'])
        context = await browser.new_context(
            user_agent=HEADERS['User-Agent'],
            viewport={'width': 390, 'height': 844},
            locale='zh-TW',
            timezone_id='Asia/Taipei',
        )
        try:
            for page_no in range(1, 61):
                url = f'https://rent.591.com.tw/list?region=3&section=26&page={page_no}'
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await page.wait_for_timeout(2200)
                    # Pull detail links together with a compact ancestor-card text. The
                    # current 591 list is rendered in the DOM even when class names vary.
                    raw = await page.evaluate("""() => {
                      const out=[];
                      const links=[...document.querySelectorAll('a[href]')];
                      for(const a of links){
                        const href=a.href||'';
                        const m=href.match(/(?:rent\/)?(\d{6,})(?:[/?#]|$)/);
                        if(!m) continue;
                        let node=a;
                        let chosen=a;
                        for(let i=0;i<7 && node;i++,node=node.parentElement){
                          const t=(node.innerText||'').replace(/\s+/g,' ').trim();
                          if(t.length>=45 && t.length<=1600){chosen=node;}
                        }
                        out.push({id:m[1],href,text:(chosen.innerText||'').replace(/\s+/g,' ').trim(),anchor:(a.innerText||'').replace(/\s+/g,' ').trim()});
                      }
                      return out;
                    }""")
                except Exception as exc:
                    logs.append(f'591租屋第{page_no}頁 {type(exc).__name__}')
                    await page.close()
                    if page_no == 1:
                        continue
                    break
                await page.close()
                page_success += 1
                page_ids = set()
                added = 0
                for item in raw:
                    text = norm(item.get('text'))
                    road = road_for(text)
                    hid = norm(item.get('id'))
                    if not road or not hid:
                        continue
                    page_ids.add(hid)
                    if hid in seen:
                        continue
                    seen.add(hid)
                    rent_match = re.search(r'([\d,]{3,})\s*元/月', text)
                    area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', text)
                    addr_match = re.search(r'板橋區[-－]?[^ ]*(?:中山路二段|三民路二段|三民路一段|光復街|萬安街|林森街|翠華街)[^ ]*', text)
                    title = norm(item.get('anchor'))
                    if not title or title.isdigit() or len(title) > 120:
                        # Prefer the text before the first known feature/size marker.
                        title = re.split(r'(?:整層住家|獨立套房|分租套房|雅房|車位|其他|\d+(?:\.\d+)?坪)', text, maxsplit=1)[0].strip()
                    rows.append({
                        'id': f'591租屋:{hid}',
                        'source': '591',
                        'houseId': hid,
                        'road': road,
                        'title': title[:120] or f'591租屋 {hid}',
                        'address': addr_match.group(0) if addr_match else road,
                        'rent': float(rent_match.group(1).replace(',', '')) if rent_match else None,
                        'size': float(area_match.group(1)) if area_match else None,
                        'url': item.get('href'),
                    })
                    added += 1
                logs.append(f'591租屋第{page_no}頁：連結 {len(raw)}／指定路段新增 {added}')
                if page_no > 1 and not page_ids:
                    # Keep going a little because sparse roads may miss one page, but stop
                    # after the district result pages begin returning no usable listings.
                    if page_no >= 8:
                        break
                if page_no >= 2 and len(raw) == 0:
                    break
        finally:
            await context.close()
            await browser.close()
    return rows, page_success > 0, logs


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    sinyi, sinyi_ok, sinyi_logs = fetch_sinyi()
    try:
        r591, r591_ok, r591_logs = asyncio.run(fetch_591())
    except Exception as exc:
        r591, r591_ok, r591_logs = [], False, [f'591租屋啟動失敗：{type(exc).__name__}: {exc}']

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
    print(json.dumps({'updatedAt': payload['updatedAt'], 'counts': counts, 'runs': {k:v['status'] for k,v in payload['runs'].items()}, 'elapsedSeconds': payload['elapsedSeconds']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
