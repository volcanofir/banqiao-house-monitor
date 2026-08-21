import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path("docs/data/listings.json")
OUT_PATH = Path("docs/preview/company-gap.json")

ROAD_URLS = {
    "板橋區中山路二段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/中山路二段_kw?od=80",
    "板橋區三民路一段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/三民路一段_kw?od=80",
    "板橋區萬安街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/萬安街_kw?od=80",
    "板橋區林森街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/林森街_kw?od=80",
    "板橋區翠華街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/翠華街_kw?od=80",
    "板橋區光復街": "https://buy.yungching.com.tw/list/新北市-板橋區_c/光復街_kw?od=80",
    "板橋區三民路二段": "https://buy.yungching.com.tw/list/新北市-板橋區_c/三民路二段_kw?od=80",
}

PROPERTY_TYPES = (
    "住宅大樓", "辦公商業大樓", "公寓", "華廈", "店面", "透天厝", "其他", "廠辦", "套房"
)

STOPWORDS = {
    "板橋", "板橋區", "新北市", "永慶房屋", "專約", "專任", "推薦", "好宅", "美寓", "美屋", "美宅",
    "公寓", "華廈", "大樓", "住宅", "捷運", "邊間", "採光", "三房", "兩房", "四房", "一樓", "二樓",
    "三樓", "四樓", "五樓", "全新", "裝潢", "首購", "成家", "稀有", "景觀", "低總價", "近捷運",
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
    if value in (None, ""):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group()) if m else None


def extract_area(text):
    m = re.search(r"建坪\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


def extract_price(text):
    tail = text.split("永慶房屋", 1)[-1]
    values = []
    for raw in re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d+)?(?:\s*萬)?", tail):
        try:
            n = float(raw.replace(",", ""))
        except Exception:
            continue
        if 500 <= n <= 100000:
            values.append(n)
    return values[-1] if values else None


def extract_title(text):
    marker = "新北市板橋區"
    idx = text.find(marker)
    if idx > 0:
        return text[:idx].strip()
    return text[:40].strip()


def extract_address(text):
    marker = "新北市板橋區"
    idx = text.find(marker)
    if idx < 0:
        return ""
    rest = text[idx:]
    stops = [rest.find(t) for t in PROPERTY_TYPES if rest.find(t) > 0]
    end = min(stops) if stops else min(len(rest), 80)
    return rest[:end].strip()


def meaningful_tokens(text):
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", str(text or ""))
    out = set()
    for chunk in chunks:
        if chunk in STOPWORDS:
            continue
        if len(chunk) >= 3:
            out.add(chunk)
        if len(chunk) >= 5:
            for n in (3, 4):
                for i in range(len(chunk) - n + 1):
                    part = chunk[i:i+n]
                    if part not in STOPWORDS:
                        out.add(part)
    return out


def shared_token_score(a, b):
    aa = meaningful_tokens(a)
    bb = meaningful_tokens(b)
    shared = aa & bb
    if not shared:
        return 0, []
    longest = max(len(x) for x in shared)
    score = 4 if longest >= 5 else 3 if longest >= 4 else 2
    return score, sorted(shared, key=lambda x: (-len(x), x))[:5]


def listing_url_ok(href):
    return bool(re.search(r"/house/\d+", href or ""))


def parse_cards(html, road, base_url):
    soup = BeautifulSoup(html, "html.parser")
    road_keyword = road.replace("板橋區", "")
    results = []
    seen = set()
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if not listing_url_ok(href):
            continue
        text = " ".join(a.stripped_strings)
        if "新北市板橋區" not in text or road_keyword not in text:
            continue
        m = re.search(r"/house/(\d+)", href)
        if not m:
            continue
        house_id = m.group(1)
        if house_id in seen:
            continue
        seen.add(house_id)
        results.append({
            "id": house_id,
            "road": road,
            "title": extract_title(text),
            "address": extract_address(text),
            "area": extract_area(text),
            "price": extract_price(text),
            "url": urljoin(base_url, href),
            "text": text,
        })
    return results, soup


def pagination_links(soup, base_url, road):
    base = urlparse(base_url)
    road_keyword = road.replace("板橋區", "")
    links = []
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        if not label.isdigit():
            continue
        href = urljoin(base_url, a.get("href") or "")
        parsed = urlparse(href)
        if parsed.netloc != base.netloc or "/list/" not in parsed.path or "/house/" in parsed.path:
            continue
        if road_keyword not in href and road_keyword not in parsed.path:
            continue
        links.append(href)
    return links


def fetch_road(session, road, url):
    queue = [url]
    visited = set()
    all_rows = {}
    logs = []
    while queue and len(visited) < 5:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        try:
            r = session.get(current, headers=HEADERS, timeout=25)
        except Exception as exc:
            logs.append(f"{road}: request error {type(exc).__name__}")
            continue
        if r.status_code != 200:
            logs.append(f"{road}: HTTP {r.status_code}")
            continue
        rows, soup = parse_cards(r.text, road, current)
        for row in rows:
            all_rows[row["id"]] = row
        for href in pagination_links(soup, current, road):
            if href not in visited and href not in queue:
                queue.append(href)
        logs.append(f"{road}: {len(rows)} rows from page; total {len(all_rows)}")
    return list(all_rows.values()), logs


def candidate_score(ext, yc):
    ext_area = parse_float(ext.get("size"))
    ext_price = ext.get("effectivePrice")
    if ext_price is None:
        ext_price = parse_float(ext.get("price"))
    yc_area = yc.get("area")
    yc_price = yc.get("price")
    score = 0
    details = []

    area_delta = None
    if ext_area is not None and yc_area is not None:
        area_delta = abs(ext_area - yc_area)
        if area_delta <= 0.12:
            score += 4
        elif area_delta <= 0.35:
            score += 2
        elif area_delta > 1.0:
            return -99, {"areaDelta": round(area_delta, 2)}
        details.append(f"坪數差{area_delta:.2f}")

    price_delta = None
    if ext_price is not None and yc_price is not None:
        price_delta = abs(float(ext_price) - float(yc_price))
        if price_delta <= 30:
            score += 4
        elif price_delta <= 80:
            score += 3
        elif price_delta <= 150:
            score += 1
        elif price_delta > 300:
            score -= 2
        details.append(f"價格差{price_delta:.0f}萬")

    ext_text = f"{ext.get('title','')} {ext.get('address','')}"
    yc_text = f"{yc.get('title','')} {yc.get('address','')} {yc.get('text','')}"
    token_score, shared = shared_token_score(ext_text, yc_text)
    score += token_score
    if shared:
        details.append("共同詞:" + ",".join(shared))

    ratio = SequenceMatcher(None, norm(ext_text), norm(yc_text)).ratio()
    if ratio >= 0.38:
        score += 2
    elif ratio >= 0.26:
        score += 1

    return score, {
        "areaDelta": None if area_delta is None else round(area_delta, 2),
        "priceDelta": None if price_delta is None else round(price_delta, 1),
        "shared": shared,
        "textRatio": round(ratio, 3),
        "details": details,
    }


def classify(ext, company_rows):
    same_road = [x for x in company_rows if x.get("road") == ext.get("road")]
    best = None
    for yc in same_road:
        score, why = candidate_score(ext, yc)
        if best is None or score > best[0]:
            best = (score, yc, why)
    if best is None:
        return "missing", 0, None, {}

    score, yc, why = best
    area_delta = why.get("areaDelta")
    price_delta = why.get("priceDelta")
    strong = score >= 7 and (area_delta is None or area_delta <= 0.35) and (price_delta is None or price_delta <= 150)
    possible = score >= 5 and (area_delta is None or area_delta <= 0.6)
    if strong:
        status = "company_match"
    elif possible:
        status = "review"
    else:
        status = "missing"
    return status, score, yc, why


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    session = requests.Session()
    company = []
    logs = []
    road_status = {}

    for road, url in ROAD_URLS.items():
        rows, road_logs = fetch_road(session, road, url)
        company.extend(rows)
        logs.extend(road_logs)
        road_status[road] = {"count": len(rows), "url": url}

    external = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") in {"591", "信義房屋"}
    ]

    comparisons = []
    counts = {"company_match": 0, "review": 0, "missing": 0}
    for ext in external:
        status, score, yc, why = classify(ext, company)
        counts[status] += 1
        comparisons.append({
            "id": ext.get("id"),
            "source": ext.get("source"),
            "road": ext.get("road"),
            "status": status,
            "score": score,
            "companyCandidate": None if not yc else {
                "id": yc.get("id"),
                "title": yc.get("title"),
                "address": yc.get("address"),
                "area": yc.get("area"),
                "price": yc.get("price"),
                "url": yc.get("url"),
            },
            "matchInfo": why,
        })

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceDataUpdatedAt": state.get("updatedAt"),
        "mode": "preview_only",
        "company": "永慶房屋",
        "companyListingCount": len(company),
        "externalActiveCount": len(external),
        "counts": counts,
        "roadStatus": road_status,
        "comparisons": comparisons,
        "logs": logs,
        "note": "PREVIEW 比對：company_match 會隱藏；missing 顯示為公司未比對到；review 顯示為待人工確認。此為公開網站資料的近似比對，不等同內部委託系統。",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"company": len(company), "external": len(external), **counts}, ensure_ascii=False))
    for line in logs:
        print(line)


if __name__ == "__main__":
    main()
