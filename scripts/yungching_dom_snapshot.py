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
        "text": text[:700],
        "rawText": text[:700],
    }


def page_controls(page):
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const out = [];
          for (const el of Array.from(document.querySelectorAll('a,button'))) {
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute('aria-label'));
            const title = clean(el.getAttribute('title'));
            const cls = typeof el.className === 'string' ? el.className : '';
            const hay = [text, aria, title, cls].join(' ');
            const paginationish = /^\d{1,2}$/.test(text) || /下一|下頁|next|上一|上頁|prev|page|pager|pagination|更多|more|›|»|‹|«/i.test(hay);
            if (!paginationish) continue;
            out.push({
              tag: el.tagName,
              text: text.slice(0,80),
              aria: aria.slice(0,120),
              title: title.slice(0,120),
              className: cls.slice(0,180),
              href: el.href || null,
              disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
            });
          }
          return out.slice(0,80);
        }"""
    )


def click_semantic_next(page):
    """Click only a clearly labelled next-page/load-more control; never guess arbitrary numeric buttons."""
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const els = Array.from(document.querySelectorAll('a,button'));
          for (const el of els) {
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute('aria-label'));
            const title = clean(el.getAttribute('title'));
            const hay = [text, aria, title].join(' ');
            if (!/(下一頁|下頁|下一页|next page|load more|載入更多|查看更多|更多物件|顯示更多)/i.test(hay)) continue;
            el.click();
            return {clicked:true, text, aria, title, href:el.href || null};
          }
          return {clicked:false};
        }"""
    )


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
          return {anchorCount: allAnchors.length, cards: Array.from(bestById.values())};
        }""",
        address,
    )


def collect_current(page, road: str):
    raw = extract_cards(page, road)
    rows = {}
    for item in raw.get("cards") or []:
        row = parse_card(item, road)
        if row:
            rows[row["id"]] = row
    return rows, raw.get("anchorCount", 0)


def collect_road(page, road: str):
    """Collect lazy-loaded cards and follow a clearly-labelled next control when present."""
    all_rows = {}
    load_rounds = 0
    page_rounds = 0
    stable = 0
    last_height = 0
    anchor_count = 0
    next_clicks = []

    # First exhaust normal lazy/infinite loading.
    for _ in range(8):
        load_rounds += 1
        rows, anchor_count = collect_current(page, road)
        all_rows.update(rows)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1300)
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            stable += 1
        else:
            stable = 0
        last_height = height
        if stable >= 2:
            break

    # Then follow semantic next/load-more controls only, up to 4 result pages.
    for _ in range(4):
        controls_before = page_controls(page)
        action = click_semantic_next(page)
        if not action.get("clicked"):
            break
        page_rounds += 1
        next_clicks.append(action)
        page.wait_for_timeout(2400)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1300)
        rows, anchor_count = collect_current(page, road)
        before = len(all_rows)
        all_rows.update(rows)
        if len(all_rows) == before:
            break
        # Keep one small diagnostic sample around the control state after a successful click.
        if len(next_clicks) == 1:
            next_clicks[0]["controlsBefore"] = controls_before[:20]

    page.evaluate("window.scrollTo(0, 0)")
    rows, anchor_count = collect_current(page, road)
    all_rows.update(rows)
    return all_rows, {
        "loadRounds": load_rounds,
        "pageRounds": page_rounds,
        "nextClicks": next_clicks,
        "anchorCount": anchor_count,
        "controls": page_controls(page),
    }


def result_summary(page, road: str):
    try:
        body = re.sub(r"\s+", " ", page.locator("body").inner_text(timeout=8000)).strip()
    except Exception:
        return []
    keyword = road.replace("板橋區", "")
    snippets = []
    for pat in (
        rf".{{0,80}}{re.escape(keyword)}.{{0,140}}(?:筆|件|戶|結果).{{0,80}}",
        r".{0,80}(?:共|全部|找到|搜尋).{0,50}\d+.{0,30}(?:筆|件|戶).{0,80}",
    ):
        for m in re.finditer(pat, body):
            s = m.group(0).strip()
            if s not in snippets:
                snippets.append(s[:360])
            if len(snippets) >= 6:
                return snippets
    return snippets


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
            info = {"mainHttp": None, "count": 0}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                info["mainHttp"] = response.status if response else None
                page.wait_for_timeout(3500)
                info["title"] = page.title()[:160]
                info["roadTextCount"] = page.get_by_text(road.replace("板橋區", ""), exact=False).count()
                info["summary"] = result_summary(page, road)
                rows, diag = collect_road(page, road)
                info.update(diag)
                for row in rows.values():
                    listings[(road, row["id"])] = row
                info["count"] = len(rows)
                info["available"] = info["mainHttp"] == 200 and info["count"] > 0
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
                info["available"] = False
            road_status[road] = info
            print(
                f"DOM snapshot {road}: HTTP {info.get('mainHttp')} / {info.get('count', 0)} listings / "
                f"pageRounds {info.get('pageRounds', 0)} / anchors {info.get('anchorCount', 0)}"
            )

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
