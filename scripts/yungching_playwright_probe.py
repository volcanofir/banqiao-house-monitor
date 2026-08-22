import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from playwright.sync_api import sync_playwright


OUT = Path("docs/preview/yungching-playwright-probe.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
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


def number_or_none(value):
    if value is None:
        return None
    try:
        text = str(value).replace(",", "").strip()
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group(0)) if m else None
    except Exception:
        return None


def parse_ga4_product(raw: str) -> dict:
    raw = unquote(raw or "")
    fields = {}
    for part in raw.split("~"):
        if len(part) < 3:
            continue
        code = part[:2]
        value = part[2:]
        if code in {"id", "nm", "pr", "br", "ca", "c2", "c3", "c4", "c5"}:
            fields[code] = value
    return fields


def normalize_candidate(row: dict, road: str, source_mode: str) -> dict | None:
    hid = row.get("id") or row.get("item_id") or row.get("caseSId") or row.get("caseId")
    title = row.get("title") or row.get("item_name") or row.get("caseName") or row.get("name")
    if hid is not None:
        hid = str(hid).strip()
    if title is not None:
        title = re.sub(r"\s+", " ", str(title)).strip()
    if not hid and not title:
        return None

    price = row.get("price")
    area = row.get("area") or row.get("regArea")
    floor = row.get("floor")
    address = row.get("address")
    url = row.get("url")

    if hid and hid.isdigit() and not url:
        url = f"{BASE}/house/{hid}"

    return {
        "id": hid,
        "road": road,
        "title": title or hid,
        "price": number_or_none(price),
        "area": number_or_none(area),
        "floor": str(floor).strip() if floor not in (None, "") else None,
        "address": str(address).strip() if address not in (None, "") else None,
        "url": url,
        "sourceMode": source_mode,
    }


def merge_candidate(target: dict, incoming: dict):
    for key in ("title", "price", "area", "floor", "address", "url", "type"):
        if target.get(key) in (None, "", target.get("id")) and incoming.get(key) not in (None, ""):
            target[key] = incoming[key]
    modes = set(str(target.get("sourceMode") or "").split("+")) | set(str(incoming.get("sourceMode") or "").split("+"))
    target["sourceMode"] = "+".join(sorted(x for x in modes if x))


def extract_data_layer(page, road: str) -> tuple[list[dict], dict]:
    result = page.evaluate(
        """() => {
          const dl = Array.isArray(window.dataLayer) ? window.dataLayer : [];
          const rows = [];
          const eventNames = [];
          const seen = new Set();
          function scalar(v) { return (typeof v === 'string' || typeof v === 'number') ? v : null; }
          function get(o, keys) { for (const k of keys) if (o && o[k] !== undefined && o[k] !== null) return o[k]; return null; }
          function maybeItem(o, path, eventName) {
            if (!o || typeof o !== 'object' || Array.isArray(o)) return;
            const id = get(o, ['item_id','itemId','caseSId','caseSid','caseId','case_id']);
            const name = get(o, ['item_name','itemName','caseName','title','name']);
            const price = get(o, ['price','item_price','casePrice','salePrice']);
            const address = get(o, ['address','caseAddress','item_address']);
            const pin = o.pinInfo && typeof o.pinInfo === 'object' ? o.pinInfo : {};
            const area = get(o, ['area','regArea','buildingArea']) ?? get(pin, ['regArea','area']);
            const floor = get(o, ['floor','floorInfo']) ?? get(pin, ['floor','floorInfo']);
            const url = get(o, ['url','item_url','caseUrl','link']);
            if (id === null && name === null) return;
            const key = String(id ?? '') + '|' + String(name ?? '') + '|' + path;
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({id: scalar(id), title: scalar(name), price: scalar(price), address: scalar(address), area: scalar(area), floor: scalar(floor), url: scalar(url), event: eventName, path});
          }
          function walk(v, path, eventName, depth) {
            if (depth > 6 || v === null || v === undefined) return;
            if (Array.isArray(v)) { for (let i = 0; i < Math.min(v.length, 120); i++) walk(v[i], path + '[' + i + ']', eventName, depth + 1); return; }
            if (typeof v !== 'object') return;
            maybeItem(v, path, eventName);
            for (const [k, child] of Object.entries(v)) { if (k !== 'gtm.uniqueEventId') walk(child, path + '.' + k, eventName, depth + 1); }
          }
          dl.forEach((entry, i) => {
            const eventName = entry && typeof entry === 'object' ? (entry.event || entry.event_name || null) : null;
            if (eventName) eventNames.push(String(eventName));
            walk(entry, 'dataLayer[' + i + ']', eventName, 0);
          });
          return {length: dl.length, events: [...new Set(eventNames)].slice(0,80), rows: rows.slice(0,500)};
        }"""
    )
    rows = []
    for raw in result.get("rows") or []:
        row = normalize_candidate(raw, road, "yungching_browser_datalayer")
        if row:
            row["event"] = raw.get("event")
            rows.append(row)
    return rows, {
        "dataLayerLength": result.get("length", 0),
        "dataLayerEvents": result.get("events") or [],
        "dataLayerCandidateCount": len(rows),
    }


def parse_dom_card(raw: dict, road: str) -> dict | None:
    text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
    href = str(raw.get("url") or "").strip()
    id_match = re.search(r"/house/(\d+)", href)
    if not id_match:
        return None
    hid = id_match.group(1)
    full_address = "新北市" + road
    marker = text.find(full_address)
    if marker <= 0:
        return None

    title = text[:marker].strip()
    title = re.sub(r"^(本週精選|新上|降價|專任委託)\s*", "", title).strip()
    if not title:
        return None

    area_m = re.search(r"建坪\s*([0-9]+(?:\.[0-9]+)?)", text)
    area = float(area_m.group(1)) if area_m else None

    tail_price = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*$", text)
    if tail_price:
        price = number_or_none(tail_price.group(1))
    else:
        prices = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*萬", text)
        price = number_or_none(prices[-1]) if prices else None

    after_addr = text[marker + len(full_address):].strip()
    after_addr = re.sub(r"^專任委託\s*", "", after_addr)
    type_m = re.match(r"([^0-9]{1,16}?)(?:[0-9]+(?:\.[0-9]+)?年|--年)建坪", after_addr)
    ptype = type_m.group(1).strip() if type_m else None

    floor = None
    floor_m = re.search(r"(?:^|\s)([0-9]+(?:~[0-9]+)?/[0-9]+樓)(?:\s|$)", text)
    if floor_m:
        floor = floor_m.group(1)

    return {
        "id": hid,
        "road": road,
        "title": title[:100],
        "price": price,
        "area": area,
        "floor": floor,
        "address": full_address,
        "type": ptype,
        "url": href,
        "sourceMode": "yungching_browser_dom",
        "rawText": text[:700],
    }


def extract_dom_cards(page, road: str) -> tuple[list[dict], list[dict], dict]:
    road_text = road.replace("板橋區", "")
    result = page.evaluate(
        """(roadText) => {
          const address = '新北市板橋區' + roadText;
          const anchors = Array.from(document.querySelectorAll('a[href*="/house/"]'));
          const cards = [];
          const seen = new Set();
          const pagination = [];

          for (const a of anchors) {
            const href = a.href || '';
            const m = href.match(/\/house\/(\d+)/);
            if (!m) continue;
            let node = a;
            let best = null;
            for (let depth = 0; depth < 9 && node; depth++, node = node.parentElement) {
              const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
              if (!text.includes(address) || !text.includes('建坪')) continue;
              if (text.length < 20 || text.length > 900) continue;
              if (!best || text.length < best.text.length) best = {text, url: href, id: m[1], depth};
            }
            if (!best) continue;
            const key = best.id + '|' + best.text;
            if (seen.has(key)) continue;
            seen.add(key);
            cards.push(best);
          }

          for (const a of Array.from(document.querySelectorAll('a[href]'))) {
            const href = a.href || '';
            const label = (a.innerText || '').trim();
            if (!href.includes('/list/') || !href.includes(encodeURIComponent(roadText)) && !decodeURIComponent(href).includes(roadText)) continue;
            if (/^\d+$/.test(label) || /page|pg=|p=/.test(href)) pagination.push({label, href});
          }
          return {cards, pagination: pagination.slice(0,30), anchorCount: anchors.length};
        }""",
        road_text,
    )

    parsed = []
    for raw in result.get("cards") or []:
        row = parse_dom_card(raw, road)
        if row:
            parsed.append(row)

    by_id = {}
    for row in parsed:
        if row["id"] not in by_id:
            by_id[row["id"]] = row
        else:
            merge_candidate(by_id[row["id"]], row)

    sample = list(by_id.values())[:12]
    diag = {
        "domHouseAnchorCount": result.get("anchorCount", 0),
        "domListingCount": len(by_id),
        "pagination": result.get("pagination") or [],
    }
    return list(by_id.values()), sample, diag


def main():
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "probeRevision": 4,
        "network": {
            "surfsharkWorkflowOutcome": os.environ.get("YUNGCHING_PROBE_VPN_OUTCOME"),
            "vpnConnected": os.environ.get("VPN_CONNECTED") == "true",
            "beforeIp": os.environ.get("VPN_BEFORE_IP"),
            "exitIp": os.environ.get("VPN_EXIT_IP"),
        },
        "browser": {"engine": "chromium", "headless": True},
        "roadStatus": {},
        "apiResponses": [],
        "analytics": {"events": []},
    }
    official_rows = {}
    current_road = {"value": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()
        payload["browser"]["userAgent"] = page.evaluate("navigator.userAgent")
        payload["browser"]["webdriver"] = page.evaluate("navigator.webdriver")

        def record_api(response):
            if "buy.yungching.com.tw/api/" not in response.url:
                return
            payload["apiResponses"].append({
                "road": current_road["value"],
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "contentType": response.headers.get("content-type"),
            })

        def record_analytics(request):
            url = request.url
            if "collect" not in url or not any(host in url for host in ("google-analytics.com", "googletagmanager.com")):
                return
            params = parse_qs(urlsplit(url).query, keep_blank_values=True)
            if request.post_data:
                for key, vals in parse_qs(request.post_data, keep_blank_values=True).items():
                    params.setdefault(key, []).extend(vals)
            event_name = (params.get("en") or [None])[0]
            product_count = 0
            for key in sorted(params):
                if not re.fullmatch(r"pr\d+", key):
                    continue
                for raw in params[key]:
                    if parse_ga4_product(raw):
                        product_count += 1
            if event_name or product_count:
                payload["analytics"]["events"].append({
                    "road": current_road["value"],
                    "event": event_name,
                    "productCount": product_count,
                })

        page.on("response", record_api)
        page.on("request", record_analytics)

        for road in ROADS:
            current_road["value"] = road
            api_start = len(payload["apiResponses"])
            analytics_start = len(payload["analytics"]["events"])
            url = road_url(road)
            info = {"road": road, "url": url, "mainHttp": None, "available": False}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                info["mainHttp"] = response.status if response else None
                page.wait_for_timeout(6500)
                info["finalUrl"] = page.url
                info["title"] = page.title()[:160]
                info["contentLength"] = len(page.content())
                info["roadTextCount"] = page.get_by_text(road.replace("板橋區", ""), exact=False).count()

                dl_rows, dl_diag = extract_data_layer(page, road)
                info.update(dl_diag)
                info["dataLayerSamples"] = dl_rows[:4]

                dom_rows, dom_samples, dom_diag = extract_dom_cards(page, road)
                info.update(dom_diag)
                info["domSamples"] = dom_samples
                for row in dom_rows:
                    official_rows[(road, row["id"])] = row

                new_api = payload["apiResponses"][api_start:]
                new_analytics = payload["analytics"]["events"][analytics_start:]
                info["apiResponseCount"] = len(new_api)
                info["apiStatuses"] = sorted({x["status"] for x in new_api})
                info["listApiStatuses"] = [x["status"] for x in new_api if "/api/v2/list" in x["url"]]
                info["analyticsEventCount"] = len(new_analytics)
                info["analyticsProductCount"] = sum(x.get("productCount", 0) for x in new_analytics)
                info["available"] = info["mainHttp"] == 200 and info.get("domListingCount", 0) > 0
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            payload["roadStatus"][road] = info
            print(
                f"chromium probe {road}: HTTP {info.get('mainHttp')} / "
                f"DOM listings {info.get('domListingCount', 0)} / "
                f"dataLayer {info.get('dataLayerCandidateCount', 0)} / APIs {info.get('apiStatuses', [])}"
            )

        browser.close()

    listings = list(official_rows.values())
    listings.sort(key=lambda x: (ROADS.index(x["road"]) if x.get("road") in ROADS else 999, str(x.get("id") or "")))
    payload["availableRoadCount"] = sum(1 for x in payload["roadStatus"].values() if x.get("available"))
    payload["apiResponseCount"] = len(payload["apiResponses"])
    payload["api200Count"] = sum(1 for x in payload["apiResponses"] if x.get("status") == 200)
    payload["browserListingCount"] = len(listings)
    payload["note"] = "Preview-only Surfshark + Chromium probe. Official listing rows are parsed from rendered Yongching result cards; dataLayer items are retained only as diagnostics because they can contain recommendations."
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = {
        "capturedAt": payload["generatedAt"],
        "previewOnly": True,
        "source": "Yongching official public result cards via Surfshark + Chromium",
        "network": payload["network"],
        "availableRoads": [r for r, st in payload["roadStatus"].items() if st.get("available")],
        "roadStatus": {r: {
            "mainHttp": st.get("mainHttp"),
            "count": st.get("domListingCount", 0),
            "roadTextCount": st.get("roadTextCount", 0),
            "pagination": st.get("pagination") or [],
        } for r, st in payload["roadStatus"].items()},
        "listingCount": len(listings),
        "listings": listings,
    }
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "vpnConnected": payload["network"]["vpnConnected"],
        "availableRoadCount": payload["availableRoadCount"],
        "apiResponseCount": payload["apiResponseCount"],
        "api200Count": payload["api200Count"],
        "browserListingCount": payload["browserListingCount"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
