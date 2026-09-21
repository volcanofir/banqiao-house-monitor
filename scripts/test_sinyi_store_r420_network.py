"""Rendered-browser network diagnostic for Sinyi R420 store listings.

Independent test only. Opens the public R420 pages in real Chrome, captures XHR/fetch
JSON, and finds any arrays containing Sinyi houseNo rows so we can compare them with
the SSR __NEXT_DATA__ list.
"""

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

STORE_CODE = "R420"
STORE_NAME = "板橋中山店"
BASE = f"https://www.sinyi.com.tw/buy/list/{STORE_CODE}-{quote(STORE_NAME)}-store"
OUT = Path("/tmp/sinyi-r420-network.json")


def walk(obj, path="$"):
    found = []
    if isinstance(obj, list):
        house_rows = [x for x in obj if isinstance(x, dict) and x.get("houseNo")]
        if house_rows:
            found.append({
                "path": path,
                "count": len(obj),
                "houseCount": len(house_rows),
                "houseNos": [str(x.get("houseNo")) for x in house_rows],
                "rows": house_rows,
            })
        for i, value in enumerate(obj[:100]):
            found.extend(walk(value, f"{path}[{i}]"))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(walk(value, f"{path}.{key}"))
    return found


def main():
    captured = []
    console = []
    first_filter_body = {"value": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            is_mobile=True,
            has_touch=True,
        )
        page = ctx.new_page()
        page.on("console", lambda msg: console.append({"type": msg.type, "text": msg.text}))

        def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            item = {
                "url": resp.url,
                "status": resp.status,
                "resourceType": req.resource_type,
                "method": req.method,
            }
            if "filterObject.php" in resp.url:
                try:
                    item["postData"] = req.post_data
                    if first_filter_body["value"] is None and req.post_data:
                        first_filter_body["value"] = json.loads(req.post_data)
                except Exception as exc:
                    item["postDataError"] = f"{type(exc).__name__}: {exc}"
            try:
                headers = resp.headers
                item["contentType"] = headers.get("content-type")
                if "json" in (item["contentType"] or "").lower():
                    payload = resp.json()
                    matches = walk(payload)
                    item["jsonMatches"] = matches
                    if isinstance(payload, dict):
                        item["topKeys"] = sorted(payload.keys())
                        content = payload.get("content")
                        if isinstance(content, dict):
                            item["contentMeta"] = {
                                k: v for k, v in content.items()
                                if k not in ("object", "objects", "list", "data")
                                and isinstance(v, (str, int, float, bool, type(None)))
                            }
            except Exception as exc:
                item["parseError"] = f"{type(exc).__name__}: {exc}"
            captured.append(item)

        page.on("response", on_response)

        page_summaries = []
        for page_no in range(1, 9):
            url = BASE if page_no == 1 else f"{BASE}/publish-desc/{page_no}"
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            text = page.locator("body").inner_text(timeout=10000)
            cards = page.locator('a[href*="/buy/house/"]')
            hrefs = []
            for i in range(min(cards.count(), 200)):
                href = cards.nth(i).get_attribute("href")
                if href:
                    hrefs.append(href)
            page_summaries.append({
                "page": page_no,
                "url": url,
                "status": resp.status if resp else None,
                "title": page.title(),
                "bodyHas72": "72" in text,
                "houseLinkCount": len(hrefs),
                "uniqueHouseLinks": sorted(set(hrefs)),
            })
            print(f"R420 BROWSER page={page_no} status={resp.status if resp else None} houseLinks={len(set(hrefs))}")

        replay = {}
        seed = first_filter_body["value"]
        if seed:
            for sort in ("0", "2"):
                replay_rows = []
                replay_pages = []
                total = None
                for page_no in range(1, 9):
                    body = json.loads(json.dumps(seed))
                    body["page"] = page_no
                    body["pageCnt"] = 10
                    body["sort"] = sort
                    body["isReturnTotal"] = True
                    result = page.evaluate(
                        """async ({url, body}) => {
                          const r = await fetch(url, {
                            method: 'POST',
                            credentials: 'include',
                            headers: {'content-type':'application/json;charset=UTF-8'},
                            body: JSON.stringify(body)
                          });
                          return {status:r.status, text:await r.text()};
                        }""",
                        {"url": "https://sinyiwebapi.sinyi.com.tw/filterObject.php", "body": body},
                    )
                    parsed = {}
                    try:
                        parsed = json.loads(result.get("text") or "{}")
                    except Exception:
                        parsed = {}
                    content = parsed.get("content") or {}
                    objs = content.get("object") or []
                    ids = [str(x.get("houseNo")) for x in objs if isinstance(x, dict) and x.get("houseNo")]
                    if total is None:
                        total = content.get("totalCnt")
                    replay_pages.append({
                        "page": page_no,
                        "status": result.get("status"),
                        "totalCnt": content.get("totalCnt"),
                        "count": len(objs),
                        "houseNos": ids,
                    })
                    replay_rows.extend(objs)
                    print(f"R420 REPLAY sort={sort} page={page_no} status={result.get('status')} totalCnt={content.get('totalCnt')} count={len(objs)} ids={','.join(ids)}")
                ids = [str(x.get("houseNo")) for x in replay_rows if isinstance(x, dict) and x.get("houseNo")]
                seen = set()
                duplicates = []
                for hid in ids:
                    if hid in seen and hid not in duplicates:
                        duplicates.append(hid)
                    seen.add(hid)
                replay[sort] = {
                    "totalCnt": total,
                    "rowCount": len(replay_rows),
                    "uniqueHouseNoCount": len(seen),
                    "duplicateHouseNos": duplicates,
                    "pages": replay_pages,
                    "listings": replay_rows,
                }
                print(f"R420 REPLAY RESULT sort={sort} totalCnt={total} rowCount={len(replay_rows)} uniqueHouseNoCount={len(seen)} duplicates={','.join(duplicates) or '-'}")

        browser.close()

    relevant = []
    union = set()
    for item in captured:
        matches = item.get("jsonMatches") or []
        if matches:
            relevant.append(item)
            for m in matches:
                union.update(m.get("houseNos") or [])

    out = {
        "baseUrl": BASE,
        "pageSummaries": page_summaries,
        "capturedRequestCount": len(captured),
        "relevantJsonResponseCount": len(relevant),
        "networkHouseNoUniqueCount": len(union),
        "networkHouseNos": sorted(union),
        "consistentSortReplay": replay,
        "relevantResponses": relevant,
        "allNetworkResponses": captured,
        "console": console,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("R420 NETWORK capturedRequestCount=", len(captured))
    print("R420 NETWORK relevantJsonResponseCount=", len(relevant))
    print("R420 NETWORK uniqueHouseNos=", len(union))
    for item in relevant:
        print("R420 API=", item.get("method"), item.get("status"), item.get("url"))
        if item.get("url", "").endswith("filterObject.php"):
            print("  POSTDATA", item.get("postData"))
            print("  CONTENTMETA", json.dumps(item.get("contentMeta") or {}, ensure_ascii=False))
        for m in item.get("jsonMatches") or []:
            print("  MATCH", m.get("path"), "count=", m.get("count"), "houseCount=", m.get("houseCount"),
                  "ids=", ",".join(m.get("houseNos") or []))
    print("R420 NETWORK OUTPUT=", OUT)


if __name__ == "__main__":
    main()
