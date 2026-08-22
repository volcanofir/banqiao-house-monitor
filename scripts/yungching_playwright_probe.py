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
    """Parse GA4 Measurement Protocol product encoding (pr1/pr2/...)."""
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
    for key in ("title", "price", "area", "floor", "address", "url"):
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

          function scalar(v) {
            return (typeof v === 'string' || typeof v === 'number') ? v : null;
          }
          function get(o, keys) {
            for (const k of keys) {
              if (o && o[k] !== undefined && o[k] !== null) return o[k];
            }
            return null;
          }
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
            if (Array.isArray(v)) {
              for (let i = 0; i < Math.min(v.length, 120); i++) walk(v[i], path + '[' + i + ']', eventName, depth + 1);
              return;
            }
            if (typeof v !== 'object') return;
            maybeItem(v, path, eventName);
            for (const [k, child] of Object.entries(v)) {
              if (k === 'gtm.uniqueEventId') continue;
              walk(child, path + '.' + k, eventName, depth + 1);
            }
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
    diag = {"dataLayerLength": result.get("length", 0), "dataLayerEvents": result.get("events") or [], "dataLayerCandidateCount": len(rows)}
    return rows, diag


def extract_dom_diagnostics(page, road: str) -> list[dict]:
    road_text = road.replace("板橋區", "")
    return page.evaluate(
        """(roadText) => {
          const out = [];
          const seen = new Set();
          const els = Array.from(document.querySelectorAll('article,li,a,div,section'));
          for (const el of els) {
            const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
            if (!text.includes(roadText) || !text.includes('萬') || !text.includes('坪')) continue;
            if (text.length < 25 || text.length > 700 || seen.has(text)) continue;
            seen.add(text);
            const links = Array.from(el.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean).slice(0,5);
            out.push({text: text.slice(0,650), links});
            if (out.length >= 12) break;
          }
          return out;
        }""",
        road_text,
    )


def main():
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "probeRevision": 3,
        "network": {
            "surfsharkWorkflowOutcome": os.environ.get("YUNGCHING_PROBE_VPN_OUTCOME"),
            "vpnConnected": os.environ.get("VPN_CONNECTED") == "true",
            "beforeIp": os.environ.get("VPN_BEFORE_IP"),
            "exitIp": os.environ.get("VPN_EXIT_IP"),
        },
        "browser": {"engine": "chromium", "headless": True},
        "roadStatus": {},
        "apiResponses": [],
        "analytics": {"events": [], "items": []},
    }
    all_candidates = {}
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
            products = []
            for key in sorted(params):
                if not re.fullmatch(r"pr\d+", key):
                    continue
                for raw in params[key]:
                    parsed = parse_ga4_product(raw)
                    if not parsed:
                        continue
                    products.append(parsed)
                    row = normalize_candidate({
                        "id": parsed.get("id"),
                        "title": parsed.get("nm"),
                        "price": parsed.get("pr"),
                    }, current_road["value"] or "", "yungching_browser_ga4")
                    if row:
                        k = (row.get("road"), row.get("id") or row.get("title"))
                        if k in all_candidates:
                            merge_candidate(all_candidates[k], row)
                        else:
                            all_candidates[k] = row
            if event_name or products:
                payload["analytics"]["events"].append({
                    "road": current_road["value"],
                    "event": event_name,
                    "productCount": len(products),
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
                info["houseLinkCount"] = page.locator('a[href*="/house/"]').count()
                info["roadTextCount"] = page.get_by_text(road.replace("板橋區", ""), exact=False).count()

                dl_rows, dl_diag = extract_data_layer(page, road)
                info.update(dl_diag)
                for row in dl_rows:
                    k = (row.get("road"), row.get("id") or row.get("title"))
                    if k in all_candidates:
                        merge_candidate(all_candidates[k], row)
                    else:
                        all_candidates[k] = row

                info["domSamples"] = extract_dom_diagnostics(page, road)
                new_api = payload["apiResponses"][api_start:]
                new_analytics = payload["analytics"]["events"][analytics_start:]
                info["apiResponseCount"] = len(new_api)
                info["apiStatuses"] = sorted({x["status"] for x in new_api})
                info["listApiStatuses"] = [x["status"] for x in new_api if "/api/v2/list" in x["url"]]
                info["analyticsEventCount"] = len(new_analytics)
                info["analyticsProductCount"] = sum(x.get("productCount", 0) for x in new_analytics)
                road_candidates = [x for (r, _), x in all_candidates.items() if r == road]
                info["browserListingCandidateCount"] = len(road_candidates)
                info["available"] = info["mainHttp"] == 200 and len(road_candidates) > 0
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            payload["roadStatus"][road] = info
            print(
                f"chromium probe {road}: HTTP {info.get('mainHttp')} / "
                f"candidates {info.get('browserListingCandidateCount', 0)} / "
                f"analytics products {info.get('analyticsProductCount', 0)} / APIs {info.get('apiStatuses', [])}"
            )

        browser.close()

    candidates = list(all_candidates.values())
    candidates.sort(key=lambda x: (ROADS.index(x["road"]) if x.get("road") in ROADS else 999, str(x.get("id") or "")))
    payload["analytics"]["items"] = candidates[:500]
    payload["availableRoadCount"] = sum(1 for x in payload["roadStatus"].values() if x.get("available"))
    payload["apiResponseCount"] = len(payload["apiResponses"])
    payload["api200Count"] = sum(1 for x in payload["apiResponses"] if x.get("status") == 200)
    payload["browserListingCount"] = len(candidates)
    payload["note"] = "Preview-only Surfshark + Chromium probe. Listing candidates are extracted from post-render browser dataLayer/GA4 data; this does not alter the active company comparison source."
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = {
        "capturedAt": payload["generatedAt"],
        "previewOnly": True,
        "source": "Yongching official public site via Surfshark + Chromium; post-render dataLayer/GA4 extraction",
        "network": payload["network"],
        "availableRoads": [r for r, st in payload["roadStatus"].items() if st.get("available")],
        "roadStatus": {r: {
            "mainHttp": st.get("mainHttp"),
            "candidateCount": st.get("browserListingCandidateCount", 0),
            "analyticsProductCount": st.get("analyticsProductCount", 0),
            "dataLayerCandidateCount": st.get("dataLayerCandidateCount", 0),
        } for r, st in payload["roadStatus"].items()},
        "listingCount": len(candidates),
        "listings": candidates,
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
