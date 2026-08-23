"""Probe Sinyi official __NEXT_DATA__ list payload for floor fields.

PREVIEW diagnostic only. Does not modify docs/data/listings.json.
This file is the explicit push trigger for the isolated floor probe workflow.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


DATA = Path("docs/data/listings.json")
OUT = Path("docs/preview/sinyi-floor-probe.json")
ROADS = [
    "板橋區中山路二段", "板橋區三民路二段", "板橋區光復街", "板橋區萬安街",
    "板橋區林森街", "板橋區三民路一段", "板橋區翠華街",
]
ALIASES = {
    "板橋區中山路二段": ["中山路二段", "中山路2段"],
    "板橋區三民路二段": ["三民路二段", "三民路2段"],
    "板橋區光復街": ["光復街"],
    "板橋區萬安街": ["萬安街"],
    "板橋區林森街": ["林森街"],
    "板橋區三民路一段": ["三民路一段", "三民路1段"],
    "板橋區翠華街": ["翠華街"],
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def active_ids():
    try:
        x = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {str(i.get("houseId")) for i in x.get("listings", []) if i.get("source") == "信義房屋" and i.get("active", True) and i.get("houseId")}


def floor_fields(item):
    out = {}
    for k, v in item.items():
        lk = str(k).lower()
        if any(t in lk for t in ("floor", "storey", "story")):
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[str(k)] = v
            elif isinstance(v, (list, dict)):
                out[str(k)] = v
    return out


def text_floor_candidates(item):
    raw = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    vals = sorted(set(re.findall(r"\d{1,2}\s*樓\s*/\s*\d{1,2}\s*樓|\d{1,2}\s*/\s*\d{1,2}\s*樓", raw)))
    return vals[:20]


def main():
    wanted = active_ids()
    rows = {}
    page_stats = []
    errors = []
    s = requests.Session()
    for road in ROADS:
        keyword = road.replace("板橋區", "")
        for page in range(1, 30):
            url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/{page}"
            try:
                r = s.get(url, headers=HEADERS, timeout=30)
            except Exception as exc:
                errors.append(f"{road} p{page}: {type(exc).__name__}: {exc}")
                break
            if r.status_code != 200:
                errors.append(f"{road} p{page}: HTTP {r.status_code}")
                break
            soup = BeautifulSoup(r.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            parsed = []
            if script and script.string:
                try:
                    payload = json.loads(script.string)
                    reducer = (((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
                    parsed = reducer.get("list") or []
                except Exception as exc:
                    errors.append(f"{road} p{page}: next-data {type(exc).__name__}")
            if not isinstance(parsed, list) or not parsed:
                page_stats.append({"road": road, "page": page, "count": 0})
                break
            page_stats.append({"road": road, "page": page, "count": len(parsed)})
            for item in parsed:
                hid = str(item.get("houseNo") or "").strip()
                addr = str(item.get("address") or "")
                if not hid or hid not in wanted or not any(a in addr for a in ALIASES[road]):
                    continue
                ff = floor_fields(item)
                rows[hid] = {
                    "houseId": hid,
                    "road": road,
                    "name": item.get("name"),
                    "address": addr,
                    "floorFields": ff,
                    "textFloorCandidates": text_floor_candidates(item),
                    "itemKeys": sorted(map(str, item.keys())),
                    "publicCrossCheck": {
                        "totalPrice": item.get("totalPrice"),
                        "areaBuilding": item.get("areaBuilding"),
                    },
                }

    known = {"5818CQ", "5368YG"}
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "activeSinyiIdCount": len(wanted),
        "matchedActiveIdCount": len(rows),
        "matchedWithFloorFieldCount": sum(1 for x in rows.values() if x.get("floorFields")),
        "matchedWithTextFloorCandidateCount": sum(1 for x in rows.values() if x.get("textFloorCandidates")),
        "knownAmbiguityCases": {k: rows.get(k) for k in sorted(known)},
        "floorFieldNames": sorted({k for x in rows.values() for k in (x.get("floorFields") or {})}),
        "rows": list(rows.values()),
        "pageStats": page_stats,
        "errors": errors[-30:],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("activeSinyiIdCount", "matchedActiveIdCount", "matchedWithFloorFieldCount", "matchedWithTextFloorCandidateCount", "floorFieldNames")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
