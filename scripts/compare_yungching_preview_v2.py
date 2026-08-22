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
    "板橋區中山路二段", "板橋區三民路二段", "板橋區光復街", "板橋區萬安街",
    "板橋區林森街", "板橋區三民路一段", "板橋區翠華街",
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


def norm(v):
    t = str(v or "").replace("臺", "台")
    t = t.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", t).lower()


def num(v):
    m = re.search(r"\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else None


def housefun_url(road, page=1):
    kw = road.replace("板橋區", "")
    url = f"{HOUSEFUN_BASE}?kw={quote(kw)}"
    return url if page == 1 else f"{url}&pg={page}"


def house_ids(node):
    ids = set()
    for a in node.select('a[href*="/buy/house/"]'):
        m = re.search(r"/buy/house/(\d+)", a.get("href") or "")
        if m:
            ids.add(m.group(1))
    return ids


def find_card(anchor, house_id, keyword):
    node = anchor
    for _ in range(12):
        node = getattr(node, "parent", None)
        if node is None:
            return None, None
        text = " ".join(node.stripped_strings)
        if keyword not in text or "坪" not in text:
            continue
        ids = house_ids(node)
        # Critical guard: do not climb into the whole result list. A card may contain
        # several links, but all of them must point to the same house id.
        if ids == {house_id}:
            return node, text
    return None, None


def parse_price(text):
    vals = []
    for raw in re.findall(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,5})(?:\.[0-9]+)?\s*萬", text):
        try:
            n = float(raw.replace(",", ""))
        except Exception:
            continue
        if 300 <= n <= 100000:
            vals.append(n)
    return vals[-1] if vals else None


def parse_area(text):
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*坪", text)
    return float(m.group(1)) if m else None


def title_from_card(card, house_id, text):
    candidates = []
    for a in card.select('a[href*="/buy/house/"]'):
        m = re.search(r"/buy/house/(\d+)", a.get("href") or "")
        if not m or m.group(1) != house_id:
            continue
        s = re.sub(r"\s+", " ", " ".join(a.stripped_strings)).strip()
        if not (2 <= len(s) <= 60):
            continue
        if "萬" in s or "坪" in s or s in {"看地圖", "詳情", "收藏"}:
            continue
        chinese = len(re.findall(r"[\u4e00-\u9fff]", s))
        if chinese >= 2:
            candidates.append((chinese, len(s), s))
    if candidates:
        # Prefer the most text-rich Chinese link, which is the title rather than price/image links.
        candidates.sort(reverse=True)
        return candidates[0][2]

    # Fallback: the title is normally before the address within one listing card.
    idx = text.find("新北市板橋區")
    prefix = text[:idx].strip() if idx > 0 else ""
    prefix = re.sub(r"^(AI煥裝|AI導覽|優質|新上架|降價)+", "", prefix).strip()
    return prefix[:60] or house_id


def parse_page(html, road, page_url):
    soup = BeautifulSoup(html, "html.parser")
    keyword = road.replace("板橋區", "")
    page_text = " ".join(soup.stripped_strings)
    mt = re.search(r"全部\s*[（(]\s*(\d+)\s*[）)]", page_text)
    total = int(mt.group(1)) if mt else None
    rows = {}

    for a in soup.select('a[href*="/buy/house/"]'):
        href = a.get("href") or ""
        mid = re.search(r"/buy/house/(\d+)", href)
        if not mid:
            continue
        hid = mid.group(1)
        if hid in rows:
            continue
        card, text = find_card(a, hid, keyword)
        if card is None:
            continue
        # Only Yongching direct-company inventory. Exclude franchise brands.
        direct = "永慶房屋(股)公司" in text or "永慶直營" in text
        if not direct:
            continue
        if "永慶不動產" in text and "永慶房屋(股)公司" not in text and "永慶直營" not in text:
            continue
        if f"板橋區{keyword}" not in text and f"板橋區-{keyword}" not in text:
            continue

        rows[hid] = {
            "id": f"HF:{hid}", "proxyId": hid, "road": road,
            "title": title_from_card(card, hid, text),
            "address": f"新北市{road}", "area": parse_area(text), "price": parse_price(text),
            "url": urljoin(page_url, href), "text": text,
            "sourceMode": "housefun_yungching_proxy",
        }
    return list(rows.values()), total


def fetch_company():
    s = requests.Session()
    company, logs, status = [], [], {}
    for road in ROADS:
        rows_by_id = {}
        total = None
        first_http = None
        parsed = False
        for page in range(1, 6):
            url = housefun_url(road, page)
            try:
                r = s.get(url, headers=HEADERS, timeout=25)
                if first_http is None:
                    first_http = r.status_code
                if r.status_code != 200:
                    logs.append(f"{road} p{page}: HTTP {r.status_code}")
                    break
                rows, page_total = parse_page(r.text, road, url)
                if page_total is not None:
                    parsed = True
                    total = page_total if total is None else total
                before = len(rows_by_id)
                for row in rows:
                    rows_by_id[row["proxyId"]] = row
                added = len(rows_by_id) - before
                logs.append(f"{road} p{page}: 永慶直營 {len(rows)}，新增 {added}，全部仲介 {page_total}")
                if total is not None and page * 30 >= total:
                    break
                if page > 1 and added == 0:
                    break
            except Exception as exc:
                logs.append(f"{road} p{page}: {type(exc).__name__}: {str(exc)[:100]}")
                break
        available = bool(parsed and first_http == 200)
        status[road] = {
            "count": len(rows_by_id), "allBrokerCount": total, "http": first_http,
            "url": housefun_url(road), "available": available,
            "mode": "housefun_yungching_proxy" if available else "unavailable",
        }
        company.extend(rows_by_id.values())
    return company, logs, status


def load_har_fallback(company, status, logs):
    if not SNAPSHOT_PATH.exists():
        return company, None
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    unavailable = {r for r, st in status.items() if not st.get("available")}
    added = 0
    for src in snap.get("listings", []):
        road = src.get("road") or snap.get("scopeRoad")
        if road not in unavailable:
            continue
        x = dict(src)
        x.setdefault("road", road); x.setdefault("address", f"新北市{road}")
        x.setdefault("area", None); x.setdefault("text", x.get("title", "")); x["sourceMode"] = "har_snapshot"
        company.append(x); added += 1
    if added:
        for road in unavailable:
            count = sum(1 for x in company if x.get("road") == road)
            if count:
                status[road].update({"available": True, "count": count, "mode": "har_snapshot_fallback"})
        logs.append(f"HAR fallback added {added}")
    return company, snap


def tokens(text):
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", str(text or ""))
    out = set()
    for ch in chunks:
        if ch in STOPWORDS:
            continue
        if len(ch) >= 3:
            out.add(ch)
        for n in (3, 4, 5):
            if len(ch) >= n:
                out.update(ch[i:i+n] for i in range(len(ch)-n+1) if ch[i:i+n] not in STOPWORDS)
    return out


def score(ext, yc):
    ea, ep = num(ext.get("size")), ext.get("effectivePrice") if ext.get("effectivePrice") is not None else num(ext.get("price"))
    ya, yp = num(yc.get("area")), num(yc.get("price"))
    ad = abs(ea-ya) if ea is not None and ya is not None else None
    pd = abs(float(ep)-float(yp)) if ep is not None and yp is not None else None
    if ad is not None and ad > 1.0:
        return -99, {"areaDelta": round(ad,2), "priceDelta": pd, "shared": [], "titleRatio": 0}
    s = 0
    if ad is not None:
        s += 8 if ad <= .12 else 5 if ad <= .30 else 2 if ad <= .60 else 0
    if pd is not None:
        s += 6 if pd <= 1 else 4 if pd <= 30 else 2 if pd <= 80 else 1 if pd <= 150 else -3 if pd > 300 else 0
    et, yt = str(ext.get("title") or ""), str(yc.get("title") or "")
    shared = tokens(et) & tokens(yt)
    longest = max((len(x) for x in shared), default=0)
    if longest >= 5: s += 4
    elif longest >= 4: s += 3
    elif longest >= 3: s += 2
    tr = SequenceMatcher(None, norm(et), norm(yt)).ratio()
    if tr >= .55: s += 4
    elif tr >= .42: s += 3
    elif tr >= .30: s += 1
    return s, {"areaDelta": None if ad is None else round(ad,2), "priceDelta": None if pd is None else round(pd,1), "shared": sorted(shared,key=lambda x:(-len(x),x))[:6], "titleRatio": round(tr,3), "companySourceMode": yc.get("sourceMode")}


def classify(ext, company, status):
    road = ext.get("road")
    if not (status.get(road) or {}).get("available"):
        return "unavailable", 0, None, {"reason":"此路段公開代理資料目前不可用"}
    candidates = [x for x in company if x.get("road") == road]
    if not candidates:
        return "missing", 0, None, {"reason":"此路段公開代理資料中沒有永慶房屋直營案件"}
    ranked = [(score(ext,yc),yc) for yc in candidates]
    (best_score, info), yc = max(ranked, key=lambda z:z[0][0])
    ad, pd, tr = info.get("areaDelta"), info.get("priceDelta"), info.get("titleRatio") or 0
    longest = max((len(x) for x in info.get("shared",[])), default=0)

    strong = ad is not None and ad <= .30 and ((pd is not None and pd <= 30) or tr >= .42 or longest >= 4) and best_score >= 10
    possible = (ad is not None and ad <= .60 and pd is not None and pd <= 150 and best_score >= 6) or ((pd is not None and pd <= 30) and (tr >= .25 or longest >= 3) and best_score >= 6)
    return ("company_match" if strong else "review" if possible else "missing"), best_score, yc, info


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    company, logs, road_status = fetch_company()
    company, snap = load_har_fallback(company, road_status, logs)
    # de-dupe by proxy/source id only; do not collapse distinct units that share area/price.
    uniq = {}
    for x in company:
        uniq[(x.get("road"), x.get("id"))] = x
    company = list(uniq.values())

    external = [x for x in state.get("listings",[]) if x.get("active",True) and x.get("source") in {"591","信義房屋"}]
    counts = {"company_match":0,"review":0,"missing":0,"unavailable":0}
    comparisons = []
    for ext in external:
        st, sc, yc, info = classify(ext, company, road_status)
        counts[st] += 1
        comparisons.append({
            "id":ext.get("id"),"source":ext.get("source"),"road":ext.get("road"),"status":st,
            "statusLabel":{"company_match":"庫存","review":"待確認","missing":"未接回","unavailable":"尚未比對"}[st],
            "score":sc,
            "companyCandidate":None if yc is None else {k:yc.get(k) for k in ("id","title","address","area","price","url","sourceMode")},
            "matchInfo":info,
        })

    payload = {
        "generatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceDataUpdatedAt":state.get("updatedAt"),"mode":"preview_only","fetchMode":"housefun_yungching_proxy",
        "company":"永慶房屋","companyDataSource":"好房網公開買屋頁（僅篩選永慶房屋(股)公司）＋必要時 HAR fallback",
        "companyListingCount":len(company),"companySnapshotCapturedAt":snap.get("capturedAt") if snap else None,
        "coveredRoads":[r for r in ROADS if (road_status.get(r) or {}).get("available")],
        "externalActiveCount":len(external),"counts":counts,"roadStatus":road_status,"comparisons":comparisons,"companyListings":company,"logs":logs,
        "note":"PREVIEW：庫存=以公開同步資料高信心比對到永慶房屋直營案件；待確認=坪數/價格/文字接近但證據不足；未接回=該路段公開代理資料可正常讀取但未比對到；尚未比對=代理資料讀取失敗。公開資料不等於公司內部委託系統。"
    }
    OUT_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"company":len(company),"coveredRoads":payload["coveredRoads"],"external":len(external),**counts},ensure_ascii=False))
    for x in logs: print(x)

if __name__ == "__main__":
    main()
