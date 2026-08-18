import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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
API_591_V1 = "bff-house.591.com.tw/v1/touch/sale/list"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_text(value):
    text = html.unescape("" if value is None else str(value))
    text = re.sub(r"\s+", " ", text).strip().replace("臺", "台")
    return text.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")


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


def format_price(value):
    if value in (None, ""):
        return None
    text = normalize_text(value).replace("萬元", "萬")
    if "萬" in text:
        match = re.search(r"([\d,]+(?:\.\d+)?)\s*萬", text)
        return f"{match.group(1)}萬" if match else text
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    amount = float(match.group(0))
    if amount >= 100000:
        amount /= 10000
    return f"{amount:g}萬"


def format_area(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return f"{value:g}坪"
    text = normalize_text(value)
    match = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)\s*坪", text)
    if match:
        return f"{match.group(1)}坪"
    try:
        number = float(text)
        return f"{number:g}坪"
    except Exception:
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


def build_591_page_url(road, street_id):
    keyword = road.replace("板橋區", "")
    params = {
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": street_id,
        "keywords": keyword,
    }
    return f"{SEARCH_591_MOBILE}?{urlencode(params)}"


def mutate_591_api_url(api_url, first_row, page_no):
    parsed = urlparse(api_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "firstRow": str(first_row),
        "newPage": str(page_no),
        "newPageSize": "30",
        "timestamp": str(int(time.time() * 1000)),
        "region_id": "3",
        "device": "touch",
    })
    return urlunparse(parsed._replace(query=urlencode(params)))


def parse_591_api_payload(payload, road):
    aliases = WATCH_ROADS[road]
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        data = data.get("items") or data.get("list") or data.get("data") or []
    if not isinstance(data, list):
        return [], 0

    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue

        post_id = normalize_text(item.get("post_id") or item.get("postId") or "")
        house_id_raw = normalize_text(item.get("houseid") or item.get("houseId") or "")
        if not post_id:
            match = re.search(r"(\d{6,})", house_id_raw)
            post_id = match.group(1) if match else ""
        if not post_id:
            continue

        region = normalize_text(item.get("region") or item.get("region_name") or "")
        section = normalize_text(item.get("section") or item.get("section_name") or "")
        section_id = normalize_text(item.get("sectionid") or item.get("section_id") or "")
        address = normalize_text(item.get("address") or item.get("address_new") or "")
        title = normalize_text(item.get("title") or item.get("name") or "")

        if region and region != "新北市":
            continue
        if section and section != "板橋區":
            continue
        if section_id and section_id != "26":
            continue
        if has_other_district(address):
            continue
        if not any(alias in address for alias in aliases):
            continue

        price_arr = item.get("price_arr") if isinstance(item.get("price_arr"), dict) else {}
        price = format_price(price_arr.get("price") or item.get("total_price") or item.get("price"))

        area_unit = item.get("areaUnit") if isinstance(item.get("areaUnit"), dict) else {}
        size = format_area(item.get("area_str") or area_unit.get("area") or item.get("area"))

        post_time = to_unix(item.get("posttime") or item.get("postTime") or item.get("publishTime"))
        rows.append({
            "id": f"591:{post_id}",
            "source": "591",
            "houseId": post_id,
            "road": road,
            "title": title or f"591案件 {post_id}",
            "address": address or f"板橋區-{road.replace('板橋區', '')}",
            "price": price,
            "size": size,
            "url": f"https://m.591.com.tw/v2/sale/{post_id}",
            "postTime": post_time,
        })

    return dedupe_by_id(rows), len(data)


def browser_fetch_json(page, url):
    return page.evaluate(
        """async (url) => {
          const response = await fetch(url, {credentials: 'include'});
          const text = await response.text();
          return {status: response.status, text};
        }""",
        url,
    )


def fetch_591():
    logs = []
    rows = []
    global_seen = set()
    successful_roads = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                locale="zh-TW",
                timezone_id="Asia/Taipei",
            )

            for road, street_id in WATCH_591_STREETS.items():
                page = context.new_page()
                captured = []

                def on_response(response):
                    if API_591_V1 not in response.url or response.status != 200:
                        return
                    try:
                        captured.append((response.url, response.json()))
                    except Exception:
                        pass

                page.on("response", on_response)
                page_url = build_591_page_url(road, street_id)
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(6000)
                except Exception as exc:
                    logs.append(f"{road} Playwright 首頁載入失敗：{exc}")

                if not captured:
                    logs.append(f"{road} streetid={street_id}：沒有取得 591 列表 API")
                    page.close()
                    continue

                successful_roads += 1
                api_url, first_payload = captured[-1]
                road_seen = set()
                page_no = 1
                payload = first_payload

                while page_no <= 20:
                    page_rows, raw_count = parse_591_api_payload(payload, road)
                    new_rows = [item for item in page_rows if item["id"] not in road_seen]
                    for item in new_rows:
                        road_seen.add(item["id"])
                        if item["id"] not in global_seen:
                            global_seen.add(item["id"])
                            rows.append(item)

                    logs.append(
                        f"{road} streetid={street_id} 第 {page_no} 頁：API {raw_count} 筆／路段符合 {len(page_rows)}／新增 {len(new_rows)}"
                    )

                    if raw_count == 0 or (page_no > 1 and not new_rows):
                        break
                    if raw_count < 30:
                        break

                    page_no += 1
                    next_url = mutate_591_api_url(api_url, (page_no - 1) * 30, page_no)
                    try:
                        result = browser_fetch_json(page, next_url)
                        if result.get("status") != 200:
                            logs.append(f"{road} 第 {page_no} 頁 API HTTP {result.get('status')}，停止翻頁")
                            break
                        payload = json.loads(result.get("text") or "{}")
                    except Exception as exc:
                        logs.append(f"{road} 第 {page_no} 頁 API 讀取失敗：{exc}")
                        break

                page.close()

            browser.close()
    except Exception as exc:
        return [], False, f"591 Playwright 啟動失敗，保留上一輪資料：{exc}", logs

    rows = dedupe_by_id(rows)
    if successful_roads:
        return rows, True, f"591 Playwright/API 完成，成功 {successful_roads}/7 路段，共 {len(rows)} 筆板橋指定路段案件。", logs
    return [], False, "591 七路段皆未取得 API，保留上一輪資料。", logs


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
                if not any(alias in address for alias in WATCH_ROADS[road]):
                    continue
                rows.append({
                    "id": f"信義房屋:{house_id}",
                    "source": "信義房屋",
                    "houseId": house_id,
                    "road": road,
                    "title": title,
                    "address": address,
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
    return rows, ok, (
        f"信義完成 7 路段逐頁抓取至空頁，共讀取 {total_pages} 頁、{len(rows)} 筆板橋案件。"
        if ok else "信義房屋抓取失敗。"
    ), logs


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
    previous_run = (state.get("runs") or {}).get(source) or {}
    baseline_ready = bool(previous_by_id)
    if source == "591" and previous_run.get("mode") != "playwright_api":
        baseline_ready = False

    if not success:
        state["runs"][source] = {
            "checkedAt": checked_at,
            "status": "error",
            "totalCount": sum(1 for item in previous if item.get("active", True)),
            "newCount": 0,
            "removedCount": 0,
            "message": message,
            "logs": logs,
            "mode": previous_run.get("mode"),
        }
        state["listings"] = other + previous
        return [], []

    current_ids = {item["id"] for item in current}
    new_ids, merged = [], []
    for item in current:
        old = previous_by_id.get(item["id"])
        first_seen = (old or {}).get("firstSeenAt") or checked_at
        new_at = (old or {}).get("newAt")
        if not old and baseline_ready:
            new_at = checked_at
            new_ids.append(item["id"])
        merged.append({
            **item,
            "firstSeenAt": first_seen,
            "lastSeenAt": checked_at,
            "newAt": new_at,
            "active": True,
            "removedAt": None,
        })

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
        "checkedAt": checked_at,
        "status": "ok",
        "totalCount": len(current),
        "newCount": len(new_ids),
        "removedCount": len(removed_ids),
        "message": message,
        "logs": logs,
        "mode": "playwright_api" if source == "591" else "html",
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
            f"{index}. [{item.get('source')}] {item.get('road')}",
            item.get("title") or "",
            " / ".join(str(v) for v in (item.get("price"), item.get("size"), item.get("address")) if v),
            item.get("url") or "",
            "",
        ])

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(lines)[:4000], "disable_web_page_preview": True},
            timeout=10,
        )
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
    state["listings"] = sorted(
        state["listings"],
        key=lambda item: (
            0 if item.get("active", True) else 1,
            -(item.get("postTime") or 0),
            item.get("firstSeenAt") or "",
        ),
    )[:600]

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
