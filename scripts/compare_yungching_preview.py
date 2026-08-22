import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path("docs/data/listings.json")
OUT_PATH = Path("docs/preview/company-gap.json")
SNAPSHOT_PATH = Path("docs/preview/yungching-har-snapshot.json")

ROADS = [
    "板橋區中山路二段",
    "板橋區三民路二段",
    "板橋區光復街",
    "板橋區萬安街",
    "板橋區林森街",
    "板橋區三民路一段",
    "板橋區翠華街",
]

HOUSEFUN_BASE = "https://buy.housefun.com.tw/region/新北市-板橋區_c/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

STOPWORDS = {
    "板橋", "板橋區", "新北市", "永慶房屋", "公司", "專約", "專任", "推薦", "好宅", "美寓", "美屋", "美宅",
    "公寓", "華廈", "大樓", "住宅", "捷運", "邊間", "採光", "三房", "兩房", "四房", "一樓", "二樓",
    "三樓", "四樓", "五樓", "全新", "裝潢", "首購", "成家", "稀有", "景觀", "低總價", "近捷運", "出價可談",
}


def norm(value):
    text = str(value or "").replace("臺", "台")
    text = text.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def parse_float(value):
    m = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(m.group()) if m else None


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


def clean_title(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_housefun_price(text):
    # Cards may contain both original and reduced prices; the last price shown is the current asking price.
    vals = []
    for raw in re.findall(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,5})(?:\.[0-9]+)?\s*萬", str(text or "")):
        try:
            n = float(raw.replace(",", ""))
        except Exception:
            continue
        if 300 <= n <= 100000:
            vals.append(n)
    return vals[-1] if vals else None


def parse_housefun_area(text):
    # First area in the listing card is the registered building area.
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*坪", str(text or ""))
    return float(m.group(1)) if m else None


def housefun_url(road, page=1):
    keyword = road.replace("板橋區", "")
    url = f"{HOUSEFUN_BASE}?kw={quote(keyword)}"
    if page > 1:
        url += f"&pg={page}"
    return url


def card_text_for_anchor(anchor, road_keyword):
    node = anchor
    best = None
    for _ in range(10):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = " ".join(node.stripped_strings)
        if road_keyword not in text or "坪" not in text:
            continue
        if "永慶房屋(股)公司" in text or "永慶直營" in text:
            best = text
            break
    return best


def parse_housefun_page(html, road, page_url):
    soup = BeautifulSoup(html, "html.parser")
    keyword = road.replace("板橋區", "")
    rows = {}

    total = None
    page_text = " ".join(soup.stripped_strings)
    m_total = re.search(r"全部\s*[（(]\s*(\d+)\s*[）)]", page_text)
    if m_total:
        total = int(m_total.group(1))

    for a in soup.select('a[href*="/buy/house/"]'):
        href = a.get("href") or ""
        m_id = re.search(r"/buy/house/(\d+)", href)
        if not m_id:
            continue
        title = clean_title(" ".join(a.stripped_strings))
        if len(title) < 2:
            continue
        text = card_text_for_anchor(a, keyword)
        if not text:
            continue
        # Only Yongching direct-company inventory. Exclude franchise brands such as 永慶不動產/有巢氏/台慶.
        if "永慶房屋(股)公司" not in text and "永慶直營" not in text:
            continue
        if "永慶不動產" in text and "永慶房屋(股)公司" not in text:
            continue

        area = parse_housefun_area(text)
        price = parse_housefun_price(text)
        house_id = m_id.group(1)
        rows[house_id] = {
            "id": f"HF:{house_id}",
            "proxyId": house_id,
            "road": road,
            "title": title,
            "address": f"新北市{road}",
            "area": area,
            "price": price,
            "url": urljoin(page_url, href),
            "text": text,
            "sourceMode": "housefun_yungching_proxy",
        }
    return list(rows.values()), total


def fetch_housefun_company():
    session = requests.Session()
    company = []
    logs = []
    status = {}

    for road in ROADS:
        all_rows = {}
        total = None
        http_codes = []
        parsed_page = False
        for page in range(1, 5):
            url = housefun_url(road, page)
            try:
                r = session.get(url, headers=HEADERS, timeout=25)
                http_codes.append(r.status_code)
                if r.status_code != 200:
                    logs.append(f"housefun {road} p{page}: HTTP {r.status_code}")
                    break
                rows, page_total = parse_housefun_page(r.text, road, url)
                if page_total is not None:
                    parsed_page = True
                    if total is None:
                        total = page_total
                before = len(all_rows)
                for row in rows:
                    all_rows[row["proxyId"]] = row
                added = len(all_rows) - before
                logs.append(f"housefun {road} p{page}: direct={len(rows)} added={added} total_page={page_total}")

                # The site currently uses roughly 30 results per page. Stop when the result count is fully covered,
                # or a later page adds nothing.
                if total is not None and page * 30 >= total:
                    break
                if page > 1 and added == 0:
                    break
            except Exception as exc:
                logs.append(f"housefun {road} p{page}: {type(exc).__name__}: {str(exc)[:100]}")
                break

        available = bool(parsed_page and http_codes and http_codes[0] == 200)
        status[road] = {
            "count": len(all_rows),
            "allBrokerCount": total,
            "http": http_codes[0] if http_codes else None,
            "url": housefun_url(road),
            "available": available,
            "mode": "housefun_yungching_proxy" if available else "unavailable",
        }
        company.extend(all_rows.values())

    return company, logs, status


def load_har_snapshot():
    if not SNAPSHOT_PATH.exists():
        return [], None, []
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    default_road = snap.get("scopeRoad")
    rows = []
    for x in snap.get("listings", []):
        row = dict(x)
        row.setdefault("road", default_road)
        row.setdefault("address", f"新北市{row.get('road') or ''}")
        row.setdefault("area", None)
        row.setdefault("text", row.get("title", ""))
        row["sourceMode"] = "har_snapshot"
        rows.append(row)
    return rows, snap, [f"HAR fallback: {len(rows)} rows; capturedAt={snap.get('capturedAt')}"]


def merge_fallback(company, road_status, logs):
    # HAR is only a fallback for a road whose Housefun proxy could not be read.
    snap_rows, snap, snap_logs = load_har_snapshot()
    logs.extend(snap_logs)
    if not snap_rows:
        return company, snap
    unavailable = {road for road, st in road_status.items() if not st.get("available")}
    existing = {(x.get("road"), norm(x.get("title")), parse_float(x.get("area")), parse_float(x.get("price"))) for x in company}
    added = 0
    for row in snap_rows:
        if row.get("road") not in unavailable:
            continue
        key = (row.get("road"), norm(row.get("title")), parse_float(row.get("area")), parse_float(row.get("price")))
        if key in existing:
            continue
        company.append(row)
        existing.add(key)
        added += 1
    if added:
        for road in unavailable:
            count = sum(1 for x in company if x.get("road") == road)
            if count:
                road_status[road]["available"] = True
                road_status[road]["mode"] = "har_snapshot_fallback"
                road_status[road]["count"] = count
        logs.append(f"HAR fallback added {added} rows")
    return company, snap


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
            score += 7
        elif area_delta <= 0.30:
            score += 4
        elif area_delta <= 0.60:
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


def classify(ext, company, road_status):
    road = ext.get("road")
    road_ready = bool((road_status.get(road) or {}).get("available"))
    if not road_ready:
        return "unavailable", 0, None, {"reason": "此路段公司公開代理資料目前不可用"}

    candidates = [x for x in company if x.get("road") == road]
    if not candidates:
        return "missing", 0, None, {"reason": "此路段公開代理資料中沒有永慶房屋直營案件"}

    best = None
    for yc in candidates:
        score, info = candidate_score(ext, yc)
        if best is None or score > best[0]:
            best = (score, yc, info)

    score, yc, info = best
    ad = info.get("areaDelta")
    pd = info.get("priceDelta")
    tr = info.get("titleRatio") or 0
    shared = info.get("shared") or []
    max_shared = max((len(x) for x in shared), default=0)

    # With the Housefun Yongching-direct proxy we usually have both registered area and asking price.
    # Strong inventory requires an area match plus either a near-identical price or meaningful title evidence.
    strong = (
        ad is not None and ad <= 0.30 and
        (
            (pd is not None and pd <= 30) or
            tr >= 0.42 or
            max_shared >= 4
        ) and score >= 9
    )
    possible = (
        (ad is not None and ad <= 0.60 and pd is not None and pd <= 150 and score >= 5) or
        (pd is not None and pd <= 30 and (tr >= 0.25 or max_shared >= 3) and score >= 5)
    )

    if strong:
        status = "company_match"
    elif possible:
        status = "review"
    else:
        status = "missing"
    return status, score, yc, info


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    company, logs, road_status = fetch_housefun_company()
    company, snapshot_meta = merge_fallback(company, road_status, logs)
    fetch_mode = "housefun_yungching_proxy" if any(st.get("mode") == "housefun_yungching_proxy" for st in road_status.values()) else "har_snapshot"

    # De-duplicate proxy rows by road + registered area + price + normalized title.
    deduped = {}
    for row in company:
        key = (row.get("road"), norm(row.get("title")), parse_float(row.get("area")), parse_float(row.get("price")))
        deduped[key] = row
    company = list(deduped.values())

    external = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") in {"591", "信義房屋"}
    ]
    comparisons = []
    counts = {"company_match": 0, "review": 0, "missing": 0, "unavailable": 0}

    for ext in external:
        status, score, yc, info = classify(ext, company, road_status)
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
        "companyDataSource": "好房網公開買屋頁（僅篩選永慶房屋(股)公司）＋必要時 HAR fallback",
        "companyListingCount": len(company),
        "companySnapshotCapturedAt": snapshot_meta.get("capturedAt") if snapshot_meta else None,
        "coveredRoads": [road for road in ROADS if (road_status.get(road) or {}).get("available")],
        "externalActiveCount": len(external),
        "counts": counts,
        "roadStatus": road_status,
        "comparisons": comparisons,
        "companyListings": company,
        "logs": logs,
        "note": "PREVIEW：庫存=以公開同步資料高信心比對到永慶房屋直營案件；待確認=坪數/價格/文字接近但證據不足；未接回=該路段公開代理資料可正常讀取，但未比對到公司直營案件；尚未比對=該路段代理資料讀取失敗。此資料是公開網站代理，不等於公司內部委託系統。",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"fetchMode": fetch_mode, "company": len(company), "roads": payload["coveredRoads"], "external": len(external), **counts}, ensure_ascii=False))
    for line in logs:
        print(line)


if __name__ == "__main__":
    main()
