"""Deep PREVIEW-only probe for where Yongching listing/detail data actually lives.

This probe stores only public/sanitized structural facts: counts, public house IDs,
marker names and script metadata. It never persists cookies, headers, request bodies,
or full HTML.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as base


OUT = Path("docs/preview/yungching-html-transport-probe.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
ROAD = "板橋區中山路二段"


def pg_url(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "pg"]
    query.append(("pg", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def detail_from_snapshot():
    try:
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None
    for row in snap.get("listings") or []:
        if row.get("road") == ROAD and row.get("id"):
            return f"{base.BASE}/house/{row['id']}", str(row["id"])
    return None


def text_metrics(text: str) -> dict:
    text = text or ""
    house_ids = sorted(set(re.findall(r"/house/(\d{5,9})", text)))
    yc_ids = sorted(set(re.findall(r"\bYC\d{5,12}\b", text, flags=re.I)))
    floors = sorted(set(
        re.sub(r"\s+", "", x).replace("～", "~")
        for x in re.findall(r"\d{1,2}(?:\s*[~～-]\s*\d{1,2})?/\d{1,2}樓", text)
    ))
    markers = {}
    for marker in [
        "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "INITIAL_STATE",
        "application/ld+json", "application/json", "houseId", "houseID",
        "house_id", "caseId", "item_pin", "item_floor", "listing",
        "searchResult", "propertyList", "price", "floor", "建坪", "樓",
    ]:
        markers[marker] = text.count(marker)
    return {
        "bytesUtf8": len(text.encode("utf-8", errors="ignore")),
        "houseIdCount": len(house_ids),
        "houseIds": house_ids[:120],
        "ycCaseIdCount": len(yc_ids),
        "ycCaseIds": yc_ids[:40],
        "floorTokenCount": len(floors),
        "floorTokens": floors[:60],
        "markers": markers,
    }


def script_metrics(page) -> dict:
    rows = page.locator("script").evaluate_all("""els => els.map((e, i) => ({
      i,
      type: e.getAttribute('type') || '',
      id: e.id || '',
      src: e.getAttribute('src') || '',
      chars: (e.textContent || '').length,
      text: (e.textContent || '')
    }))""")
    json_scripts = []
    inline_house_scripts = 0
    inline_state_scripts = 0
    for row in rows:
        txt = str(row.pop("text", "") or "")
        if re.search(r"/house/\d{5,9}|houseId|house_id|item_pin", txt, re.I):
            inline_house_scripts += 1
        if re.search(r"__NEXT_DATA__|__NUXT__|INITIAL_STATE|searchResult|propertyList", txt, re.I):
            inline_state_scripts += 1
        typ = str(row.get("type") or "").lower()
        if "json" in typ:
            meta = dict(row)
            try:
                obj = json.loads(txt)
                if isinstance(obj, dict):
                    meta["jsonTopLevelKeys"] = sorted(map(str, obj.keys()))[:80]
                    meta["jsonShape"] = "object"
                elif isinstance(obj, list):
                    meta["jsonShape"] = "array"
                    meta["jsonLength"] = len(obj)
                else:
                    meta["jsonShape"] = type(obj).__name__
            except Exception as exc:
                meta["jsonParseError"] = type(exc).__name__
            json_scripts.append(meta)
    srcs = []
    for row in rows:
        src = row.get("src")
        if not src:
            continue
        parts = urlsplit(src if "://" in src else base.BASE + (src if src.startswith("/") else "/" + src))
        srcs.append({"origin": f"{parts.scheme}://{parts.netloc}", "path": parts.path})
    unique_srcs = []
    seen = set()
    for x in srcs:
        key = (x["origin"], x["path"])
        if key not in seen:
            seen.add(key)
            unique_srcs.append(x)
    return {
        "scriptCount": len(rows),
        "externalScriptCount": len(srcs),
        "inlineScriptCount": sum(1 for x in rows if not x.get("src")),
        "inlineScriptsContainingHouseDataMarkers": inline_house_scripts,
        "inlineScriptsContainingStateMarkers": inline_state_scripts,
        "jsonScriptCount": len(json_scripts),
        "jsonScripts": json_scripts[:30],
        "externalScripts": unique_srcs[:120],
    }


def dom_attribute_metrics(page) -> dict:
    data = page.evaluate("""() => {
      const attrs = ['href','data-url','data-href','data-id','data-house-id','data-houseid','onclick'];
      const hits = [];
      for (const el of document.querySelectorAll('*')) {
        for (const a of attrs) {
          const v = el.getAttribute && el.getAttribute(a);
          if (!v) continue;
          if (/\/house\/\d{5,9}/i.test(v) || /(?:house|item|case)[_-]?id/i.test(a)) {
            hits.push({tag: el.tagName, attr:a, value:String(v).slice(0,240)});
          }
        }
      }
      return hits.slice(0, 200);
    }""")
    anchors = page.locator('a[href*="/house/"]')
    anchor_hrefs = []
    for i in range(min(anchors.count(), 120)):
        href = anchors.nth(i).get_attribute("href")
        if href:
            anchor_hrefs.append(href)
    anchor_ids = sorted(set(sum((re.findall(r"/house/(\d{5,9})", h) for h in anchor_hrefs), [])))
    attr_ids = sorted(set(sum((re.findall(r"/house/(\d{5,9})", str(x.get("value") or "")) for x in data), [])))
    return {
        "houseAnchorCount": anchors.count(),
        "houseAnchorIds": anchor_ids[:120],
        "attributeHouseHitCount": len(data),
        "attributeHouseIds": attr_ids[:120],
        "attributeSamples": data[:30],
    }


def window_metrics(page) -> dict:
    keys = page.evaluate("""() => Object.keys(window).filter(k =>
      /(next|nuxt|initial|state|house|listing|property|search|pin|redux|apollo)/i.test(k)
    ).sort().slice(0, 150)""")
    return {"interestingWindowGlobals": keys}


def inspect_page(page, response, label: str) -> dict:
    try:
        server_text = response.text() if response else ""
    except Exception as exc:
        server_text = ""
        server_error = f"{type(exc).__name__}: {exc}"
    else:
        server_error = None
    rendered = page.content()
    result = {
        "label": label,
        "http": response.status if response else None,
        "title": page.title()[:180],
        "urlPath": urlsplit(page.url).path,
        "serverDocument": text_metrics(server_text),
        "renderedDocument": text_metrics(rendered),
        "scripts": script_metrics(page),
        "domAttributes": dom_attribute_metrics(page),
        "window": window_metrics(page),
    }
    if server_error:
        result["serverDocumentReadError"] = server_error
    server_ids = set(result["serverDocument"]["houseIds"])
    rendered_ids = set(result["renderedDocument"]["houseIds"])
    result["houseIdTransportInference"] = {
        "serverContainsHouseIds": bool(server_ids),
        "renderedContainsHouseIds": bool(rendered_ids),
        "serverHouseIdCount": len(server_ids),
        "renderedHouseIdCount": len(rendered_ids),
        "renderedOnlyIds": sorted(rendered_ids - server_ids)[:120],
        "serverAndRenderedSameIdSet": server_ids == rendered_ids,
    }
    return result


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "road": ROAD,
        "privacy": "No cookies, headers, request bodies or full HTML are persisted.",
        "pages": {},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        u1 = base.road_url(ROAD)
        r1 = page.goto(u1, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)
        out["pages"]["searchPage1"] = inspect_page(page, r1, "searchPage1")

        u2 = pg_url(u1, 2)
        r2 = page.goto(u2, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)
        out["pages"]["searchPage2"] = inspect_page(page, r2, "searchPage2")
        active = page.locator(".paginationPageListItem.actived, .paginationPageListItem.active")
        out["pages"]["searchPage2"]["activePagerText"] = active.first.inner_text(timeout=2000).strip() if active.count() else None

        detail = detail_from_snapshot()
        if detail:
            detail_url, detail_id = detail
            rd = page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4500)
            out["pages"]["detail"] = inspect_page(page, rd, "detail")
            out["pages"]["detail"]["expectedHouseId"] = detail_id
        else:
            out["pages"]["detail"] = {"error": "no verified detail from snapshot"}

        context.close()
        browser.close()

    p1 = out["pages"].get("searchPage1") or {}
    p2 = out["pages"].get("searchPage2") or {}
    d = out["pages"].get("detail") or {}
    out["conclusionHints"] = {
        "searchPage1HouseIdsAlreadyInServerHtml": bool(((p1.get("serverDocument") or {}).get("houseIdCount") or 0)),
        "searchPage2HouseIdsAlreadyInServerHtml": bool(((p2.get("serverDocument") or {}).get("houseIdCount") or 0)),
        "detailHouseIdAlreadyInServerHtml": bool(((d.get("serverDocument") or {}).get("houseIdCount") or 0)),
        "searchHasJsonBootstrapScript": any(((p1.get("scripts") or {}).get("jsonScriptCount", 0), (p2.get("scripts") or {}).get("jsonScriptCount", 0))),
        "detailHasJsonBootstrapScript": bool((d.get("scripts") or {}).get("jsonScriptCount", 0)),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["conclusionHints"], ensure_ascii=False))


if __name__ == "__main__":
    main()
