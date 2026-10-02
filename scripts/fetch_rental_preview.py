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

SEARCH_RAKUYA = {
    road: f"https://rent.rakuya.com.tw/result?zipcode=220&keyword={aliases[0]}"
    for road, aliases in WATCH_ROADS.items()
}

SEARCH_HOUSEPRICE = {
    road: f"https://rent.houseprice.tw/list/21_usage/15_zip/{aliases[0]}_kw/?p=1"
    for road, aliases in WATCH_ROADS.items()
}

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def norm(v):
    text = '' if v is None else str(v)
    text = re.sub(r'\s+', ' ', text).strip().replace('臺', '台')
    return text.replace('中山路2段', '中山路二段').replace('三民路1段', '三民路一段').replace('三民路2段', '三民路二段')


def num(v):
    m = re.search(r'[\d,]+(?:\.\d+)?', norm(v))
    return float(m.group(0).replace(',', '')) if m else None


def dedupe(rows):
    out, seen = [], set()
    for row in rows:
        key = row.get('id')
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def with_page(url, page_no):
    if page_no <= 1:
        return url
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params['page'] = str(page_no)
    return urlunparse(parsed._replace(query=urlencode(params)))


def load_page(page, url, wait_ms=2500, attempts=2):
    last = None
    for attempt in range(attempts):
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(wait_ms)
            status = response.status if response else 0
            if status == 200:
                return True, status
            last = status
        except Exception as exc:
            last = type(exc).__name__
        if attempt + 1 < attempts:
            page.wait_for_timeout(1200)
    return False, last


def extract_591_dom(page, road):
    keyword = WATCH_ROADS[road][0]
    raw = page.evaluate(
        """({keyword}) => {
          const out=[];
          const seen=new Set();
          for(const a of document.querySelectorAll('a[href]')){
            let u; try{u=new URL(a.href)}catch(e){continue}
            if(u.hostname!=='rent.591.com.tw' || !/^\/\d{6,}$/.test(u.pathname)) continue;
            const id=u.pathname.slice(1);
            let node=a, best='';
            for(let i=0;i<9 && node;i++,node=node.parentElement){
              const t=(node.innerText||'').replace(/\s+/g,' ').trim();
              if(t.includes(keyword) && t.includes('元/月') && t.length>=25 && t.length<=1800){
                if(!best || t.length<best.length) best=t;
              }
            }
            if(!best) continue;
            const anchor=(a.innerText||'').replace(/\s+/g,' ').trim();
            const key=id+'|'+anchor;
            if(seen.has(key)) continue;
            seen.add(key);
            out.push({id,href:u.href,anchor,text:best});
          }
          return out;
        }""",
        {'keyword': keyword},
    )
    grouped = {}
    for item in raw:
        grouped.setdefault(item['id'], []).append(item)
    rows = []
    for house_id, items in grouped.items():
        items.sort(key=lambda x: (0 if x.get('anchor') else 1, len(x.get('text') or '')))
        item = items[0]
        text = norm(item.get('text'))
        title = norm(item.get('anchor'))
        if not title or title in ('優選好屋', '精選') or len(title) > 120:
            title = f'591租屋 {house_id}'
        rent_match = re.search(r'([\d,]+)\s*元/月', text)
        area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', text)
        floor_match = re.search(r'((?:B?\d+F|頂層加蓋)(?:~(?:B?\d+F))?/\d+F)', text)
        rows.append({
            'id': f'591租屋:{house_id}',
            'source': '591',
            'houseId': house_id,
            'road': road,
            'title': title,
            'address': road,
            'rent': float(rent_match.group(1).replace(',', '')) if rent_match else None,
            'size': float(area_match.group(1)) if area_match else None,
            'url': item.get('href'),
            'floor': norm(floor_match.group(1)) if floor_match else None,
        })
    return dedupe(rows)


def extract_sinyi_dom(page, road):
    keyword = WATCH_ROADS[road][0]
    raw = page.evaluate(
        """({keyword}) => {
          const out=[];
          const seen=new Set();
          for(const a of document.querySelectorAll('a[href]')){
            const href=a.href||'';
            const m=href.match(/\/houseno\/([A-Za-z0-9_-]+)/);
            if(!m) continue;
            const id=m[1];
            let node=a, best='';
            for(let i=0;i<9 && node;i++,node=node.parentElement){
              const t=(node.innerText||'').replace(/\s+/g,' ').trim();
              if(t.includes(keyword) && t.includes('元/月') && t.length>=25 && t.length<=2200){
                if(!best || t.length<best.length) best=t;
              }
            }
            if(!best || seen.has(id)) continue;
            seen.add(id);
            out.push({id,href,anchor:(a.innerText||'').replace(/\s+/g,' ').trim(),text:best});
          }
          return out;
        }""",
        {'keyword': keyword},
    )
    rows = []
    for item in raw:
        text = norm(item.get('text'))
        house_id = item.get('id')
        title_match = re.search(r'(?:店長推薦\s*\d+\s*)?(.{2,50}?)(?:\s+成屋|\s+預售屋|\s+\d+(?:\.\d+)?坪)', text)
        title = norm(title_match.group(1)) if title_match else norm(item.get('anchor'))
        if not title or len(title) > 120:
            title = f'信義租屋 {house_id}'
        rent_match = re.search(r'([\d,]+)\s*元/月', text)
        area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', text)
        floor_match = re.search(r'(B?\d+/\d+樓)', text)
        updated_match = re.search(r'更新日期[:：]\s*([0-9/ :]+)', text)
        rows.append({
            'id': f'信義租屋:{house_id}',
            'source': '信義房屋',
            'houseId': house_id,
            'road': road,
            'title': title,
            'address': road,
            'rent': float(rent_match.group(1).replace(',', '')) if rent_match else None,
            'size': float(area_match.group(1)) if area_match else None,
            'url': item.get('href'),
            'floor': norm(floor_match.group(1)) if floor_match else None,
            'sourceUpdatedAt': norm(updated_match.group(1)) if updated_match else None,
        })
    return dedupe(rows)



def extract_rakuya_dom(page, road):
    keyword = WATCH_ROADS[road][0]
    raw = page.evaluate(
        """({keyword}) => {
          const out=[];
          const seen=new Set();
          for(const a of document.querySelectorAll('a[href]')){
            let u; try{u=new URL(a.href)}catch(e){continue}
            if(u.hostname!=='rent.rakuya.com.tw' || !/^\/item\/[A-Za-z0-9]+/.test(u.pathname)) continue;
            const m=u.pathname.match(/^\/item\/([A-Za-z0-9]+)/);
            if(!m) continue;
            const id=m[1];
            let node=a, best='';
            for(let i=0;i<9 && node;i++,node=node.parentElement){
              const t=(node.innerText||'').replace(/\s+/g,' ').trim();
              if(t.includes(keyword) && /[\d,]+\s*元/.test(t) && t.length>=20 && t.length<=2200){
                if(!best || t.length<best.length) best=t;
              }
            }
            if(!best || seen.has(id)) continue;
            seen.add(id);
            out.push({id,href:u.href,text:best});
          }
          return out;
        }""",
        {'keyword': keyword},
    )

    rows = []
    for item in raw:
        text = norm(item.get('text'))
        house_id = item.get('id')
        road_label = road.replace('板橋區', '')

        # Rakuya cards are rendered as: title + 板橋區 + road + type/floor/area/rent.
        pos = text.find('板橋區')
        title = norm(text[:pos]) if pos > 0 else ''
        title = re.sub(r'^(追蹤|立即預約)\s*', '', title).strip()
        if not title or len(title) > 120:
            title = f'樂屋租屋 {house_id}'

        rent_values = re.findall(r'([\d,]+)\s*元', text)
        rent = float(rent_values[-1].replace(',', '')) if rent_values else None

        area_match = re.search(r'(?:主建|建坪|坪數)?\s*(\d+(?:\.\d+)?)\s*坪', text)
        floor_match = re.search(r'((?:B?\d+)(?:~(?:B?\d+))?/\d+樓)', text)
        updated_match = re.search(
            r'((?:\d+\s*(?:分鐘|小時|天|個月|月)|剛剛|今天|昨日|昨天)前?)\s*更新',
            text,
        )

        rows.append({
            'id': f'樂屋租屋:{house_id}',
            'source': '樂屋網',
            'houseId': house_id,
            'road': road,
            'title': title,
            'address': road,
            'rent': rent,
            'size': float(area_match.group(1)) if area_match else None,
            'url': item.get('href'),
            'floor': norm(floor_match.group(1)) if floor_match else None,
            'sourceUpdatedRaw': norm(updated_match.group(1)) if updated_match else None,
        })
    return dedupe(rows)



def houseprice_page_url(base_url, page_no):
    return re.sub(r'([?&])p=\\d+', rf'\\1p={page_no}', base_url)


def extract_houseprice_dom(page, road):
    keyword = WATCH_ROADS[road][0]
    raw = page.evaluate(
        """({keyword}) => {
          const out=[];
          const seen=new Set();
          for(const a of document.querySelectorAll('a[href]')){
            let u; try{u=new URL(a.href)}catch(e){continue}
            if(u.hostname!=='rent.houseprice.tw') continue;
            if(u.pathname.startsWith('/list/')) continue;
            if(u.pathname==='/' || u.pathname.length<4) continue;
            let node=a, best='';
            for(let i=0;i<10 && node;i++,node=node.parentElement){
              const t=(node.innerText||'').replace(/\\s+/g,' ').trim();
              if(t.includes(keyword) && /[\\d,]+\\s*元/.test(t) && t.length>=20 && t.length<=2600){
                if(!best || t.length<best.length) best=t;
              }
            }
            if(!best) continue;
            const href=u.origin+u.pathname+u.search;
            if(seen.has(href)) continue;
            seen.add(href);
            out.push({href,anchor:(a.innerText||'').replace(/\\s+/g,' ').trim(),text:best});
          }
          return out;
        }""",
        {'keyword': keyword},
    )
    rows=[]
    for item in raw:
        text=norm(item.get('text'))
        href=item.get('href') or ''
        key=re.sub(r'\\W+','-',href).strip('-')
        if not key:
            continue
        title=norm(item.get('anchor'))
        if not title or len(title)>120 or title in ('查看更多','詳細資料','看屋'):
            pos=text.find('板橋區')
            title=norm(text[:pos]) if pos>0 else ''
        if not title or len(title)>120:
            title=f'5168租屋 {key[-24:]}'
        rent_values=re.findall(r'([\\d,]+)\\s*元(?:/月|／月)?',text)
        rent=float(rent_values[-1].replace(',','')) if rent_values else None
        area_match=re.search(r'(\\d+(?:\\.\\d+)?)\\s*坪',text)
        floor_match=re.search(r'((?:B?\\d+)(?:~(?:B?\\d+))?/\\d+樓)',text)
        rows.append({
            'id': f'5168租屋:{key}',
            'source': '5168',
            'houseId': key,
            'road': road,
            'title': title,
            'address': road,
            'rent': rent,
            'size': float(area_match.group(1)) if area_match else None,
            'url': href,
            'floor': norm(floor_match.group(1)) if floor_match else None,
        })
    return dedupe(rows)


def fetch_all():
    rows_591, rows_sinyi, rows_rakuya, rows_houseprice = [], [], [], []
    logs_591, logs_sinyi, logs_rakuya, logs_houseprice = [], [], [], []
    ok_591 = 0
    ok_sinyi = 0
    ok_rakuya = 0
    ok_houseprice = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--disable-dev-shm-usage'])
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 390, 'height': 844},
            locale='zh-TW',
            timezone_id='Asia/Taipei',
        )
        try:
            # 591: exact keyword page, then page=2,3... only while new matching IDs exist.
            for road, base_url in SEARCH_591.items():
                road_rows, seen = [], set()
                page = context.new_page()
                for page_no in range(1, 8):
                    url = with_page(base_url, page_no)
                    loaded, status = load_page(page, url, wait_ms=2200)
                    if not loaded:
                        logs_591.append(f'{road} 591租屋第{page_no}頁載入失敗：{status}')
                        break
                    parsed = extract_591_dom(page, road)
                    new_rows = [x for x in parsed if x['id'] not in seen]
                    for row in new_rows:
                        seen.add(row['id'])
                        road_rows.append(row)
                    logs_591.append(f'{road} 591租屋第{page_no}頁：DOM {len(parsed)}／新增 {len(new_rows)}')
                    if page_no > 1 and not new_rows:
                        break
                    if len(parsed) < 20:
                        break
                if road_rows or loaded:
                    ok_591 += 1
                rows_591.extend(road_rows)
                logs_591.append(f'{road} 591租屋完成，共 {len(road_rows)} 筆')
                page.close()

            # Sinyi: exact keyword page. These road-specific result sets are small,
            # and the first page contains the currently listed matching rentals.
            for road, url in SEARCH_SINYI.items():
                page = context.new_page()
                loaded, status = load_page(page, url, wait_ms=2000, attempts=3)
                if not loaded:
                    logs_sinyi.append(f'{road} 信義租屋載入失敗：{status}')
                    page.close()
                    continue
                parsed = extract_sinyi_dom(page, road)
                rows_sinyi.extend(parsed)
                ok_sinyi += 1
                logs_sinyi.append(f'{road} 信義租屋：DOM {len(parsed)} 筆')
                page.close()

            # Rakuya: one keyword result page currently renders the complete result set
            # for the exact Banqiao road. Only /item/<id> rental links are accepted.
            for road, url in SEARCH_RAKUYA.items():
                page = context.new_page()
                loaded, status = load_page(page, url, wait_ms=2200, attempts=3)
                if not loaded:
                    logs_rakuya.append(f'{road} 樂屋租屋載入失敗：{status}')
                    page.close()
                    continue
                parsed = extract_rakuya_dom(page, road)
                rows_rakuya.extend(parsed)
                ok_rakuya += 1
                logs_rakuya.append(f'{road} 樂屋租屋：DOM {len(parsed)} 筆')
                page.close()

            # 5168: user-confirmed rental keyword URL. Page through ?p=N
            # and only accept cards that contain the exact monitored road keyword.
            for road, base_url in SEARCH_HOUSEPRICE.items():
                road_rows, seen = [], set()
                page = context.new_page()
                loaded_any = False
                for page_no in range(1, 9):
                    url = houseprice_page_url(base_url, page_no)
                    loaded, status = load_page(page, url, wait_ms=2200, attempts=3)
                    if not loaded:
                        logs_houseprice.append(f'{road} 5168租屋第{page_no}頁載入失敗：{status}')
                        break
                    loaded_any = True
                    parsed = extract_houseprice_dom(page, road)
                    new_rows = [x for x in parsed if x['id'] not in seen]
                    for row in new_rows:
                        seen.add(row['id'])
                        road_rows.append(row)
                    logs_houseprice.append(f'{road} 5168租屋第{page_no}頁：DOM {len(parsed)}／新增 {len(new_rows)}')
                    if page_no > 1 and not new_rows:
                        break
                    if not parsed:
                        break
                if loaded_any:
                    ok_houseprice += 1
                rows_houseprice.extend(road_rows)
                logs_houseprice.append(f'{road} 5168租屋完成，共 {len(road_rows)} 筆')
                page.close()
        finally:
            context.close()
            browser.close()

    return (
        dedupe(rows_591), ok_591 == len(SEARCH_591), logs_591,
        dedupe(rows_sinyi), ok_sinyi == len(SEARCH_SINYI), logs_sinyi,
        dedupe(rows_rakuya), ok_rakuya == len(SEARCH_RAKUYA), logs_rakuya,
        dedupe(rows_houseprice), ok_houseprice == len(SEARCH_HOUSEPRICE), logs_houseprice,
    )


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        r591, ok591, logs591, sinyi, oksinyi, logssinyi, rakuya, okrakuya, logsrakuya, houseprice, okhouseprice, logshouseprice = fetch_all()
    except Exception as exc:
        r591, sinyi, rakuya, houseprice = [], [], [], []
        ok591 = oksinyi = okrakuya = okhouseprice = False
        logs591 = [f'租屋瀏覽器啟動失敗：{type(exc).__name__}: {exc}']
        logssinyi = []
        logsrakuya = []
        logshouseprice = []

    listings = dedupe(r591 + sinyi + rakuya + houseprice)
    payload = {
        'updatedAt': now_iso(),
        'previewOnly': True,
        'market': 'rent',
        'watchRoads': list(WATCH_ROADS),
        'searchPages': {'591': SEARCH_591, '信義房屋': SEARCH_SINYI, '樂屋網': SEARCH_RAKUYA, '5168': SEARCH_HOUSEPRICE},
        'runs': {
            '591': {'status': 'ok' if ok591 else 'error', 'totalCount': len(r591), 'logs': logs591},
            '信義房屋': {'status': 'ok' if oksinyi else 'error', 'totalCount': len(sinyi), 'logs': logssinyi},
            '樂屋網': {'status': 'ok' if okrakuya else 'error', 'totalCount': len(rakuya), 'logs': logsrakuya},
            '5168': {'status': 'ok' if okhouseprice else 'error', 'totalCount': len(houseprice), 'logs': logshouseprice},
        },
        'counts': {
            'total': len(listings),
            'sinyi': len(sinyi),
            '591': len(r591),
            'rakuya': len(rakuya),
            'houseprice': len(houseprice),
            'roads': {road: sum(1 for x in listings if x.get('road') == road) for road in WATCH_ROADS},
        },
        'listings': listings,
        'elapsedSeconds': round(time.time() - started, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'updatedAt': payload['updatedAt'], 'counts': payload['counts'], 'runs': {k:v['status'] for k,v in payload['runs'].items()}, 'elapsedSeconds': payload['elapsedSeconds']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
