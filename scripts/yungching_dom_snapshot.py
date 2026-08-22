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
    # Keep the whole subject-floor expression, including split-level units such as
    # "14~15/16樓". Cards can concatenate area + floor, e.g. "主20.241/5樓".
    m = re.search(r"(\d{1,2}(?:\s*[~～-]\s*\d{1,2})?/\d{1,2}樓)", text)
    if m:
        return re.sub(r"\s+", "", m.group(1)).replace("～", "~")
    return None


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
          const selector = 'a,button,[role="button"]';
          for (const el of Array.from(document.querySelectorAll(selector))) {
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute('aria-label'));
            const title = clean(el.getAttribute('title'));
            const cls = typeof el.className === 'string' ? el.className : '';
            const current = el.getAttribute('aria-current') || '';
            const hay = [text, aria, title, cls, current].join(' ');
            const paginationish = /^\d{1,3}$/.test(text) || /下一|下頁|next|上一|上頁|prev|page|pager|pagination|更多|more|›|»|‹|«|current|active/i.test(hay);
            if (!paginationish) continue;
            out.push({
              tag: el.tagName,
              text: text.slice(0,80),
              aria: aria.slice(0,120),
              title: title.slice(0,120),
              className: cls.slice(0,180),
              ariaCurrent: current,
              href: el.href || null,
              disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
            });
          }
          return out.slice(0,100);
        }"""
    )


def click_semantic_next(page):
    """Click a clearly labelled next-page/load-more control when Yongching exposes one."""
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const els = Array.from(document.querySelectorAll('a,button,[role="button"]'));
          for (const el of els) {
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute('aria-label'));
            const title = clean(el.getAttribute('title'));
            const hay = [text, aria, title].join(' ');
            if (!/(下一頁|下頁|下一页|next page|load more|載入更多|查看更多|更多物件|顯示更多)/i.test(hay)) continue;
            el.click();
            return {clicked:true, mode:'semantic', text, aria, title, href:el.href || null};
          }
          return {clicked:false};
        }"""
    )


def click_numeric_page(page, target: int):
    """Safely click a numeric page control only when it lives in a pagination-like group.

    Yongching's rendered list often exposes only numeric controls (1,2,3...) rather than
    an element literally labelled "下一頁". We require multiple sibling page numbers or
    a pagination/pager/page class/role before clicking, so unrelated numeric UI is ignored.
    """
    return page.evaluate(
        """(target) => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const selector = 'a,button,[role="button"]';
          const wanted = String(target);
          const candidates = Array.from(document.querySelectorAll(selector)).filter(el => {
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
            if (clean(el.innerText) !== wanted) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          });

          function paginationScore(el) {
            let node = el;
            let best = 0;
            for (let depth = 0; depth < 6 && node; depth++, node = node.parentElement) {
              const cls = typeof node.className === 'string' ? node.className : '';
              const id = node.id || '';
              const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
              const aria = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
              const hay = [cls,id,role,aria].join(' ');
              const nums = Array.from(node.querySelectorAll ? node.querySelectorAll(selector) : [])
                .map(x => clean(x.innerText)).filter(x => /^\d{1,3}$/.test(x));
              const uniqueNums = new Set(nums);
              let score = 0;
              if (/page|pager|pagination/i.test(hay)) score += 10;
              if (/navigation/i.test(role)) score += 6;
              if (uniqueNums.size >= 2) score += 4;
              if (uniqueNums.has('1') && uniqueNums.has(wanted)) score += 3;
              if (uniqueNums.size >= 3) score += 2;
              best = Math.max(best, score);
            }
            return best;
          }

          let best = null;
          for (const el of candidates) {
            const score = paginationScore(el);
            if (score < 4) continue;
            if (!best || score > best.score) best = {el, score};
          }
          if (!best) return {clicked:false};
          const el = best.el;
          const beforeUrl = location.href;
          el.click();
          return {
            clicked:true,
            mode:'numeric',
            target,
            score:best.score,
            text:clean(el.innerText),
            href:el.href || null,
            beforeUrl,
          };
        }""",
        target,
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


def exhaust_lazy_load(page, road: str, all_rows: dict, rounds=8):
    stable = 0
    last_height = 0
    anchor_count = 0
    used = 0
    for _ in range(rounds):
        used += 1
        rows, anchor_count = collect_current(page, road)
        all_rows.update(rows)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1200)
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            stable += 1
        else:
            stable = 0
        last_height = height
        if stable >= 2:
            break
    return used, anchor_count


def collect_road(page, road: str):
    """Collect rendered cards, lazy loading, and Yongching numeric/semantic pagination."""
    all_rows = {}
    load_rounds = 0
    page_rounds = 0
    anchor_count = 0
    next_clicks = []

    used, anchor_count = exhaust_lazy_load(page, road, all_rows)
    load_rounds += used

    # Follow up to four extra result pages. Prefer an explicit next/load-more control;
    # when Yongching only renders numeric pagination, safely click 2, 3, 4, 5.
    for target_page in range(2, 6):
        controls_before = page_controls(page)
        action = click_semantic_next(page)
        if not action.get("clicked"):
            action = click_numeric_page(page, target_page)
        if not action.get("clicked"):
            break

        page_rounds += 1
        next_clicks.append(action)
        before_ids = set(all_rows)
        page.wait_for_timeout(2200)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        used, anchor_count = exhaust_lazy_load(page, road, all_rows, rounds=6)
        load_rounds += used

        if len(next_clicks) == 1:
            next_clicks[0]["controlsBefore"] = controls_before[:30]
        if set(all_rows) == before_ids:
            # A click that does not produce any new listing ids is not a real next page.
            break

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
