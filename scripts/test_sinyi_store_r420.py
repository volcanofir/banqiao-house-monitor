"""Independent diagnostic crawl for Sinyi R420 store listings.

This intentionally reuses the same public-page strategy as monitor_sinyi_parallel.py:
requests -> __NEXT_DATA__ -> props.initialReduxState.buyReducer.list.
It does not read or write canonical monitor data and does not publish to the website.
"""

import json
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

STORE_CODE = "R420"
STORE_NAME = "板橋中山店"
BASE = f"https://www.sinyi.com.tw/buy/list/{STORE_CODE}-{quote(STORE_NAME)}-store"
OUT = Path("/tmp/sinyi-r420-test.json")
MAX_PAGES = 20


def headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.sinyi.com.tw/",
    }


def parse(url):
    r = requests.get(url, headers=headers(), timeout=30)
    result = {
        "url": url,
        "status": r.status_code,
        "list": [],
        "reducerKeys": [],
        "routeQuery": {},
    }
    if r.status_code != 200:
        return result

    soup = BeautifulSoup(r.text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        result["error"] = "__NEXT_DATA__ missing"
        return result

    payload = json.loads(script.string)
    props = payload.get("props") or {}
    state = props.get("initialReduxState") or {}
    reducer = state.get("buyReducer") or {}
    rows = reducer.get("list") or []
    result["reducerKeys"] = sorted(reducer.keys())
    result["routeQuery"] = payload.get("query") or {}
    result["list"] = rows if isinstance(rows, list) else []
    for key in ("total", "totalCount", "count", "page", "pageIndex", "currentPage", "pageCount", "totalPage"):
        if key in reducer:
            result[key] = reducer.get(key)
    return result


def page_candidates(page):
    if page == 1:
        return [
            BASE,
            f"{BASE}/publish-desc/1",
            f"{BASE}/1",
            f"{BASE}?page=1",
        ]
    return [
        f"{BASE}/publish-desc/{page}",
        f"{BASE}/{page}",
        f"{BASE}?page={page}",
    ]


def slim(item):
    return {
        "houseNo": item.get("houseNo"),
        "name": item.get("name"),
        "address": item.get("address"),
        "totalPrice": item.get("totalPrice"),
        "areaBuilding": item.get("areaBuilding"),
        "room": item.get("room"),
        "hall": item.get("hall"),
        "bathroom": item.get("bathroom"),
        "floor": item.get("floor"),
        "floorText": item.get("floorText"),
        "age": item.get("age"),
        "houseType": item.get("houseType"),
        "publishTime": item.get("publishTime"),
        "updateTime": item.get("updateTime"),
        "createTime": item.get("createTime"),
        "url": (
            f"https://www.sinyi.com.tw/buy/house/{quote(str(item.get('houseNo')))}?breadcrumb=list"
            if item.get("houseNo") else None
        ),
    }


def main():
    seen = set()
    all_rows = []
    page_logs = []
    chosen_pattern = None

    for page in range(1, MAX_PAGES + 1):
        attempts = []
        chosen = None
        for url in page_candidates(page):
            try:
                parsed = parse(url)
            except Exception as exc:
                attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
                continue

            ids = [
                str(x.get("houseNo"))
                for x in parsed.get("list") or []
                if x.get("houseNo")
            ]
            new_ids = [x for x in ids if x not in seen]
            attempts.append({
                "url": url,
                "status": parsed.get("status"),
                "count": len(parsed.get("list") or []),
                "newCount": len(new_ids),
                "routeQuery": parsed.get("routeQuery"),
                "reducerKeys": parsed.get("reducerKeys"),
                **{k: parsed[k] for k in ("total","totalCount","count","page","pageIndex","currentPage","pageCount","totalPage") if k in parsed},
            })

            if parsed.get("status") == 200 and parsed.get("list") and new_ids:
                chosen = parsed
                chosen_pattern = url
                break

        if not chosen:
            page_logs.append({"page": page, "chosen": None, "attempts": attempts})
            print(f"R420 page {page}: no unseen rows; stop")
            break

        rows = chosen["list"]
        page_ids = [str(x.get("houseNo") or "").strip() for x in rows if x.get("houseNo")]
        repeated_ids = [hid for hid in page_ids if hid in seen]
        print(
            f"R420 page {page} meta routeQuery={json.dumps(chosen.get('routeQuery') or {}, ensure_ascii=False)} "
            f"reducerKeys={','.join(chosen.get('reducerKeys') or [])} repeated={','.join(repeated_ids) or '-'}"
        )
        added = 0
        for item in rows:
            hid = str(item.get("houseNo") or "").strip()
            if not hid or hid in seen:
                continue
            seen.add(hid)
            all_rows.append(item)
            added += 1

        page_logs.append({
            "page": page,
            "chosen": chosen["url"],
            "parsedCount": len(rows),
            "added": added,
            "attempts": attempts,
        })
        print(f"R420 page {page}: parsed={len(rows)} added={added} totalUnique={len(all_rows)} via {chosen['url']}")

        if added == 0:
            break

    out = {
        "storeCode": STORE_CODE,
        "storeName": STORE_NAME,
        "baseUrl": BASE,
        "uniqueCount": len(all_rows),
        "lastChosenUrl": chosen_pattern,
        "pages": page_logs,
        "listings": [slim(x) for x in all_rows],
        "rawListings": all_rows,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("R420 RESULT uniqueCount=", len(all_rows))
    print("R420 HOUSE IDS=", ",".join(str(x.get("houseNo")) for x in all_rows if x.get("houseNo")))
    if all_rows:
        print("R420 FIRST=", json.dumps(slim(all_rows[0]), ensure_ascii=False))
        print("R420 FIRST RAW KEYS=", ",".join(sorted(all_rows[0].keys())))
        print("R420 FIRST RAW=", json.dumps(all_rows[0], ensure_ascii=False))
        print("R420 LAST=", json.dumps(slim(all_rows[-1]), ensure_ascii=False))
    print("R420 OUTPUT=", OUT)


if __name__ == "__main__":
    main()
