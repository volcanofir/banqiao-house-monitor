import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from yungching_crypto import self_test


OUT = Path("docs/preview/yungching-official-probe.json")
SNAPSHOT = Path("docs/preview/yungching-official-snapshot.json")
BASE = "https://buy.yungching.com.tw"
ROADS = [
    "板橋區中山路二段",
    "板橋區三民路一段",
    "板橋區三民路二段",
    "板橋區翠華街",
    "板橋區林森街",
    "板橋區萬安街",
    "板橋區光復街",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def road_url(road: str) -> str:
    keyword = road.replace("板橋區", "")
    # This is the public route pattern observed from the residential-browser snapshot.
    return f"{BASE}/list/{quote('新北市-板橋區')}_c/{quote(keyword)}_kw?od=80"


def clean_text(node) -> str:
    return re.sub(r"\s+", " ", " ".join(node.stripped_strings)).strip()


def parse_title(text: str, road: str) -> str | None:
    marker = "新北市" + road
    idx = text.find(marker)
    if idx <= 0:
        return None
    title = text[:idx].strip()
    title = re.sub(r"^(新上|降價|專任委託)+", "", title).strip()
    return title[:80] or None


def parse_area(text: str) -> float | None:
    m = re.search(r"建坪\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


def parse_floor(text: str) -> str | None:
    m = re.search(r"([0-9]+(?:~[0-9]+)?/[0-9]+樓)", text)
    return m.group(1) if m else None


def parse_cards(html: str, road: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    road_text = road.replace("板橋區", "")

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        m = re.search(r"/house/(\d+)", href)
        if not m:
            continue
        hid = m.group(1)

        node = anchor
        selected = None
        for _ in range(8):
            node = getattr(node, "parent", None)
            if node is None:
                break
            text = clean_text(node)
            if road_text in text and "建坪" in text and "永慶房屋" in text:
                selected = node
                break
        if selected is None:
            continue

        text = clean_text(selected)
        if f"板橋區{road_text}" not in text:
            continue
        title = parse_title(text, road)
        found[hid] = {
            "id": hid,
            "road": road,
            "title": title or hid,
            "area": parse_area(text),
            "floor": parse_floor(text),
            "url": href if href.startswith("http") else BASE + href,
            "sourceMode": "yungching_official_html",
        }

    return list(found.values())


def fetch_one(session: requests.Session, road: str) -> tuple[list[dict], dict]:
    url = road_url(road)
    info = {"road": road, "url": url, "http": None, "count": 0, "available": False, "mode": "official_html_probe"}
    try:
        r = session.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        info["http"] = r.status_code
        info["finalUrl"] = r.url
        info["contentLength"] = len(r.content)
        info["contentType"] = r.headers.get("content-type")
        if r.status_code != 200:
            info["error"] = f"HTTP {r.status_code}"
            return [], info
        rows = parse_cards(r.text, road)
        info["count"] = len(rows)
        info["available"] = len(rows) > 0
        if not rows:
            info["error"] = "HTTP 200 but no reliable official listing cards parsed"
        return rows, info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        return [], info


def probe_chunk(session: requests.Session) -> dict:
    # The filename was identified from the current public frontend bundle.
    url = f"{BASE}/mansion/chunk-B7SBOXYM.js"
    result = {"url": url, "http": None, "contentLength": 0, "hasAesCbc": False, "hasPbkdf2": False}
    try:
        r = session.get(url, headers=HEADERS, timeout=20)
        result["http"] = r.status_code
        result["contentLength"] = len(r.content)
        if r.status_code == 200:
            result["hasAesCbc"] = "AES-CBC" in r.text
            result["hasPbkdf2"] = "PBKDF2" in r.text
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
    return result


def main() -> None:
    crypto = self_test()
    session = requests.Session()
    road_status = {}
    listings = []

    for road in ROADS:
        rows, info = fetch_one(session, road)
        road_status[road] = info
        listings.extend(rows)
        print(f"official probe {road}: HTTP {info.get('http')} / {len(rows)} rows")

    # Dedupe official HTML rows by house id.
    unique = {}
    for row in listings:
        unique[(row.get("road"), row.get("id"))] = row
    listings = list(unique.values())

    chunk = probe_chunk(session)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    available_roads = [r for r, st in road_status.items() if st.get("available")]
    payload = {
        "generatedAt": now,
        "previewOnly": True,
        "crypto": crypto,
        "frontendChunk": chunk,
        "roadStatus": road_status,
        "availableRoadCount": len(available_roads),
        "listingCount": len(listings),
        "readyForComparison": len(available_roads) == len(ROADS) and len(listings) > 0,
        "note": "Preview-only official Yongching acquisition probe. It does not replace the current Housefun proxy unless a later guarded integration explicitly accepts the official snapshot.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = {
        "capturedAt": now,
        "source": "Yongching official public HTML probe",
        "previewOnly": True,
        "availableRoads": available_roads,
        "roadStatus": road_status,
        "listingCount": len(listings),
        "listings": listings,
    }
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "cryptoOk": crypto["knownVectorMatch"] and crypto["roundtripOk"],
        "availableRoadCount": len(available_roads),
        "listingCount": len(listings),
        "chunkHttp": chunk.get("http"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
