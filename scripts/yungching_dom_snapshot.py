import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


OUT = Path("docs/preview/yungching-browser-snapshot.json")
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


def road_url(road: str) -> str:
    keyword = road.replace("板橋區", "")
    return f"{BASE}/list/{quote('新北市-板橋區')}_c/{quote(keyword)}_kw?od=80"


def num(value):
    if value is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group(0)) if m else None


def parse_card(raw: dict, road: str):
    text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
    url = str(raw.get("url") or "")
    mid = re.search(r"/house/(\d+)", url)
    if not mid:
        return None
    hid = mid.group(1)
    address = "新北市" + road
    pos = text.find(address)
    if pos <= 0:
        return None
    title = text[:pos].strip()
    title = re.sub(r"^(本週精選|新上|降價|專任委託)\s*", "", title).strip()
    if not title:
        return None

    ma = re.search(r"建坪\s*([0-9]+(?:\.[0-9]+)?)", text)
    area = float(ma.group(1)) if ma else None

    tail = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*$", text)
    if tail:
        price = num(tail.group(1))
    else:
        prices = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*萬", text)
        price = num(prices[-1]) if prices else None

    after = text[pos + len(address):].strip()
    after = re.sub(r"^專任委託\s*", "", after)
    mt = re.match(r"([^0-9]{1,18}?)(?:[0-9]+(?:\.[0-9]+)?年|--年)建坪", after)
    ptype = mt.group(1).strip() if mt else None

    mf = re.search(r"(?:^|\s)([0-9]+(?:~[0-9]+)?/[0-9]+樓)(?:\s|$)", text)
    floor = mf.group(1) if mf else None

    return {
        "id": hid,
        "road": road,
        "title": title[:100],
        "price": price,
        "area": area,
        "floor": floor,
        "address": address,
        "type": ptype,
        "url": url,
        "sourceMode": "yungching_browser_dom",
        "rawText": text[:700],
    }


def extract_cards(page, road: str):
    address = "新北市" + road
    return page.evaluate(
        """(address) => {
          const candidates = [];
          const seen = new Set();
          const allAnchors = Array.from(document.querySelectorAll('a[href]'));

          for (const a of allAnchors) {
            const href = a.href || '';
            const m = href.match(/\/house\/(\d+)/);
            if (!m) continue;
            let node = a;
            let best = null;
            for (let depth = 0; depth < 10 && node; depth++, node = node.parentElement) {
              const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
              if (!text.includes(address) || !text.includes('建坪')) continue;
              if (text.length < 20 || text.length > 950) continue;
              if (!best || text.length < best.text.length) best = {url: href, text, depth};
            }
            if (best) {
              const key = m[1] + '|' + best.text;
              if (!seen.has(key)) {
                seen.add(key);
                candidates.push(best);
              }
            }
          }

          // Fallback for Angular-rendered links whose raw href attributes are unusual.
          if (candidates.length === 0) {
            const containers = Array.from(document.querySelectorAll('article,li,section,div'));
            for (const el of containers) {
              const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
              if (!text.includes(address) || !text.includes('建坪')) continue;
              if (text.length < 20 || text.length > 950) continue;
              const links = Array.from(el.querySelectorAll('a[href]')).map(a => a.href || '').filter(h => /\/house\/\d+/.test(h));
              if (links.length !== 1) continue;
              const href = links[0];
              const id = (href.match(/\/house\/(\d+)/) || [])[1];
              if (!id) continue;
              const key = id + '|' + text;
              if (!seen.has(key)) {
                seen.add(key);
                candidates.push({url: href, text, depth: 99});
              }
            }
          }

          const pagination = [];
          for (const a of allAnchors) {
            const label = (a.innerText || '').replace(/\s+/g, ' ').trim();
            const href = a.href || '';
            if (!href.includes('/list/')) continue;
            if (/^\d+$/.test(label) || /下一頁|下頁|next/i.test(label) || /[?&](?:page|pg|p)=\d+/i.test(href)) {
              pagination.push({label, href});
            }
          }
          return {anchorCount: allAnchors.length, cards: candidates, pagination: pagination.slice(0,40)};
        }""",
        address,
    )


def main():
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    road_status = {}
    listings = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        for road in ROADS:
            url = road_url(road)
            info = {"mainHttp": None, "count": 0, "pagination": []}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                info["mainHttp"] = response.status if response else None
                page.wait_for_timeout(5500)
                info["title"] = page.title()[:160]
                info["roadTextCount"] = page.get_by_text(road.replace("板橋區", ""), exact=False).count()
                raw = extract_cards(page, road)
                info["anchorCount"] = raw.get("anchorCount", 0)
                info["pagination"] = raw.get("pagination") or []
                for item in raw.get("cards") or []:
                    row = parse_card(item, road)
                    if row:
                        listings[(road, row["id"])] = row
                info["count"] = sum(1 for r, _ in listings if r == road)
                info["available"] = info["mainHttp"] == 200 and info["count"] > 0
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
                info["available"] = False
            road_status[road] = info
            print(f"DOM snapshot {road}: HTTP {info.get('mainHttp')} / {info.get('count', 0)} listings / anchors {info.get('anchorCount', 0)}")

        browser.close()

    rows = list(listings.values())
    rows.sort(key=lambda x: (ROADS.index(x["road"]), x["id"]))
    payload = {
        "capturedAt": captured,
        "previewOnly": True,
        "source": "Yongching official public result cards via Surfshark + Chromium DOM",
        "availableRoads": [r for r, st in road_status.items() if st.get("available")],
        "roadStatus": road_status,
        "listingCount": len(rows),
        "listings": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"availableRoadCount": len(payload["availableRoads"]), "listingCount": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
