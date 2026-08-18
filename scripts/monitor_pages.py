import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path("docs/data/listings.json")
TZ_OFFSET = "+08:00"

WATCH_ROADS = {
    "板橋區中山路二段": ("中山路二段", "中山路2段"),
    "板橋區三民路二段": ("三民路二段", "三民路2段"),
    "板橋區光復街": ("光復街",),
    "板橋區萬安街": ("萬安街",),
    "板橋區林森街": ("林森街",),
    "板橋區三民路一段": ("三民路一段", "三民路1段"),
    "板橋區翠華街": ("翠華街",),
}

BANQIAO_ALIASES = ("板橋", "板橋區", "新北市板橋區")
OTHER_DISTRICTS = (
    "永和", "中和", "土城", "新莊", "三重", "蘆洲", "汐止", "鶯歌", "三峽", "淡水", "新店", "五股", "泰山", "林口", "八里", "台北", "北市", "桃園", "基隆"
)

SEARCH_591_API = "https://sale.591.com.tw/home/search/list"
SEARCH_591_HOME = "https://sale.591.com.tw"
SEARCH_SINYI = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/date-desc/{page}"
INVALID_MARKERS = ("案件已下架", "物件已下架", "找不到此案件", "此物件不存在", "頁面不存在", "物件不存在")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_text(value):
    text = "" if value is None else str(value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("臺", "台")


def default_headers(referer=None):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def looks_like_other_district(text):
    text = normalize_text(text)
    return any(dist in text for dist in OTHER_DISTRICTS)


def is_banqiao_text(text, source_is_already_banqiao=False):
    text = normalize_text(text)
    if not text or looks_like_other_district(text):
        return False
    if source_is_already_banqiao:
        return True
    return any(alias in text for alias in BANQIAO_ALIASES)


def match_road(text, source_is_already_banqiao=False):
    text = normalize_text(text)
    if not is_banqiao_text(text, source_is_already_banqiao=source_is_already_banqiao):
        return None
    for canonical, aliases in WATCH_ROADS.items():
        if any(alias in text for alias in aliases):
            return canonical
    return None


def format_price(value):
    value = normalize_text(value)
    if not value:
        return None
    if "萬" in value:
        return value
    number = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    return f"{number.group(0)}萬" if number else value


def format_area(value):
    value = normalize_text(value)
    m = re.search(r"([1-9]\d{0,2}(?:\.\d+)?)\s*坪", value)
    if m:
        return f"{m.group(1)}坪"
    m = re.search(r"\b([1-9]\d{0,2}(?:\.\d+)?)\b", value)
    return f"{m.group(1)}坪" if m else None


def to_unix(value):
    if value in (None, ""):
        return None
    try:
        n = int(float(value))
        return n // 1000 if n > 10**12 else n
    except Exception:
        return None


def dedupe_by_id(items):
    seen = set()
    output = []
    for item in items:
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def fetch_591():
    """ChatGPT Site-era logic: lock 591 to New Taipei + Banqiao first, then match the 7 roads."""
    rows = []
    logs = []
    session = requests.Session()
    headers = default_headers(SEARCH_591_HOME)
    headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        session.get(SEARCH_591_HOME, headers=headers, timeout=10)
    except Exception as exc:
        return [], False, f"591 首頁連線失敗：{exc}", logs

    seen_page_ids = set()
    for first_row in (0, 30, 60, 90, 120):
        params = {
            "type": "1",
            "regionid": "3",
            "section": "26",
            "firstRow": str(first_row),
            "totalRows": "30",
            "order": "posttime_desc",
        }
        try:
            response = session.get(SEARCH_591_API, headers=headers, params=params, timeout=15)
        except Exception as exc:
            logs.append(f"第 {first_row // 30 + 1} 頁連線失敗：{exc}")
            if first_row == 0:
                return [], False, logs[-1], logs
            break

        if response.status_code != 200:
            logs.append(f"第 {first_row // 30 + 1} 頁 HTTP {response.status_code}")
            if first_row == 0:
                return [], False, f"591 HTTP {response.status_code}", logs
            break

        try:
            payload = response.json()
        except Exception:
            logs.append(f"第 {first_row // 30 + 1} 頁 JSON 解析失敗")
            if first_row == 0:
                return [], False, logs[-1], logs
            break

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        items = data.get("house_list") or data.get("data") or []
        if not isinstance(items, list):
            items = []

        page_new = 0
        page_match = 0
        for item in items:
            house_id = str(item.get("houseid") or item.get("id") or "").strip()
            title = normalize_text(item.get("title"))
            address = normalize_text(item.get("address")) or "新北市板橋區"
            if not house_id or not title or house_id in seen_page_ids:
                continue
            seen_page_ids.add(house_id)
            page_new += 1

            road = match_road(f"{title} {address}", source_is_already_banqiao=True)
            if not road:
                continue
            page_match += 1
            rows.append({
                "id": f"591:{house_id}",
                "source": "591",
                "houseId": house_id,
                "road": road,
                "title": title,
                "address": address,
                "price": format_price(item.get("price") or item.get("showprice")),
                "size": format_area(item.get("area") or item.get("areaBuilding") or item.get("area_building")),
                "url": f"https://sale.591.com.tw/home/{house_id}",
                "postTime": to_unix(item.get("posttime") or item.get("postTime")),
            })

        logs.append(f"第 {first_row // 30 + 1} 頁：板橋資料 {len(items)}／新增 {page_new}／指定路段 {page_match}")
        if not items or (first_row > 0 and page_new == 0) or len(items) < 30:
            break

    rows = dedupe_by_id(rows)
    return rows, True, f"591 板橋資料池完成，指定路段 {len(rows)} 筆。", logs


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_sinyi_json(payload):
    rows = []
    for item in walk_json(payload):
        href = normalize_text(item.get("url") or item.get("href") or item.get("link"))
        title = normalize_text(item.get("name") or item.get("title") or item.get("caseName"))
        address = normalize_text(item.get("address") or item.get("addr"))
        price = normalize_text(item.get("price") or item.get("totalPrice") or item.get("amount"))
        if "/buy/house/" not in href or not title:
            continue
        full_text = f"{title} {address}"
        road = match_road(full_text)
        if not road:
            continue
        full_url = urljoin("https://www.sinyi.com.tw", href)
        house_id = full_url.rstrip("/").split("/")[-1]
        rows.append({
            "id": f"信義房屋:{house_id}",
            "source": "信義房屋",
            "houseId": house_id,
            "road": road,
            "title": title[:80],
            "address": address or "新北市板橋區",
            "price": format_price(price),
            "size": format_area(item.get("area") or item.get("buildingArea") or item.get("totalArea")),
            "url": full_url,
            "postTime": None,
        })
    return rows


def fetch_sinyi():
    rows = []
    logs = []
    any_success = False
    for page in (1, 2, 3):
        url = SEARCH_SINYI.format(page=page)
        try:
            response = requests.get(url, headers=default_headers("https://www.sinyi.com.tw/"), timeout=15)
        except Exception as exc:
            logs.append(f"第 {page} 頁連線失敗：{exc}")
            continue
        if response.status_code != 200:
            logs.append(f"第 {page} 頁 HTTP {response.status_code}")
            continue

        any_success = True
        soup = BeautifulSoup(response.text, "html.parser")
        before = len(rows)
        next_data = soup.find("script", id="__NEXT_DATA__", type="application/json")
        if next_data and next_data.string:
            try:
                rows.extend(extract_sinyi_json(json.loads(next_data.string)))
            except Exception:
                pass

        for link in soup.find_all("a", href=True):
            href = normalize_text(link.get("href"))
            if "/buy/house/" not in href:
                continue
            title = normalize_text(link.get("title") or link.get_text(" ", strip=True))
            if not title or len(title) < 4 or "信義" in title or "瀏覽" in title:
                continue
            parent_text = normalize_text(link.parent.get_text(" ", strip=True) if link.parent else title)
            full_text = f"{title} {parent_text}"
            road = match_road(full_text)
            if not road:
                continue
            full_url = urljoin("https://www.sinyi.com.tw", href)
            house_id = full_url.rstrip("/").split("/")[-1]
            rows.append({
                "id": f"信義房屋:{house_id}",
                "source": "信義房屋",
                "houseId": house_id,
                "road": road,
                "title": title[:80],
                "address": "新北市板橋區",
                "price": None,
                "size": None,
                "url": full_url,
                "postTime": None,
            })
        logs.append(f"第 {page} 頁：指定路段新增 {len(rows) - before} 筆")

    rows = dedupe_by_id(rows)
    return rows, any_success, (f"信義板橋頁完成，指定路段 {len(rows)} 筆。" if any_success else "信義抓取失敗。"), logs


def definitely_inactive(item):
    url = item.get("url")
    if not url:
        return False
    try:
        response = requests.get(url, headers=default_headers(), timeout=10, allow_redirects=True)
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
        if not isinstance(data, dict):
            raise ValueError
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
        active_count = sum(1 for item in previous if item.get("active", True))
        state["runs"][source] = {
            "checkedAt": checked_at,
            "status": "error",
            "totalCount": active_count,
            "newCount": 0,
            "removedCount": 0,
            "message": message,
            "logs": logs,
        }
        state["listings"] = other + previous
        return [], []

    current_ids = {item["id"] for item in current}
    new_ids = []
    merged = []
    for item in current:
        old = previous_by_id.get(item["id"])
        if old:
            first_seen = old.get("firstSeenAt") or checked_at
            new_at = old.get("newAt")
        else:
            first_seen = checked_at
            new_at = checked_at if had_baseline else None
            if had_baseline:
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
    if not fresh:
        return
    lines = ["板橋指定路段新案件", ""]
    for i, item in enumerate(fresh[:10], 1):
        lines.extend([
            f"{i}. [{item.get('source')}] {item.get('road')}",
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
