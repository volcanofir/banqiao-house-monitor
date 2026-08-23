"""Probe official Yongching APIs exposed by Angular SSR TransferState.

This is diagnostic-only. It does not change scheme A canonical output. Only public
response structure and a small set of public listing identifiers/fields are saved.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as base


OUT = Path("docs/preview/yungching-internal-api-probe.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
TRANSPORT = Path("docs/preview/yungching-html-transport-probe.json")
ROAD = "板橋區中山路二段"
KEYWORD = "中山路二段"
AREA = "新北市-板橋區"


def api_list_url(page: int) -> str:
    q = urlencode({
        "area": AREA,
        "pinType": 0,
        "isAddRoom": "true",
        "keyword": KEYWORD,
        "filter": 0,
        "od": 80,
        "pg": page,
        "ps": 30,
    })
    return f"{base.BASE}/api/v2/list?{q}"


def detail_id_from_snapshot() -> str | None:
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None
    for row in data.get("listings") or []:
        if row.get("road") == ROAD and row.get("id"):
            return str(row["id"])
    return None


def structure(obj, depth=0):
    if depth >= 4:
        return type(obj).__name__
    if isinstance(obj, dict):
        keys = sorted(map(str, obj.keys()))
        out = {"type": "object", "keys": keys[:120]}
        # Include compact child shapes only for likely data containers.
        children = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if depth < 2 and (isinstance(v, (dict, list))) and any(t in lk for t in (
                "data", "list", "item", "house", "result", "page", "info", "content"
            )):
                children[str(k)] = structure(v, depth + 1)
        if children:
            out["children"] = children
        return out
    if isinstance(obj, list):
        out = {"type": "array", "length": len(obj)}
        if obj:
            out["first"] = structure(obj[0], depth + 1)
        return out
    return {"type": type(obj).__name__}


def public_signals(obj) -> dict:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    house_url_ids = sorted(set(re.findall(r"/house/(\d{5,9})", raw)))
    yc_ids = sorted(set(re.findall(r"\bYC\d{5,12}\b", raw, flags=re.I)))
    floors = sorted(set(
        re.sub(r"\s+", "", x).replace("～", "~")
        for x in re.findall(r"\d{1,2}(?:\s*[~～-]\s*\d{1,2})?/\d{1,2}樓", raw)
    ))
    field_samples = []

    def walk(x, path="", depth=0):
        if depth > 7 or len(field_samples) >= 180:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}" if path else str(k)
                lk = str(k).lower()
                if any(t in lk for t in ("id", "pin", "floor", "price", "area", "count", "total", "page", "case")):
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        s = str(v)
                        if len(s) <= 160:
                            field_samples.append({"path": p, "value": v})
                walk(v, p, depth + 1)
        elif isinstance(x, list):
            for i, v in enumerate(x[:5]):
                walk(v, f"{path}[{i}]", depth + 1)

    walk(obj)
    # Generic 5-9 digit values can expose listing IDs even when URLs are absent.
    candidate_numeric_ids = sorted(set(re.findall(r'(?<!\d)(\d{5,9})(?!\d)', raw)))
    return {
        "jsonBytesUtf8": len(raw.encode("utf-8")),
        "houseUrlIds": house_url_ids[:200],
        "houseUrlIdCount": len(house_url_ids),
        "ycCaseIds": yc_ids[:80],
        "ycCaseIdCount": len(yc_ids),
        "floorTokens": floors[:100],
        "floorTokenCount": len(floors),
        "candidateNumericIds": candidate_numeric_ids[:250],
        "fieldSamples": field_samples,
    }


def request_json(context, url: str) -> dict:
    resp = context.request.get(url, headers={"Accept": "application/json"}, timeout=45000)
    out = {
        "status": resp.status,
        "ok": resp.ok,
        "contentType": resp.headers.get("content-type"),
        "urlPath": re.sub(r"\?.*$", "", url.replace(base.BASE, "")),
    }
    text = resp.text()
    out["responseBytesUtf8"] = len(text.encode("utf-8", errors="ignore"))
    try:
        data = json.loads(text)
    except Exception as exc:
        out["jsonError"] = f"{type(exc).__name__}: {exc}"
        out["textPrefix"] = text[:200]
        return out
    out["structure"] = structure(data)
    out["signals"] = public_signals(data)
    return out


def html_house_ids(name: str) -> list[str]:
    try:
        data = json.loads(TRANSPORT.read_text(encoding="utf-8"))
        return (((data.get("pages") or {}).get(name) or {}).get("serverDocument") or {}).get("houseIds") or []
    except Exception:
        return []


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    detail_id = detail_id_from_snapshot()
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "sourceDiscovery": "Angular SSR ng-state TransferState keys",
        "road": ROAD,
        "requests": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        # Seed normal site cookies/session first; APIs are still requested directly.
        page = context.new_page()
        seed = page.goto(base.road_url(ROAD), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        out["seedPageStatus"] = seed.status if seed else None

        out["requests"]["listPage1"] = request_json(context, api_list_url(1))
        out["requests"]["listPage2"] = request_json(context, api_list_url(2))
        if detail_id:
            out["requests"]["detail"] = request_json(context, f"{base.BASE}/api/v2/house?id={detail_id}")
            out["requests"]["detail"]["expectedHouseId"] = detail_id
        else:
            out["requests"]["detail"] = {"error": "no verified detail id"}

        context.close()
        browser.close()

    p1_html = set(html_house_ids("searchPage1"))
    p2_html = set(html_house_ids("searchPage2"))
    p1_api = set(((out["requests"]["listPage1"].get("signals") or {}).get("houseUrlIds") or []))
    p2_api = set(((out["requests"]["listPage2"].get("signals") or {}).get("houseUrlIds") or []))
    out["comparisons"] = {
        "page1": {
            "apiHouseUrlIdCount": len(p1_api),
            "serverHtmlHouseIdCount": len(p1_html),
            "apiOnly": sorted(p1_api - p1_html),
            "htmlOnly": sorted(p1_html - p1_api),
            "intersectionCount": len(p1_api & p1_html),
        },
        "page2": {
            "apiHouseUrlIdCount": len(p2_api),
            "serverHtmlHouseIdCount": len(p2_html),
            "apiOnly": sorted(p2_api - p2_html),
            "htmlOnly": sorted(p2_html - p2_api),
            "intersectionCount": len(p2_api & p2_html),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "list1": {k: out["requests"]["listPage1"].get(k) for k in ("status", "ok", "contentType")},
        "list2": {k: out["requests"]["listPage2"].get(k) for k in ("status", "ok", "contentType")},
        "detail": {k: out["requests"]["detail"].get(k) for k in ("status", "ok", "contentType")},
        "comparisons": out["comparisons"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
