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

OTHER_DISTRICTS = (
    "永和區", "中和區", "新莊區", "土城區", "樹林區", "三重區", "蘆洲區",
    "汐止區", "鶯歌區", "三峽區", "淡水區", "新店區", "五股區", "泰山區",
    "林口區", "八里區", "台北市", "臺北市", "桃園市", "基隆市",
)

INVALID_MARKERS = ("案件已下架", "物件已下架", "找不到此案件", "此物件不存在", "頁面不存在", "物件不存在")
SEARCH_591_HOME = "https://sale.591.com.tw/"


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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
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
    match = re.search(r"\b([1-9]\d{0,2}(?:\.\d+)?)\b", text)
    return f"{match.group(1)}坪" if match else None


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


def parse_591_script_objects(body):
    pattern = re.compile(
        r'\{type:[^{}]*?houseid:(\d+)[\s\S]*?title:"((?:\\.|[^"])*)"'
        r'[\s\S]*?posttime:(\d+)[\s\S]*?address:("((?:\\.|[^"])*)"|[A-Za-z_$][\w$]*)'
        r'[\s\S]*?showprice:("((?:\\.|[^"])*)"|[A-Za-z_$][\w$]*)[\s\S]*?\}',
        re.S,
    )
    rows = []
    for match in pattern.finditer(body):
        house_id = match.group(1)
        title = normalize_text(decode_js_string(match.group(2)))
        raw_address = match.group(5)
        address = normalize_text(decode_js_string(raw_address)) if raw_address else ""
        raw_price = match.group(7)
        price = normalize_text(decode_js_string(raw_price)) if raw_price else None
        road = match_road(f"{title} {address}", source_locked_to_banqiao=True)
        if not road:
            continue
        if not address:
            address = f"新北市{road}"
        rows.append({
            "id": f"591:{house_id}",
            "source": "591",
            "houseId": house_id,
            "road": road,
            "title": title or f"591案件 {house_id}",
            "address": address,
            "price": format_price(price),
            "size": format_area(match.group(0)),
            "url": f"https://sale.591.com.tw/home/house/detail/2/{house_id}.html",
            "postTime": int(match.group(3)),
        })
    return rows


def parse_591_html_cards(body):
    soup = BeautifulSoup(body, "html.parser")
    rows = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = normalize_text(link.get("href"))
        match = re.search(r"/home/house/detail/2/(\d+)\.html", href)
        if not match:
            match = re.search(r"/home/(\d+)(?:$|[/?#])", href)
        if not match:
            continue

        house_id = match.group(1)
        if house_id in seen:
            continue

        card = link
        for _ in range(6):
            if not card.parent:
                break
            card = card.parent
            card_text = normalize_text(card.get_text(" ", strip=True))
            if match_road(card_text, source_locked_to_banqiao=True):
                break

        card_text = normalize_text(card.get_text(" ", strip=True))
        road = match_road(card_text, source_locked_to_banqiao=True)
        if not road:
            continue
        if has_other_district(card_text):
            continue

        title = normalize_text(link.get("title") or link.get_text(" ", strip=True))
        if not title or len(title) < 3:
            title_node = card.find(["h2", "h3", "h4"])
            title = normalize_text(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            title = f"591案件 {house_id}"

        price_match = re.search(r"([\d,]+(?:\.\d+)?)\s*萬", card_text)
        area_match = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)\s*坪", card_text)
        address = f"新北市{road}"

        rows.append({
            "id": f"591:{house_id}",
            "source": "591",
            "houseId": house_id,
            "road": road,
            "title": title,
            "address": address,
            "price": f"{price_match.group(1)}萬" if price_match else None,
            "size": f"{area_match.group(1)}坪" if area_match else None,
            "url": href if href.startswith("http") else f"https://sale.591.com.tw{href}",
            "postTime": None,
        })
        seen.add(house_id)

    return rows


def parse_591_html(body):
    rows = parse_591_script_objects(body)
    if rows:
        return dedupe_by_id(rows)
    return dedupe_by_id(parse_591_html_cards(body))


def fetch_591():
    """
    跟信義相同概念：
    直接抓一般售屋列表 HTML，先由 591 查詢條件鎖定新北市 + 板橋區，
    再從頁面內容比對 7 條監控路段。
    """
    session = requests.Session()
    logs = []
    rows = []
    seen_ids = set()
    successful_pages = 0

    for page_index, first_row in enumerate((0, 30, 60, 90, 120), start=1):
        response = None
        for attempt, delay in enumerate((0, 20, 60), start=1):
            if delay:
                time.sleep(delay)
            params = {
                "regionid": "3",
                "section": "26",
                "shType": "list",
                "order": "posttime_desc",
                "firstRow": str(first_row),
            }
            try:
                response = session.get(
                    SEARCH_591_HOME,
                    params=params,
                    headers=default_headers(SEARCH_591_HOME),
                    timeout=30,
                )
            except Exception as exc:
                logs.append(f"591 HTML 第 {page_index} 頁第 {attempt} 次連線失敗：{exc}")
                continue

            if response.status_code == 200:
                break

            logs.append(f"591 HTML 第 {page_index} 頁第 {attempt} 次 HTTP {response.status_code}")

        if response is None or response.status_code != 200:
            if page_index == 1:
                return [], False, "591 一般板橋列表本輪遭暫時封鎖，保留上一輪資料。", logs
            break

        successful_pages += 1
        page_rows = parse_591_html(response.text)
        page_new = [item for item in page_rows if item["id"] not in seen_ids]
        for item in page_new:
            seen_ids.add(item["id"])
        rows.extend(page_new)
        logs.append(f"591 HTML 第 {page_index} 頁：解析 {len(page_rows)}／新增 {len(page_new)}")

        if not page_rows or (page_index > 1 and not page_new):
            break

    rows = dedupe_by_id(rows)
    if successful_pages:
        return rows, True, f"591 一般板橋列表 HTML 完成，指定路段 {len(rows)} 筆。", logs
    return [], False, "591 一般板橋列表本輪無法讀取，保留上一輪資料。", logs


def fetch_sinyi():
    rows, logs = [], []
    success_count = 0
    for road in WATCH_ROADS:
        keyword = road.replace("板橋區", "")
        for page in (1, 2, 3):
            url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/{page}"
            try:
                response = requests.get(url, headers=default_headers("https://www.sinyi.com.tw/"), timeout=30)
            except Exception as exc:
                logs.append(f"{road} 第 {page} 頁連線失敗：{exc}")
                continue
            if response.status_code != 200:
                logs.append(f"{road} 第 {page} 頁 HTTP {response.status_code}")
                continue
            success_count += 1
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
            added = 0
            for item in parsed if isinstance(parsed, list) else []:
                house_id = normalize_text(item.get("houseNo"))
                title = normalize_text(item.get("name"))
                address = normalize_text(item.get("address"))
                if not house_id or not title or not address or not is_banqiao_address(address):
                    continue
                if road not in normalize_text(address):
                    aliases = WATCH_ROADS[road]
                    if not any(alias in normalize_text(address) for alias in aliases):
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
            logs.append(f"{road} 第 {page} 頁：解析 {len(parsed) if isinstance(parsed, list) else 0}／板橋 {added}")
    rows = dedupe_by_id(rows)
    ok = success_count > 0
    return rows, ok, (f"信義完成 7 路段 × 3 頁，共 {len(rows)} 筆板橋案件。" if ok else "信義房屋抓取失敗。"), logs


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
        state["runs"][source] = {
            "checkedAt": checked_at, "status": "error",
            "totalCount": sum(1 for item in previous if item.get("active", True)),
            "newCount": 0, "removedCount": 0, "message": message, "logs": logs,
        }
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

    state["runs"][source] = {
        "checkedAt": checked_at, "status": "ok", "totalCount": len(current),
        "newCount": len(new_ids), "removedCount": len(removed_ids), "message": message, "logs": logs,
    }
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
        lines.extend([
            f"{index}. [{item.get('source')}] {item.get('road')}", item.get("title") or "",
            " / ".join(str(v) for v in (item.get("price"), item.get("size"), item.get("address")) if v),
            item.get("url") or "", "",
        ])
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
