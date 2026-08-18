import json
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

import monitor_pages as core

DATA_PATH = Path("docs/data/listings.json")


def fetch_sinyi_publish_times():
    publish_times = {}
    logs = []

    for road in core.WATCH_ROADS:
        keyword = road.replace("板橋區", "")
        page = 1
        seen_ids = set()

        while True:
            url = (
                "https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/"
                f"{quote(keyword)}-keyword/publish-desc/{page}"
            )
            try:
                response = requests.get(
                    url,
                    headers=core.default_headers("https://www.sinyi.com.tw/"),
                    timeout=25,
                )
            except Exception as exc:
                logs.append(f"{road} 第 {page} 頁連線失敗：{exc}")
                break

            if response.status_code != 200:
                logs.append(f"{road} 第 {page} 頁 HTTP {response.status_code}")
                break

            soup = BeautifulSoup(response.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            parsed = []
            if script and script.string:
                try:
                    payload = json.loads(script.string)
                    reducer = (
                        (((payload.get("props") or {}).get("initialReduxState") or {})
                         .get("buyReducer") or {})
                    )
                    parsed = reducer.get("list") or []
                except Exception:
                    parsed = []

            if not isinstance(parsed, list) or not parsed:
                break

            page_ids = set()
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                house_id = core.normalize_text(item.get("houseNo"))
                if not house_id:
                    continue
                page_ids.add(house_id)
                if item.get("publishTime") not in (None, ""):
                    publish_times[house_id] = core.to_unix(item.get("publishTime"))

            if page_ids and page_ids.issubset(seen_ids):
                break
            seen_ids.update(page_ids)
            page += 1

    return publish_times, logs


def main():
    if not DATA_PATH.exists():
        print("No listings data found.")
        return

    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    listings = state.get("listings") or []

    sinyi_times, logs = fetch_sinyi_publish_times()
    count_591 = 0
    count_sinyi = 0
    missing_sinyi = 0

    for item in listings:
        source = item.get("source")
        if source == "591":
            # 591 API `posttime` is the original listing publish time.
            item["sourcePublishedAt"] = item.get("postTime")
            item["sourcePublishedAtType"] = "posttime" if item.get("postTime") else None
            count_591 += 1 if item.get("postTime") else 0

        elif source == "信義房屋":
            house_id = str(item.get("houseId") or "")
            publish_time = sinyi_times.get(house_id)
            # Only publishTime is allowed to represent a real source publish time.
            # Never substitute updateTime/createTime here.
            item["sourcePublishedAt"] = publish_time
            item["sourcePublishedAtType"] = "publishTime" if publish_time else None
            item["postTime"] = publish_time
            if publish_time:
                count_sinyi += 1
            else:
                missing_sinyi += 1

    state.setdefault("timeNormalization", {})
    state["timeNormalization"] = {
        "591RealPublishTimes": count_591,
        "sinyiRealPublishTimes": count_sinyi,
        "sinyiMissingPublishTimes": missing_sinyi,
        "logs": logs[-30:],
    }

    DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Source times normalized: 591={count_591}, "
        f"Sinyi publishTime={count_sinyi}, Sinyi missing={missing_sinyi}"
    )


if __name__ == "__main__":
    main()
