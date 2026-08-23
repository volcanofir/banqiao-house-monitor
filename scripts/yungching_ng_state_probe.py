"""Inspect Yongching Angular SSR TransferState payloads without persisting raw HTML.

The probe records structural metadata and public listing fields only. It is diagnostic
and does not alter scheme A canonical output.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as base


OUT = Path("docs/preview/yungching-ng-state-probe.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
ROAD = "板橋區中山路二段"


def pg_url(url: str, page: int) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "pg"]
    q.append(("pg", str(page)))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def snapshot_ids():
    try:
        s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return set(), None
    ids = {str(x.get("id")) for x in (s.get("listings") or []) if x.get("id")}
    detail = None
    for x in s.get("listings") or []:
        if x.get("road") == ROAD and x.get("id"):
            detail = str(x["id"])
            break
    return ids, detail


def structure(x, depth=0):
    if depth >= 5:
        return type(x).__name__
    if isinstance(x, dict):
        out = {"type": "object", "keys": sorted(map(str, x.keys()))[:160]}
        if depth < 3:
            children = {}
            for k, v in x.items():
                if isinstance(v, (dict, list)):
                    children[str(k)] = structure(v, depth + 1)
                    if len(children) >= 30:
                        break
            if children:
                out["children"] = children
        return out
    if isinstance(x, list):
        out = {"type": "array", "length": len(x)}
        if x:
            out["first"] = structure(x[0], depth + 1)
        return out
    return {"type": type(x).__name__}


def project_item(item: dict) -> dict:
    keep = {}
    wanted = (
        "id", "pin", "title", "name", "address", "road", "price", "area", "floor",
        "case", "room", "age", "type", "url", "link", "building", "square", "total",
    )
    for k, v in item.items():
        lk = str(k).lower()
        if any(w in lk for w in wanted) and (isinstance(v, (str, int, float, bool)) or v is None):
            s = str(v)
            if len(s) <= 220:
                keep[str(k)] = v
        if len(keep) >= 50:
            break
    return keep


def candidate_arrays(root):
    found = []

    def walk(x, path="", depth=0):
        if depth > 8 or len(found) >= 80:
            return
        if isinstance(x, list):
            if x and isinstance(x[0], dict):
                keys = set(map(str.lower, x[0].keys()))
                score = sum(any(tok in k for k in keys) for tok in (
                    "id", "pin", "price", "area", "floor", "title", "name", "address"
                ))
                if score >= 2 or len(x) >= 10:
                    found.append({
                        "path": path or "$",
                        "length": len(x),
                        "firstItemKeys": sorted(map(str, x[0].keys()))[:140],
                        "firstItemPublicFields": project_item(x[0]),
                        "secondItemPublicFields": project_item(x[1]) if len(x) > 1 and isinstance(x[1], dict) else None,
                    })
            for i, v in enumerate(x[:8]):
                walk(v, f"{path}[{i}]", depth + 1)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{path}.{k}" if path else str(k), depth + 1)

    walk(root)
    return found


def relevant_scalars(root, known_ids):
    rows = []
    matched_known_ids = set()

    def walk(x, path="", depth=0):
        if depth > 9 or len(rows) >= 300:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}" if path else str(k)
                lk = str(k).lower()
                if isinstance(v, (str, int, float, bool)) or v is None:
                    sv = str(v)
                    if sv in known_ids:
                        matched_known_ids.add(sv)
                    if any(tok in lk for tok in (
                        "id", "pin", "floor", "price", "area", "count", "total", "page",
                        "case", "title", "name", "address", "room", "age", "url", "link"
                    )) and len(sv) <= 220:
                        rows.append({"path": p, "value": v})
                walk(v, p, depth + 1)
        elif isinstance(x, list):
            for i, v in enumerate(x[:12]):
                walk(v, f"{path}[{i}]", depth + 1)

    walk(root)
    return rows, sorted(matched_known_ids)


def extract_transfer(page, known_ids):
    loc = page.locator("script#ng-state")
    if not loc.count():
        return {"error": "script#ng-state not found"}
    txt = loc.first.text_content() or ""
    try:
        state = json.loads(txt)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "chars": len(txt)}
    transfers = []
    for key, value in state.items():
        if not str(key).startswith("transfer-buy:/api/v2/"):
            continue
        scalars, known = relevant_scalars(value, known_ids)
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        transfers.append({
            "key": str(key),
            "payloadBytesUtf8": len(raw.encode("utf-8")),
            "structure": structure(value),
            "candidateArrays": candidate_arrays(value),
            "relevantScalars": scalars,
            "matchedCanonicalHouseIds": known,
            "matchedCanonicalHouseIdCount": len(known),
            "ycCaseIds": sorted(set(re.findall(r"\bYC\d{5,12}\b", raw, flags=re.I)))[:80],
            "floorTokens": sorted(set(re.findall(r"\d{1,2}(?:[~～-]\d{1,2})?/\d{1,2}樓", raw)))[:100],
        })
    return {
        "ngStateChars": len(txt),
        "topLevelKeys": sorted(map(str, state.keys()))[:120],
        "transferCount": len(transfers),
        "transfers": transfers,
    }


def main():
    known_ids, detail_id = snapshot_ids()
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "road": ROAD,
        "pages": {},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        u1 = base.road_url(ROAD)
        r1 = page.goto(u1, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        out["pages"]["searchPage1"] = {
            "http": r1.status if r1 else None,
            "transferState": extract_transfer(page, known_ids),
        }

        r2 = page.goto(pg_url(u1, 2), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        out["pages"]["searchPage2"] = {
            "http": r2.status if r2 else None,
            "transferState": extract_transfer(page, known_ids),
        }

        if detail_id:
            rd = page.goto(f"{base.BASE}/house/{detail_id}", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            out["pages"]["detail"] = {
                "http": rd.status if rd else None,
                "expectedHouseId": detail_id,
                "transferState": extract_transfer(page, known_ids),
            }
        else:
            out["pages"]["detail"] = {"error": "no detail id from verified snapshot"}

        context.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        name: {
            "http": data.get("http"),
            "transferCount": ((data.get("transferState") or {}).get("transferCount")),
            "matchedCanonical": [
                t.get("matchedCanonicalHouseIdCount")
                for t in ((data.get("transferState") or {}).get("transfers") or [])
            ],
        }
        for name, data in out["pages"].items()
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
