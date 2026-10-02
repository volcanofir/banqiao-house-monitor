import json
import os
import re
import time

import requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
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

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36'


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




def parse_rakuya_cards(html_text, road):
    keyword = WATCH_ROADS[road][0]
    soup = BeautifulSoup(html_text or '', 'html.parser')
    rows = []
    seen = set()
    for link in soup.select('a[href*="/item/"]'):
        href = link.get('href') or ''
        m = re.search(r'/item/([A-Za-z0-9]+)', href)
        if not m:
            continue
        house_id = m.group(1)
        if house_id in seen:
            continue

        card = link.find_parent('section')
        if card is None:
            continue

        # Nearby-area recommendations are explicitly wrapped by Rakuya.
        # Exclude them first; primary cards may omit some geo spans.
        if card.find_parent(attrs={'data-rent-recommend': '1'}) is not None:
            continue
        area_node = card.select_one('.info__geo--area')
        road_node = card.select_one('.info__geo--road')
        district = norm(area_node.get_text(' ', strip=True) if area_node else '')
        card_road = norm(road_node.get_text(' ', strip=True) if road_node else '')
        text_probe = norm(card.get_text(' ', strip=True))
        if district and district != '板橋區':
            continue
        if card_road and card_road != keyword:
            continue
        if keyword not in text_probe and card_road != keyword:
            continue

        seen.add(house_id)
        if href.startswith('/'):
            href = 'https://rent.rakuya.com.tw' + href

        title_node = card.select_one('.card__head h2') or link.select_one('h2')
        title = norm(title_node.get_text(' ', strip=True) if title_node else '')
        text = norm(card.get_text(' ', strip=True))
        price_node = card.select_one('.info__price--total b')
        rent = num(price_node.get_text(' ', strip=True) if price_node else '')
        if rent is None:
            vals = re.findall(r'([\d,]+)\s*元', text)
            rent = float(vals[-1].replace(',', '')) if vals else None

        area_match = re.search(r'(\d+(?:\.\d+)?)\s*坪', text)
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
            'title': title or f'樂屋租屋 {house_id}',
            'address': road,
            'rent': rent,
            'size': float(area_match.group(1)) if area_match else None,
            'url': href,
            'floor': norm(floor_match.group(1)) if floor_match else None,
            'sourceUpdatedRaw': norm(updated_match.group(1)) if updated_match else None,
        })
    return dedupe(rows)


def fetch_rakuya_http():
    rows, logs = [], []
    ok = 0
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-TW,zh;q=0.9',
        'X-Requested-With': 'XMLHttpRequest',
    })
    for road, result_url in SEARCH_RAKUYA.items():
        keyword = WATCH_ROADS[road][0]
        road_rows, seen = [], set()
        exact_total = None
        success = False
        for page_no in range(1, 6):
            ajax_url = 'https://rent.rakuya.com.tw/ajax/get-result'
            try:
                r = session.get(
                    ajax_url,
                    params={
                        'zipcode': '220',
                        'keyword': keyword,
                        'sort': '11',
                        'page': page_no,
                    },
                    headers={'Referer': requests.utils.requote_uri(result_url)},
                    timeout=25,
                )
                if r.status_code != 200:
                    logs.append(f'{road} 樂屋AJAX第{page_no}頁失敗：HTTP {r.status_code}')
                    break
                payload = r.json()
                success = True
                if exact_total is None:
                    try:
                        exact_total = int(payload.get('total') or 0)
                    except Exception:
                        exact_total = 0
                parsed = parse_rakuya_cards(payload.get('list') or '', road)
                new_rows = [x for x in parsed if x['id'] not in seen]
                for item in new_rows:
                    seen.add(item['id'])
                    road_rows.append(item)
                logs.append(
                    f'{road} 樂屋AJAX第{page_no}頁：符合板橋指定路段 {len(parsed)}／新增 {len(new_rows)}'
                    + (f'／來源總數 {exact_total}' if exact_total is not None else '')
                )
                if exact_total is not None and len(road_rows) >= exact_total:
                    break
                page_info = payload.get('pages') or {}
                page_count = int(page_info.get('pageCount') or 1)
                if page_no >= page_count:
                    break
                if not (payload.get('list') or '').strip():
                    break
            except Exception as exc:
                logs.append(f'{road} 樂屋AJAX第{page_no}頁例外：{type(exc).__name__}: {exc}')
                break

        if success and exact_total is not None and len(road_rows) == exact_total:
            ok += 1
        elif success:
            logs.append(f'{road} 樂屋完整性警告：來源 {exact_total} 筆，實得 {len(road_rows)} 筆')
        rows.extend(road_rows)
        logs.append(f'{road} 樂屋租屋完成，共 {len(road_rows)} 筆')
    return dedupe(rows), ok == len(SEARCH_RAKUYA), logs


def houseprice_api_url(road, page_no):
    keyword = WATCH_ROADS[road][0]
    return f'https://rent.houseprice.tw/api/RentCaseList/Search/21_usage/15_zip/{keyword}_kw/?p={page_no}'


def normalize_houseprice_row(item, road):
    sid = str(item.get('caseSid') or '').strip()
    if not sid:
        return None
    if norm(item.get('city')) != '新北市' or norm(item.get('district')) != '板橋區':
        return None
    if norm(item.get('road')) != WATCH_ROADS[road][0]:
        return None

    case_from = item.get('caseFromList') or []
    url = None
    if isinstance(case_from, list):
        for source_item in case_from:
            if isinstance(source_item, dict) and source_item.get('caseUrl'):
                url = source_item.get('caseUrl')
                break
    if not url:
        url = SEARCH_HOUSEPRICE[road]

    from_floor = item.get('fromFloor')
    to_floor = item.get('toFloor')
    roof = item.get('roofLevel')
    floor = None
    if from_floor not in (None, '') and roof not in (None, ''):
        floor = f'{from_floor}/{roof}樓' if from_floor == to_floor or to_floor in (None, '') else f'{from_floor}~{to_floor}/{roof}樓'

    return {
        'id': f'5168租屋:{sid}',
        'source': '5168',
        'houseId': sid,
        'road': road,
        'title': norm(item.get('caseName')) or f'5168租屋 {sid}',
        'address': road,
        'rent': item.get('rentPrice'),
        'size': item.get('totalPin'),
        'url': url,
        'floor': floor,
        'rooms': item.get('room'),
        'livingRooms': item.get('livingRoom'),
        'bathrooms': item.get('bathRoom'),
        'balconies': item.get('balcony'),
        'purposeName': item.get('purposeName'),
        'buildingStyle': item.get('buildingStyle'),
        'sourcePublishedAt': item.get('publishTime'),
        'sourceUpdatedAtRaw': item.get('updateTime'),
        'sourcePublishedAtType': 'housepriceRentApiPublishTime',
    }


def fetch_houseprice_api():
    rows, logs = [], []
    ok = 0
    session = curl_requests.Session(impersonate='chrome')
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Sec-CH-UA': '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    })
    globally_blocked = False
    for road in WATCH_ROADS:
        if globally_blocked:
            logs.append(f'{road} 5168 API略過：已確認 GitHub 出口遭 403，直接交由瀏覽器備援')
            continue
        road_rows, seen = [], set()
        success = False
        total_count = None
        total_pages = None
        for page_no in range(1, 20):
            url = houseprice_api_url(road, page_no)
            try:
                r = session.get(
                    url,
                    headers={'Referer': requests.utils.requote_uri(SEARCH_HOUSEPRICE[road])},
                    timeout=8,
                )
                if r.status_code == 403:
                    logs.append(f'{road} 5168 API第{page_no}頁：HTTP 403，停止其餘直連測試並切瀏覽器備援')
                    globally_blocked = True
                    break
                if r.status_code != 200:
                    logs.append(f'{road} 5168 API第{page_no}頁失敗：HTTP {r.status_code}')
                    break
                payload = r.json()
                if payload.get('status') != 'Success' or not isinstance(payload.get('data'), dict):
                    logs.append(f'{road} 5168 API第{page_no}頁格式異常')
                    break
                success = True
                data = payload['data']
                page_info = data.get('page') or {}
                total_count = int(page_info.get('totalItemCount') or 0)
                total_pages = int(page_info.get('totalPageCount') or 0)
                parsed = []
                for item in data.get('rentCaseInfo') or []:
                    row = normalize_houseprice_row(item, road)
                    if row:
                        parsed.append(row)
                new_rows = [x for x in parsed if x['id'] not in seen]
                for item in new_rows:
                    seen.add(item['id'])
                    road_rows.append(item)
                logs.append(
                    f'{road} 5168 API第{page_no}頁：符合 {len(parsed)}／新增 {len(new_rows)}'
                    f'／來源總數 {total_count}'
                )
                if page_no >= total_pages or len(road_rows) >= total_count or not data.get('rentCaseInfo'):
                    break
            except Exception as exc:
                logs.append(f'{road} 5168 API第{page_no}頁例外：{type(exc).__name__}: {exc}')
                break

        if success and total_count is not None and len(road_rows) == total_count:
            ok += 1
        elif success and total_count == 0:
            ok += 1
        elif success:
            logs.append(f'{road} 5168 API完整性警告：來源 {total_count} 筆，實得 {len(road_rows)} 筆')
        rows.extend(road_rows)
        logs.append(f'{road} 5168租屋完成，共 {len(road_rows)} 筆')

    return dedupe(rows), ok == len(WATCH_ROADS), logs


def fetch_houseprice_browser(context, current_rows, current_ok, current_logs):
    if current_ok:
        return current_rows, current_ok, current_logs

    rows, logs = [], list(current_logs)
    ok = 0
    domain_blocked = False

    for road, list_url in SEARCH_HOUSEPRICE.items():
        if domain_blocked:
            logs.append(f'{road} 5168瀏覽器備援略過：已確認入口遭阻擋')
            continue

        page = context.new_page()
        road_rows, seen = [], set()
        try:
            response = page.goto(list_url, wait_until='domcontentloaded', timeout=12000)
            status = response.status if response else 0
            page.wait_for_timeout(900)
        except Exception as exc:
            status = type(exc).__name__

        if status != 200:
            logs.append(f'{road} 5168瀏覽器備援入口失敗：{status}')
            if status == 403:
                domain_blocked = True
                logs.append('5168 瀏覽器入口亦為 403，本輪停止 5168，其餘來源照常完成')
            page.close()
            continue

        success = False
        total_count = None
        total_pages = None
        for page_no in range(1, 20):
            api_url = houseprice_api_url(road, page_no)
            try:
                result = page.evaluate(
                    """async ({url}) => {
                      const ctrl = new AbortController();
                      const timer = setTimeout(() => ctrl.abort(), 8000);
                      try {
                        const r = await fetch(url, {
                          method:'GET',
                          headers:{accept:'application/json, text/plain, */*'},
                          credentials:'include',
                          cache:'no-store',
                          signal:ctrl.signal
                        });
                        return {status:r.status, text:await r.text()};
                      } catch(e) {
                        return {status:0, text:'', error:String(e)};
                      } finally {
                        clearTimeout(timer);
                      }
                    }""",
                    {'url': api_url},
                )
                api_status = int(result.get('status') or 0)
                if api_status != 200:
                    logs.append(f'{road} 5168瀏覽器API第{page_no}頁失敗：HTTP {api_status} {result.get("error") or ""}'.strip())
                    if api_status == 403:
                        domain_blocked = True
                    break
                payload = json.loads(result.get('text') or '{}')
                if payload.get('status') != 'Success' or not isinstance(payload.get('data'), dict):
                    logs.append(f'{road} 5168瀏覽器API第{page_no}頁格式異常')
                    break

                success = True
                data = payload['data']
                page_info = data.get('page') or {}
                total_count = int(page_info.get('totalItemCount') or 0)
                total_pages = int(page_info.get('totalPageCount') or 0)
                parsed = []
                for item in data.get('rentCaseInfo') or []:
                    row = normalize_houseprice_row(item, road)
                    if row:
                        parsed.append(row)
                new_rows = [x for x in parsed if x['id'] not in seen]
                for item in new_rows:
                    seen.add(item['id'])
                    road_rows.append(item)
                logs.append(
                    f'{road} 5168瀏覽器API第{page_no}頁：符合 {len(parsed)}／新增 {len(new_rows)}'
                    f'／來源總數 {total_count}'
                )
                if page_no >= total_pages or len(road_rows) >= total_count or not data.get('rentCaseInfo'):
                    break
            except Exception as exc:
                logs.append(f'{road} 5168瀏覽器API第{page_no}頁例外：{type(exc).__name__}: {exc}')
                break

        if success and total_count is not None and len(road_rows) == total_count:
            ok += 1
        elif success and total_count == 0:
            ok += 1
        elif success:
            logs.append(f'{road} 5168瀏覽器完整性警告：來源 {total_count} 筆，實得 {len(road_rows)} 筆')

        rows.extend(road_rows)
        logs.append(f'{road} 5168瀏覽器備援完成，共 {len(road_rows)} 筆')
        page.close()

    if rows:
        return dedupe(rows), ok == len(WATCH_ROADS), logs
    return current_rows, current_ok, logs


def fetch_all():
    # HAR-verified HTTP sources first. They do not depend on browser/VPN.
    rows_rakuya, ok_rakuya, logs_rakuya = fetch_rakuya_http()
    skip_houseprice = os.getenv('SKIP_HOUSEPRICE', '').strip() == '1'
    if skip_houseprice:
        rows_houseprice, ok_houseprice = [], False
        logs_houseprice = ['5168 本輪由 VPN 專用步驟另行抓取']
    else:
        rows_houseprice, ok_houseprice, logs_houseprice = fetch_houseprice_api()

    rows_591, rows_sinyi = [], []
    logs_591, logs_sinyi = [], []
    ok_591 = 0
    ok_sinyi = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--disable-dev-shm-usage'])
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 390, 'height': 844},
            locale='zh-TW',
            timezone_id='Asia/Taipei',
        )
        try:
            for road, base_url in SEARCH_591.items():
                road_rows, seen = [], set()
                page = context.new_page()
                loaded = False
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
                if loaded:
                    ok_591 += 1
                rows_591.extend(road_rows)
                logs_591.append(f'{road} 591租屋完成，共 {len(road_rows)} 筆')
                page.close()

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
            if not skip_houseprice:
                rows_houseprice, ok_houseprice, logs_houseprice = fetch_houseprice_browser(
                    context, rows_houseprice, ok_houseprice, logs_houseprice
                )
        finally:
            context.close()
            browser.close()

    return (
        dedupe(rows_591), ok_591 == len(SEARCH_591), logs_591,
        dedupe(rows_sinyi), ok_sinyi == len(SEARCH_SINYI), logs_sinyi,
        rows_rakuya, ok_rakuya, logs_rakuya,
        rows_houseprice, ok_houseprice, logs_houseprice,
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
