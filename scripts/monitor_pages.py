import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path("docs/data/listings.json")

WATCH_ROADS = {
    "板橋區中山路二段": ("中山路二段", "中山路2段"),
    "板橋區三民路二段": ("三民路二段", "三民路2段"),
    "板橋區光復街": ("光復街",),
    "板橋區萬安街": ("萬安街",),
    "板橋區林森街": ("林森街",),
    "板橋區三民路一段": ("三民路一段", "三民路1段"),
    "板橋區翠華街": ("翠華街",),
}

WATCH_591_STREETS = {
    "板橋區中山路二段": "27507",
    "板橋區三民路二段": "27485",
    "板橋區光復街": "27550",
    "板橋區萬安街": "27630",
    "板橋區林森街": "27574",
    "板橋區三民路一段": "27484",
    "板橋區翠華街": "27644",
}

OTHER_DISTRICTS = (
    "永和區", "中和區", "新莊區", "土城區", "樹林區", "三重區", "蘆洲區",
    "汐止區", "鶯歌區", "三峽區", "淡水區", "新店區", "五股區", "泰山區",
    "林口區", "八里區", "台北市", "臺北市", "桃園市", "基隆市",
)

INVALID_MARKERS = ("案件已下架", "物件已下架", "找不到此案件", "此物件不存在", "頁面不存在", "物件不存在")
SEARCH_591_MOBILE = "https://m.591.com.tw/v2/sale"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_text(value):
    text = html.unescape("" if value is None else str(value))
    text = re.sub(r"\s+", " ", text).strip().replace("臺", "台")
    text = text.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")
    return text


def default_headers(referer=None):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def has_other_district(text):
    text = normalize_text(text)
    return any(item.replace("臺", "台") in text for item in OTHER_DISTRICTS)


def is_banqiao_address(address):
    text = normalize_text(address)
    return "板橋區" in text and not has_other_district(text)


def match_road(text, source_locked_to_banqiao=False):
    text = normalize_text(text)
    if not source_locked_to_banqiao and not is_banqiao_address(text):
        return None
    if source_locked_to_banqiao and has_other_district(text):
        return None
    for canonical, aliases in WATCH_ROADS.items():
        if any(alias in text for alias in aliases):
            return canonical
    return None


def format_price(value):
    text = normalize_text(value)
    if not text:
        return None
    if "萬" in text:
        return text
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    amount = float(match.group(0))
    if amount >= 100000:
        amount /= 10000
    return f"{amount:g}萬"


def format_area(value):
    text = normalize_text(value)
    match = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)\s*坪", text)
    if match:
        return f"{match.group(1)}坪"
    return None


def to_unix(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number // 1000 if number > 10**12 else number
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.timestamp())
    except Exception:
        try:
            number = int(float(value))
            return number // 1000 if number > 10**12 else number
        except Exception:
            return None


def dedupe_by_id(items):
    seen = set()
    output = []
    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        output.append(item)
    return output


def decode_js_string(value):
    if value is None:
        return ""
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return normalize_text(value.replace(r"\/", "/").replace(r'\"', '"'))


def extract_js_value(fragment, keys, numeric=False):
    for key in keys:
        if numeric:
            match = re.search(rf'["\']?{re.escape(key)}["\']?\s*:\s*([0-9.]+)', fragment, re.I)
            if match:
                return match.group(1)
        else:
            match = re.search(rf'["\']?{re.escape(key)}["\']?\s*:\s*["\']((?:\\.|[^"\'])*)["\']', fragment, re.I)
            if match:
                return decode_js_string(match.group(1))
    return None


def parse_591_script_objects(body, forced_road):
    aliases = WATCH_ROADS[forced_road]
    rows = []
    seen = set()
    id_matches = list(re.finditer(r'["\']?houseid["\']?\s*:\s*["\']?(\d{6,})', body, re.I))
    if not id_matches:
        id_matches = list(re.finditer(r'["\']?(?:houseId|id)["\']?\s*:\s*["\']?(\d{7,})', body, re.I))

    for match in id_matches:
        house_id = match.group(1)
        if house_id in seen:
            continue
        start = max(0, match.start() - 2200)
        end = min(len(body), match.end() + 5200)
        fragment = body[start:end]
        fragment_text = normalize_text(fragment)
        if has_other_district(fragment_text) or not any(alias in fragment_text for alias in aliases):
            continue

        title = normalize_text(extract_js_value(fragment, ("title", "name", "subject")) or "")
        address = normalize_text(extract_js_value(fragment, ("address", "addr", "location")) or "")
        if address and has_other_district(address):
            continue
        if address and not any(alias in address for alias in aliases) and not any(alias in title for alias in aliases):
            continue

        price_raw = extract_js_value(fragment, ("showprice", "price", "totalPrice", "price_total"))
        if not price_raw:
            price_raw = extract_js_value(fragment, ("showprice", "price", "totalPrice", "price_total"), numeric=True)
        area_raw = extract_js_value(fragment, ("area", "areaBuilding", "buildarea", "area_total", "totalarea"))
        if not area_raw:
            area_raw = extract_js_value(fragment, ("area", "areaBuilding", "buildarea", "area_total", "totalarea"), numeric=True)
        post_raw = extract_js_value(fragment, ("posttime", "postTime", "publishTime", "updateTime"), numeric=True)

        if not address:
            address = f"新北市{forced_road}"

        rows.append({
            "id": f"591:{house_id}",
            "source": "591",
            "houseId": house_id,
            "road": forced_road,
            "title": title or f"591案件 {house_id}",
            "address": address,
            "price": format_price(price_raw),
            "size": format_area(area_raw),
            "url": f"https://m.591.com.tw/v2/sale/{house_id}",
            "postTime": to_unix(post_raw),
        })
        seen.add(house_id)
    return rows


def parse_591_html_cards(body, forced_road):
    soup = BeautifulSoup(body, "html.parser")
    aliases = WATCH_ROADS[forced_road]
    rows = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = normalize_text(link.get("href"))
        match = re.search(r"/v2/sale/(\d{6,})(?:$|[/?#])", href)
        if not match:
            match = re.search(r"/home/house/detail/2/(\d+)\.html", href)
        if not match:
            continue
        house_id = match.group(1)
        if house_id in seen:
            continue

        card = link
        card_text = ""
        for _ in range(7):
            card_text = normalize_text(card.get_text(" ", strip=True))
            if any(alias in card_text for alias in aliases):
                break
            if not card.parent:
                break
            card = card.parent

        if not any(alias in card_text for alias in aliases) or has_other_district(card_text):
            continue
        title = normalize_text(link.get("title") or link.get_text(" ", strip=True)) or f"591案件 {house_id}"
        price_match = re.search(r"([\d,]+(?:\.\d+)?)\s*萬", card_text)
        area_match = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)\s*坪", card_text)
        rows.append({
            "id": f"591:{house_id}",
            "source": "591",
            "houseId": house_id,
            "road": forced_road,
            "title": title,
            "address": f"新北市{forced_road}",
            "price": f"{price_match.group(1)}萬" if price_match else None,
            "size": f"{area_match.group(1)}坪" if area_match else None,
            "url": href if href.startswith("http") else f"https://m.591.com.tw{href}",
            "postTime": None,
        })
        seen.add(house_id)
    return rows


def parse_591_html(body, forced_road):
    return dedupe_by_id(parse_591_script_objects(body, forced_road) + parse_591_html_cards(body, forced_road))


def fetch_591():
    session = requests.Session()
    logs = []
    rows = []
    seen_ids = set()
    successful_roads = 0

    for road, street_id in WATCH_591_STREETS.items():
        keyword = road.replace("板橋區", "")
        road_success = False
        road_seen = set()

        for page in range(1, 6):
            params = {
                "regionid": "3",
                "sectionidStr": "26",
                "o": "32",
                "streetid": street_id,
                "keywords": keyword,
            }
            if page > 1:
                params["page"] = str(page)
                params["firstRow"] = str((page - 1) * 30)

            response = None
            for attempt, delay in enumerate((0, 15, 45), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    response = session.get(SEARCH_591_MOBILE, params=params, headers=default_headers("https://m.591.com.tw/"), timeout=30)
                except Exception as exc:
                    logs.append(f"{road} 第 {page} 頁第 {attempt} 次連線失敗：{exc}")
                    continue
                if response.status_code == 200:
                    break
                logs.append(f"{road} 第 {page} 頁第 {attempt} 次 HTTP {response.status_code}")

            if response is None or response.status_code != 200:
                logs.append(f"{road} 第 {page} 頁讀取失敗，停止此路段")
                break

            if page == 1:
                road_success = True
                successful_roads += 1

            body = response.text
            page_rows = parse_591_html(body, road)
            page_new = [item for item in page_rows if item["id"] not in road_seen]
            for item in page_new:
                road_seen.add(item["id"])
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    rows.append(item)

            raw_houseids = len(set(re.findall(r'houseid["\']?\s*:\s*["\']?(\d{6,})', body, re.I)))
            raw_links = len(set(re.findall(r'/v2/sale/(\d{6,})', body)))
            logs.append(f"{road} streetid={street_id} 第 {page} 頁：HTTP 200 / HTML {len(body)} bytes / houseid {raw_houseids} / detail links {raw_links} / 解析 {len(page_rows)} / 新增 {len(page_new)}")
            if not page_rows or (page > 1 and not page_new):
                break

        if not road_success:
            logs.append(f"{road} 本輪沒有成功取得頁面")

    rows = dedupe_by_id(rows)
    if successful_roads:
        return rows, True, f"591 以 7 路段 streetid 獨立查詢完成，成功 {successful_roads}/7 路段，共 {len(rows)} 筆。", logs
    return [], False, "591 七路段本輪皆無法讀取，保留上一輪資料。", logs


def fetch_sinyi():
    rows, logs = [], []
    success_count = 0
    total_pages = 0
    for road in WATCH_ROADS:
        keyword = road.replace("板橋區", "")
        page = 1
        seen_search_ids = set()
        while True:
            url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/{page}"
            try:
                response = requests.get(url, headers=default_headers("https://www.sinyi.com.tw/"), timeout=30)
            except Exception as exc:
                logs.append(f"{road} 第 {page} 頁連線失敗：{exc}")
                break
            if response.status_code != 200:
                logs.append(f"{road} 第 {page} 頁 HTTP {response.status_code}，停止此路段翻頁")
                break
            success_count += 1
            total_pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            parsed = []
            if script and script.string:
                try:
                    payload = json.loads(script.string)
                    reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
                    parsed = reducer.get("list") or []
                except Exception:
                    parsed = []
            if not isinstance(parsed, list) or len(parsed) == 0:
                logs.append(f"{road} 第 {page} 頁：0 筆，已抓完整條路")
                break
            page_ids = {normalize_text(item.get("houseNo")) for item in parsed if normalize_text(item.get("houseNo"))}
            if page_ids and page_ids.issubset(seen_search_ids):
                logs.append(f"{road} 第 {page} 頁：全部為前頁重複案件，停止翻頁")
                break
            seen_search_ids.update(page_ids)
            added = 0
            for item in parsed:
                house_id = normalize_text(item.get("houseNo"))
                title = normalize_text(item.get("name"))
                address = normalize_text(item.get("address"))
                if not house_id or not title or not address or not is_banqiao_address(address):
                    continue
                aliases = WATCH_ROADS[road]
                if not any(alias in address for alias in aliases):
                    continue
                rows.append({
                    "id": f"信義房屋:{house_id}", "source": "信義房屋", "houseId": house_id, "road": road,
                    "title": title, "address": address,
                    "price": f"{item.get('totalPrice'):,}萬" if isinstance(item.get("totalPrice"), (int, float)) else None,
                    "size": f"{item.get('areaBuilding')}坪" if isinstance(item.get("areaBuilding"), (int, float)) else None,
                    "url": f"https://www.sinyi.com.tw/buy/house/{quote(house_id)}?breadcrumb=list",
                    "postTime": to_unix(item.get("publishTime") or item.get("updateTime") or item.get("createTime")),
                })
                added += 1
            logs.append(f"{road} 第 {page} 頁：解析 {len(parsed)}／板橋 {added}")
            page += 1
    rows = dedupe_by_id(rows)
    ok = success_count > 0
    return rows, ok, (f"信義完成 7 路段逐頁抓取至空頁，共讀取 {total_pages} 頁、{len(rows)} 筆板橋案件。" if ok else "信義房屋抓取失敗。"), logs


def definitely_inactive(item):
    url = item.get("url")
    if not url:
        return False
    try:
        response = requests.get(url, headers=default_headers(), timeout=12, allow_redirects=True)
    except Exception:
        return False
    if response.status_code in (404, 410):
        return True
    if response.status_code != 200:
        return False
    text = normalize_text(response.text)
    return any(marker in text for marker in INVALID_MARKERS)


def load_state():
    if not DATA_PATH.exists():
        return {"updatedAt": None, "runs": {}, "listings": []}
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data.setdefault("runs", {})
        data.setdefault("listings", [])
        return data
    except Exception:
        return {"updatedAt": None, "runs": {}, "listings": []}


def merge_source(state, source, current, success, message, logs, checked_at):
    previous = [item for item in state["listings"] if item.get("source") == source]
    other = [item for item in state["listings"] if item.get("source") != source]
    previous_by_id = {item.get("id"): item for item in previous if item.get("id")}
    had_baseline = bool(previous_by_id)
    if not success:
        state["runs"][source] = {"checkedAt": checked_at, "status": "error", "totalCount": sum(1 for item in previous if item.get("active", True)), "newCount": 0, "removedCount": 0, "message": message, "logs": logs}
        state["listings"] = other + previous
        return [], []
    current_ids = {item["id"] for item in current}
    new_ids, merged = [], []
    for item in current:
        old = previous_by_id.get(item["id"])
        first_seen = (old or {}).get("firstSeenAt") or checked_at
        new_at = (old or {}).get("newAt")
        if not old and had_baseline:
            new_at = checked_at
            new_ids.append(item["id"])
        merged.append({**item, "firstSeenAt": first_seen, "lastSeenAt": checked_at, "newAt": new_at, "active": True, "removedAt": None})
    removed_ids = []
    for old in previous:
        old_id = old.get("id")
        if not old_id or old_id in current_ids:
            continue
        if old.get("active", True) and definitely_inactive(old):
            changed = dict(old)
            changed["active"] = False
            changed["removedAt"] = checked_at
            merged.append(changed)
            removed_ids.append(old_id)
        else:
            merged.append(old)
    state["runs"][source] = {"checkedAt": checked_at, "status": "ok", "totalCount": len(current), "newCount": len(new_ids), "removedCount": len(removed_ids), "message": message, "logs": logs}
    state["listings"] = other + dedupe_by_id(merged)
    return new_ids, removed_ids


def send_telegram(state, new_ids):
    token = os.environ.get("TG_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not new_ids:
        return
    lookup = {item.get("id"): item for item in state.get("listings", [])}
    fresh = [lookup[item_id] for item_id in new_ids if item_id in lookup]
    lines = ["板橋指定路段新案件", ""]
    for index, item in enumerate(fresh[:10], 1):
        lines.extend([f"{index}. [{item.get('source')}] {item.get('road')}", item.get("title") or "", " / ".join(str(v) for v in (item.get("price"), item.get("size"), item.get("address")) if v), item.get("url") or "", ""])
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": "\n".join(lines)[:4000], "disable_web_page_preview": True}, timeout=10)
    except Exception:
        pass


def main():
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    checked_at = now_iso()
    state = load_state()
    rows_591, ok_591, msg_591, logs_591 = fetch_591()
    rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi = fetch_sinyi()
    new_591, _ = merge_source(state, "591", rows_591, ok_591, msg_591, logs_591, checked_at)
    new_sinyi, _ = merge_source(state, "信義房屋", rows_sinyi, ok_sinyi, msg_sinyi, logs_sinyi, checked_at)
    state["updatedAt"] = checked_at
    state["watchRoads"] = list(WATCH_ROADS.keys())
    state["listings"] = sorted(state["listings"], key=lambda item: (0 if item.get("active", True) else 1, -(item.get("postTime") or 0), item.get("firstSeenAt") or ""))[:600]
    DATA_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    send_telegram(state, new_591 + new_sinyi)
    print("591:", msg_591)
    for line in logs_591:
        print(" -", line)
    print("信義:", msg_sinyi)
    for line in logs_sinyi:
        print(" -", line)
    print("寫入:", DATA_PATH)


if __name__ == "__main__":
    main()
