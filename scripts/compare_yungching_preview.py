import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DATA_PATH = Path("docs/data/listings.json")
OUT_PATH = Path("docs/preview/company-gap.json")
SNAPSHOT_PATH = Path("docs/preview/yungching-har-snapshot.json")

ROAD_URLS = {
    "板橋區中山路二段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/中山路二段_kw?od=80",
    "板橋區三民路一段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/三民路一段_kw?od=80",
    "板橋區萬安街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/萬安街_kw?od=80",
    "板橋區林森街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/林森街_kw?od=80",
    "板橋區翠華街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/翠華街_kw?od=80",
    "板橋區光復街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/光復街_kw?od=80",
    "板橋區三民路二段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/三民路二段_kw?od=80",
}

PROPERTY_TYPES = ("住宅大樓", "辦公商業大樓", "公寓", "華廈", "店面", "透天厝", "其他", "廠辦", "套房")
STOPWORDS = {
    "板橋", "板橋區", "新北市", "永慶房屋", "專約", "專任", "推薦", "好宅", "美寓", "美屋", "美宅",
    "公寓", "華廈", "大樓", "住宅", "捷運", "邊間", "採光", "三房", "兩房", "四房", "一樓", "二樓",
    "三樓", "四樓", "五樓", "全新", "裝潢", "首購", "成家", "稀有", "景觀", "低總價", "近捷運", "出價可談",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


def norm(value):
    text = str(value or "").replace("臺", "台")
    text = text.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def parse_float(value):
    m = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(m.group()) if m else None


def extract_area(text):
    m = re.search(r"建坪\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


def extract_price(text):
    tail = text.split("永慶房屋", 1)[-1]
    vals = []
    for raw in re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d+)?(?:\s*萬)?", tail):
        try:
            n = float(raw.replace(",", ""))
        except Exception:
            continue
        if 500 <= n <= 100000:
            vals.append(n)
    return vals[-1] if vals else None


def extract_title(text):
    idx = text.find("新北市板橋區")
    return text[:idx].strip() if idx > 0 else text[:40].strip()


def extract_address(text):
    idx = text.find("新北市板橋區")
    if idx < 0:
        return ""
    rest = text[idx:]
    stops = [rest.find(t) for t in PROPERTY_TYPES if rest.find(t) > 0]
    return rest[:min(stops) if stops else min(len(rest), 80)].strip()


def meaningful_tokens(text):
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", str(text or ""))
    out = set()
    for chunk in chunks:
        if chunk in STOPWORDS:
            continue
        if len(chunk) >= 3:
            out.add(chunk)
        if len(chunk) >= 4:
            for n in (3, 4, 5):
                if len(chunk) < n:
                    continue
                for i in range(len(chunk) - n + 1):
                    part = chunk[i:i+n]
                    if part not in STOPWORDS:
                        out.add(part)
    return out


def parse_cards(html, road, base_url):
    soup = BeautifulSoup(html, "html.parser")
    keyword = road.replace("板橋區", "")
    rows = {}
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        m = re.search(r"/house/(\d+)", href)
        if not m:
            continue
        text = " ".join(a.stripped_strings)
        if "新北市板橋區" not in text or keyword not in text:
            continue
        house_id = m.group(1)
        rows[house_id] = {
            "id": house_id,
            "road": road,
            "title": extract_title(text),
            "address": extract_address(text),
            "area": extract_area(text),
            "price": extract_price(text),
            "url": urljoin(base_url, href),
            "text": text,
            "sourceMode": "live_html",
        }
    return list(rows.values())


def fetch_requests():
    session = requests.Session()
    company, logs, status = [], [], {}
    for road, url in ROAD_URLS.items():
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            rows = parse_cards(r.text, road, url) if r.status_code == 200 else []
            logs.append(f"requests {road}: HTTP {r.status_code}; rows={len(rows)}")
            status[road] = {"count": len(rows), "http": r.status_code, "url": url, "available": bool(rows)}
            company.extend(rows)
        except Exception as exc:
            logs.append(f"requests {road}: {type(exc).__name__}")
            status[road] = {"count": 0, "http": None, "url": url, "available": False}
    return company, logs, status


def fetch_browser():
    company, logs, status = [], [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1440, "height": 1000},
        )
        for road, url in ROAD_URLS.items():
            page = context.new_page()
            http_status = None
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                http_status = resp.status if resp else None
                page.wait_for_timeout(1500)
                rows = parse_cards(page.content(), road, url)
                body = page.locator("body").inner_text(timeout=5000)[:100].replace("\n", " ")
                logs.append(f"browser {road}: HTTP {http_status}; rows={len(rows)}; body={body}")
                status[road] = {"count": len(rows), "http": http_status, "url": url, "available": bool(rows)}
                company.extend(rows)
            except Exception as exc:
                logs.append(f"browser {road}: {type(exc).__name__}: {str(exc)[:90]}")
                status[road] = {"count": 0, "http": http_status, "url": url, "available": False}
            finally:
                page.close()
        browser.close()
    deduped = {(x["road"], x["id"]): x for x in company}
    return list(deduped.values()), logs, status


def load_har_snapshot():
    if not SNAPSHOT_PATH.exists():
        return [], None, []
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    road = snap.get("scopeRoad")
    rows = []
    for x in snap.get("listings", []):
        row = dict(x)
        row.setdefault("road", road)
        row.setdefault("address", "")
        row.setdefault("area", None)
        row.setdefault("text", row.get("title", ""))
        row["sourceMode"] = "har_snapshot"
        rows.append(row)
    return rows, snap, [f"HAR snapshot {road}: {len(rows)} rows; capturedAt={snap.get('capturedAt')}"]


def shared_token_score(a, b):
    shared = meaningful_tokens(a) & meaningful_tokens(b)
    if not shared:
        return 0, []
    longest = max(len(x) for x in shared)
    return (4 if longest >= 5 else 3 if longest >= 4 else 2), sorted(shared, key=lambda x: (-len(x), x))[:6]


def candidate_score(ext, yc):
    ext_area = parse_float(ext.get("size"))
    ext_price = ext.get("effectivePrice") if ext.get("effectivePrice") is not None else parse_float(ext.get("price"))
    yc_area = parse_float(yc.get("area"))
    yc_price = parse_float(yc.get("price"))
    area_delta = abs(ext_area - yc_area) if ext_area is not None and yc_area is not None else None
    price_delta = abs(float(ext_price) - float(yc_price)) if ext_price is not None and yc_price is not None else None
    score = 0

    if area_delta is not None:
        if area_delta <= 0.12:
            score += 5
        elif area_delta <= 0.35:
            score += 3
        elif area_delta <= 0.6:
            score += 1
        elif area_delta > 1.0:
            return -99, {"areaDelta": round(area_delta, 2), "priceDelta": price_delta, "shared": [], "titleRatio": 0}

    if price_delta is not None:
        if price_delta <= 1:
            score += 5
        elif price_delta <= 30:
            score += 4
        elif price_delta <= 80:
            score += 2
        elif price_delta <= 150:
            score += 1
        elif price_delta > 300:
            score -= 3

    ext_title = str(ext.get("title") or "")
    yc_title = str(yc.get("title") or "")
    ext_text = f"{ext_title} {ext.get('address','')}"
    yc_text = f"{yc_title} {yc.get('address','')} {yc.get('text','')}"
    token_score, shared = shared_token_score(ext_text, yc_text)
    score += token_score
    title_ratio = SequenceMatcher(None, norm(ext_title), norm(yc_title)).ratio()
    full_ratio = SequenceMatcher(None, norm(ext_text), norm(yc_text)).ratio()
    if title_ratio >= 0.55:
        score += 4
    elif title_ratio >= 0.42:
        score += 3
    elif title_ratio >= 0.30:
        score += 1
    if full_ratio >= 0.45:
        score += 2
    elif full_ratio >= 0.30:
        score += 1

    return score, {
        "areaDelta": None if area_delta is None else round(area_delta, 2),
        "priceDelta": None if price_delta is None else round(price_delta, 1),
        "shared": shared,
        "titleRatio": round(title_ratio, 3),
        "textRatio": round(full_ratio, 3),
        "companySourceMode": yc.get("sourceMode"),
    }


def classify(ext, company, covered_roads):
    road = ext.get("road")
    if road not in covered_roads:
        return "unavailable", 0, None, {"reason": "此路段尚無永慶可用快照"}

    best = None
    for yc in (x for x in company if x.get("road") == road):
        score, info = candidate_score(ext, yc)
        if best is None or score > best[0]:
            best = (score, yc, info)
    if best is None:
        return "missing", 0, None, {}

    score, yc, info = best
    ad = info.get("areaDelta")
    pd = info.get("priceDelta")
    tr = info.get("titleRatio") or 0
    shared = info.get("shared") or []
    max_shared = max((len(x) for x in shared), default=0)
    snapshot = yc.get("sourceMode") == "har_snapshot"

    if snapshot:
        strong = pd is not None and pd <= 1 and (tr >= 0.42 or max_shared >= 4) and score >= 8
        possible = pd is not None and pd <= 30 and (tr >= 0.25 or max_shared >= 3 or pd <= 1)
    else:
        strong = score >= 8 and (ad is None or ad <= 0.35) and (pd is None or pd <= 80)
        possible = score >= 5 and (ad is None or ad <= 0.6) and (pd is None or pd <= 150)

    if strong:
        status = "company_match"
    elif possible:
        status = "review"
    else:
        status = "missing"
    return status, score, yc, info


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    company, logs, road_status = fetch_requests()
    fetch_mode = "requests"
    snapshot_meta = None

    if not company:
        browser_rows, browser_logs, browser_status = fetch_browser()
        logs.extend(browser_logs)
        if browser_rows:
            company, road_status, fetch_mode = browser_rows, browser_status, "playwright"
        else:
            snap_rows, snapshot_meta, snap_logs = load_har_snapshot()
            logs.extend(snap_logs)
            if snap_rows:
                company = snap_rows
                fetch_mode = "har_snapshot"
                scope_road = snapshot_meta.get("scopeRoad")
                road_status = {
                    road: {
                        "count": len(company) if road == scope_road else 0,
                        "url": url,
                        "available": road == scope_road,
                        "mode": "har_snapshot" if road == scope_road else "not_captured",
                    }
                    for road, url in ROAD_URLS.items()
                }
            else:
                road_status = browser_status
                fetch_mode = "blocked"

    covered_roads = {x.get("road") for x in company if x.get("road")}
    external = [x for x in state.get("listings", []) if x.get("active", True) and x.get("source") in {"591", "信義房屋"}]
    comparisons = []
    counts = {"company_match": 0, "review": 0, "missing": 0, "unavailable": 0}

    for ext in external:
        status, score, yc, info = classify(ext, company, covered_roads)
        counts[status] += 1
        comparisons.append({
            "id": ext.get("id"),
            "source": ext.get("source"),
            "road": ext.get("road"),
            "status": status,
            "statusLabel": {
                "company_match": "庫存",
                "review": "待確認",
                "missing": "未接回",
                "unavailable": "尚未比對",
            }[status],
            "score": score,
            "companyCandidate": None if not yc else {
                "id": yc.get("id"),
                "title": yc.get("title"),
                "address": yc.get("address"),
                "area": yc.get("area"),
                "price": yc.get("price"),
                "url": yc.get("url"),
                "sourceMode": yc.get("sourceMode"),
            },
            "matchInfo": info,
        })

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceDataUpdatedAt": state.get("updatedAt"),
        "mode": "preview_only",
        "fetchMode": fetch_mode,
        "company": "永慶房屋",
        "companyListingCount": len(company),
        "companySnapshotCapturedAt": snapshot_meta.get("capturedAt") if snapshot_meta else None,
        "coveredRoads": sorted(covered_roads),
        "externalActiveCount": len(external),
        "counts": counts,
        "roadStatus": road_status,
        "comparisons": comparisons,
        "logs": logs,
        "note": "PREVIEW：庫存=高信心比對到永慶公開案件；待確認=價格/文字疑似相同但證據不足；未接回=在已有公司資料的路段未比對到；尚未比對=該路段目前沒有永慶快照。HAR 快照不是即時自動資料。",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"fetchMode": fetch_mode, "company": len(company), "coveredRoads": sorted(covered_roads), "external": len(external), **counts}, ensure_ascii=False))
    for line in logs:
        print(line)


if __name__ == "__main__":
    main()
