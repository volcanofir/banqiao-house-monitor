"""Direct Sinyi R420 API pagination test with a consistent sort on every page.

Independent diagnostic only. It does not touch monitor data or website output.
"""

import json
import math
from collections import Counter
from pathlib import Path

import requests

API = "https://sinyiwebapi.sinyi.com.tw/filterObject.php"
OUT = Path("/tmp/sinyi-r420-api.json")


def headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.sinyi.com.tw",
        "Referer": "https://www.sinyi.com.tw/",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    }


def payload(page, sort):
    return {
        "machineNo": "",
        "ipAddress": "",
        "osType": 2,
        "model": "web",
        "deviceVersion": "iOS 18.0",
        "appVersion": "604.1",
        "deviceType": 1,
        "apType": 2,
        "browser": 4,
        "memberId": "",
        "domain": "www.sinyi.com.tw",
        "utmSource": "",
        "utmMedium": "",
        "utmCampaign": "",
        "utmCode": "",
        "requestor": 1,
        "utmContent": "",
        "utmTerm": "",
        "sinyiGroup": 1,
        "filter": {
            "exludeSameTrade": False,
            "objectStatus": 0,
            "retType": 6,
            "retRange": ["R420"],
            "mapType": 1,
            "objectType": [],
            "sortByStoreno": "R420",
        },
        "page": page,
        "pageCnt": 10,
        "sort": str(sort),
        "isReturnTotal": True,
    }


def run_sort(sort):
    rows = []
    pages = []
    total = None

    for page in range(1, 20):
        r = requests.post(API, headers=headers(), json=payload(page, sort), timeout=30)
        r.raise_for_status()
        data = r.json()
        content = data.get("content") or {}
        objs = content.get("object") or []
        if total is None:
            total = int(content.get("totalCnt") or 0)
        ids = [str(x.get("houseNo") or "").strip() for x in objs if x.get("houseNo")]
        pages.append({
            "page": page,
            "count": len(objs),
            "houseNos": ids,
            "totalCnt": content.get("totalCnt"),
        })
        rows.extend(objs)
        print(f"R420 API sort={sort} page={page} totalCnt={content.get('totalCnt')} count={len(objs)} ids={','.join(ids)}")
        if not objs:
            break
        if total and page >= math.ceil(total / 10):
            break

    ids = [str(x.get("houseNo") or "").strip() for x in rows if x.get("houseNo")]
    counts = Counter(ids)
    dups = {k: v for k, v in counts.items() if v > 1}
    result = {
        "sort": str(sort),
        "totalCnt": total,
        "rowCount": len(rows),
        "uniqueHouseNoCount": len(counts),
        "duplicateHouseNos": dups,
        "pages": pages,
        "listings": rows,
    }
    print(
        f"R420 API RESULT sort={sort} totalCnt={total} rowCount={len(rows)} "
        f"uniqueHouseNoCount={len(counts)} duplicates={json.dumps(dups, ensure_ascii=False)}"
    )
    return result


def main():
    results = {str(sort): run_sort(sort) for sort in (0, 2)}
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("R420 API OUTPUT=", OUT)


if __name__ == "__main__":
    main()
