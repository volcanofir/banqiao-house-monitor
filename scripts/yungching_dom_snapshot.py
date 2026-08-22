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


def parse_floor(text: str):
    # Cards sometimes concatenate area and floor, e.g. "主20.241/5樓".
    m = re.search(r"\d+\.\d{1,2}(\d{1,2}/\d{1,2}樓)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<![\d.])(\d{1,2}/\d{1,2}樓)", text)
    return m.group(1) if m else None


def parse_card(raw: dict, road: str):
    text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
    url = str(raw.get("url") or "")
    mid = re.search(r"/house/(\d+)", url)
    if not mid:
        return None
    hid = mid.group(1)
    address = "新北市" + road

    if text.count("新北市") != 1 or text.count(address) != 1:
        return None

    pos = text.find(address)
    if pos <= 0:
        return None
    title = text[:pos].strip()
    title = re.sub(r"^(本週精選|新上|降價|專任委託)\s*", "", title).strip()
    if not title or "新北市" in title:
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

    return {
        "id": hid,
        "road": road,
        "title": title[:100],
        "price": price,
        "area": area,
        "floor": parse_floor(text),
        "address": address,
        "type": ptype,
        "url": url,
        "sourceMode": "yungching_browser_dom",
        "rawText": text[:700],
    }


def expand_results(page):
    """Trigger lazy/infinite loading without relying on a particular pagination selector."""
    rounds = 0
    stable = 0
    last_height = 0
    for _ in range(8):
        rounds += 1
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1400)
            # Some builds expose a load-more control instead of pure infinite scroll.
            button = page.locator("button, a").filter(has_text=re.compile(r"載入更多|查看更多|更多物件|顯示更多"))
            if button.count() > 0:
                try:
                    button.first.click(timeout=1200)
                    page.wait_for_timeout(1400)
                except Exception:
                    pass
            height = page.evaluate("document.body.scrollHeight")
            if height == last_height:
                stable += 1
            else:
                stable = 0
            last_height = height
            if stable >= 2:
                break
        except Exception:
            break
    page.evaluate("window.scrollTo(0, 0)")
    return rounds


def extract_cards(page, road: str):
    address = "新北市" + road
    return page.evaluate(
        """(address) => {
          const allAnchors = Array.from(document.querySelectorAll('a[href]'));
          const bestById = new Map();
          const containers = Array.from(document.querySelectorAll('article,li,section,div'));

          for (const el of containers) {
            const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
            if (!text.includes(address) || !text.includes('建坪')) continue;
            if (text.length < 20 || text.length > 760) continue;
            if ((text.match(/新北市/g) || []).length !== 1) continue;
            if ((text.split(address).length - 1) !== 1) continue;

            const houseLinks = [];
            for (const a of Array.from(el.querySelectorAll('a[href]'))) {
              const href = a.href || '';
              const m = href.match(/\/house\/(\d+)/);
              if (m) houseLinks.push({id: m[1], href});
            }
            const uniq = [];
            const seenIds = new Set();
            for (const x of houseLinks) {
              if (!seenIds.has(x.id)) { seenIds.add(x.id); uniq.push(x); }
            }
            if (uniq.length !== 1) continue;

            const x = uniq[0];
            const existing = bestById.get(x.id);
            if (!existing || text.length < existing.text.length) {
              bestById.set(x.id, {url: x.href, text});
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

          return {
            anchorCount: allAnchors.length,
            cards: Array.from(bestById.values()),
            pagination: pagination.slice(0,40),
          };
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
                page.wait_for_timeout(3500)
                info["loadRounds"] = expand_results(page)
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
