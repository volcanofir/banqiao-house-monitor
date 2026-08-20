import concurrent.futures
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROADS = {
    "板橋區中山路二段": "27507",
    "板橋區三民路二段": "27485",
    "板橋區光復街": "27550",
    "板橋區萬安街": "27630",
    "板橋區林森街": "27574",
    "板橋區三民路一段": "27484",
    "板橋區翠華街": "27644",
}

V1 = "https://bff-house.591.com.tw/v1/touch/sale/list"
V2 = "https://bff-house.591.com.tw/v2/php-api"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def request_json(url, referer):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
            "Referer": referer,
            "Origin": "https://m.591.com.tw",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def warmup(road, street_id):
    params = {
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": street_id,
        "keywords": road.replace("板橋區", ""),
    }
    url = "https://m.591.com.tw/v2/sale?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        resp.read(1024)
    return url


def extract_items(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        data = data.get("items") or data.get("list") or data.get("data") or []
    return data if isinstance(data, list) else []


def fetch_road(road, street_id):
    started = time.time()
    logs = []
    result = {
        "road": road,
        "streetid": street_id,
        "success": False,
        "count": 0,
        "pages": 0,
        "api": None,
        "logs": logs,
        "startedAt": now_iso(),
        "vpnConnected": os.environ.get("VPN_CONNECTED", "").lower() == "true",
        "vpnExitIp": os.environ.get("VPN_EXIT_IP") or None,
    }

    try:
        referer = warmup(road, street_id)
        logs.append("HTTP 暖機成功")
    except Exception as exc:
        referer = "https://m.591.com.tw/"
        logs.append(f"HTTP 暖機失敗：{exc}")

    seen = set()
    for page_no in range(1, 11):
        common = {
            "regionid": "3",
            "sectionidStr": "26",
            "o": "32",
            "streetid": street_id,
            "firstRow": str((page_no - 1) * 30),
            "newPage": str(page_no),
            "newPageSize": "30",
            "timestamp": str(int(time.time() * 1000)),
            "region_id": "3",
            "device": "touch",
        }
        candidates = [
            ("v1", V1 + "?" + urllib.parse.urlencode(common)),
            ("v2", V2 + "?" + urllib.parse.urlencode({**common, "module": "mobile", "action": "list", "type": "sale"})),
        ]

        payload = None
        chosen = None
        for label, url in candidates:
            try:
                status, data = request_json(url, referer)
                items = extract_items(data)
                logs.append(f"{label} 第 {page_no} 頁 HTTP {status} items={len(items)}")
                if status == 200 and isinstance(items, list):
                    payload = data
                    chosen = label
                    break
            except Exception as exc:
                logs.append(f"{label} 第 {page_no} 頁失敗：{type(exc).__name__}: {exc}")

        if payload is None:
            break

        result["api"] = chosen
        items = extract_items(payload)
        ids = []
        for item in items:
            if not isinstance(item, dict):
                continue
            post_id = str(item.get("post_id") or item.get("postId") or item.get("houseid") or item.get("houseId") or "")
            if post_id and post_id not in seen:
                seen.add(post_id)
                ids.append(post_id)
        result["count"] += len(ids)
        result["pages"] += 1

        if len(items) < 30 or not ids:
            break

    result["success"] = result["pages"] > 0
    result["finishedAt"] = now_iso()
    result["durationSeconds"] = round(time.time() - started, 2)
    return result


def main():
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = [ex.submit(fetch_road, road, sid) for road, sid in ROADS.items()]
        rows = [f.result() for f in futures]

    report = {
        "checkedAt": now_iso(),
        "mode": "surfshark_taiwan_wireguard_pure_http_seven_parallel",
        "vpnExpected": True,
        "vpnVerifiedForAllResults": len(rows) == 7 and all(r.get("vpnConnected") and r.get("vpnExitIp") for r in rows),
        "vpnExitIps": sorted({r.get("vpnExitIp") for r in rows if r.get("vpnExitIp")}),
        "successCount": sum(bool(r.get("success")) for r in rows),
        "totalRoads": 7,
        "receivedResults": len(rows),
        "allSucceeded": len(rows) == 7 and all(bool(r.get("success")) for r in rows),
        "wallSeconds": round(time.time() - started, 2),
        "results": rows,
        "productionDataModified": False,
    }

    out = Path("docs/data/591-http-fast-test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
