import concurrent.futures
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

DATA_PATH = Path("docs/data/listings.json")
CACHE_PATH = Path("docs/data/sinyi-first-display-cache.json")
API_URL = "https://sinyiwebapi.sinyi.com.tw/getObjectContent.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Content-Type": "application/json",
    "Referer": "https://www.sinyi.com.tw/",
    "Origin": "https://www.sinyi.com.tw",
}


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def parse_first_display(value):
    if not value:
        return None
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Taipei"))
        return int(dt.timestamp())
    except Exception:
        return None


def iso_from_timestamp(ts):
    try:
        return datetime.fromtimestamp(int(ts), ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")
    except Exception:
        return None


def extract(payload, house_id):
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, dict):
        return None
    if str(content.get("houseNo") or "").upper() != str(house_id).upper():
        return None
    raw = content.get("firstDisplay")
    ts = parse_first_display(raw)
    if not ts:
        return None
    return {"firstDisplay": raw, "timestamp": ts}


def build_payload(house_id):
    return {
        "machineNo": "",
        "ipAddress": "",
        "osType": 5,
        "model": "web",
        "deviceVersion": "Linux",
        "appVersion": "151.0.0.0",
        "deviceType": 3,
        "apType": 3,
        "browser": 1,
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
        "houseNo": str(house_id),
        "agentId": "",
        "memberPhone": "",
        "showOff": 0,
    }


def fetch_one(house_id):
    session = requests.Session()
    session.headers.update(HEADERS)
    last_error = None
    for attempt in range(1, 4):
        try:
            r = session.post(API_URL, json=build_payload(house_id), timeout=15)
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}"
                continue
            try:
                payload = r.json()
            except Exception:
                last_error = "non-json"
                continue
            found = extract(payload, house_id)
            if found:
                return house_id, found, None
            message = payload.get("message") if isinstance(payload, dict) else None
            last_error = f"house/firstDisplay not found{': ' + str(message) if message else ''}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return house_id, None, last_error


def main():
    state = load_json(DATA_PATH, {"listings": []})
    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}

    sinyi = [x for x in state.get("listings", []) if x.get("source") == "信義房屋" and x.get("houseId")]
    house_ids = sorted({str(x.get("houseId")) for x in sinyi})
    missing = [hid for hid in house_ids if not (cache.get(hid) or {}).get("timestamp")]

    errors = []
    fetched = 0
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            for hid, value, error in pool.map(fetch_one, missing):
                if value:
                    cache[hid] = value
                    fetched += 1
                elif error:
                    errors.append(f"{hid}: {error}")

    applied = 0
    for item in sinyi:
        hid = str(item.get("houseId"))
        hit = cache.get(hid) or {}
        ts = hit.get("timestamp")
        if ts:
            item["sourcePublishedAt"] = ts
            item["sourcePublishedAtType"] = "publishTime"
            item["sourcePublishedAtField"] = "firstDisplay"
            item["postTime"] = ts
            item["sinyiFirstDisplay"] = hit.get("firstDisplay")
            item["newAt"] = iso_from_timestamp(ts)
            applied += 1

    state.setdefault("timeNormalization", {})
    state["timeNormalization"]["sinyiFirstDisplayCached"] = applied
    state["timeNormalization"]["sinyiFirstDisplayFetchedThisRun"] = fetched
    state["timeNormalization"]["sinyiFirstDisplayMissing"] = max(0, len(house_ids) - applied)
    state["timeNormalization"]["sinyiFirstDisplayErrors"] = errors[-20:]

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sinyi firstDisplay: total={len(house_ids)}, cached/applied={applied}, fetched={fetched}, missing={len(house_ids)-applied}")
    for line in errors[-10:]:
        print(" -", line)


if __name__ == "__main__":
    main()
