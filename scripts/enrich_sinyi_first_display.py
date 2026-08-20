import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

DATA_PATH = Path("docs/data/listings.json")
CACHE_PATH = Path("docs/data/sinyi-first-display-cache.json")
API_NAME = "getObjectContent.php"
MAX_CONCURRENCY = 8


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def parse_first_display(value):
    if not value:
        return None
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Asia/Taipei")
        )
        return int(dt.timestamp())
    except Exception:
        return None


def iso_from_timestamp(ts):
    try:
        return datetime.fromtimestamp(int(ts), ZoneInfo("Asia/Taipei")).isoformat(
            timespec="seconds"
        )
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


async def fetch_one(browser, semaphore, house_id):
    async with semaphore:
        context = None
        try:
            context = await browser.new_context(
                locale="zh-TW",
                timezone_id="Asia/Taipei",
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            page = await context.new_page()
            result_future = asyncio.get_running_loop().create_future()

            async def inspect_response(response):
                if API_NAME not in response.url or response.status != 200:
                    return
                if result_future.done():
                    return
                try:
                    payload = await response.json()
                    found = extract(payload, house_id)
                    if found and not result_future.done():
                        result_future.set_result(found)
                except Exception:
                    pass

            def on_response(response):
                asyncio.create_task(inspect_response(response))

            page.on("response", on_response)
            url = f"https://www.sinyi.com.tw/buy/house/{house_id}?breadcrumb=list"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                # shield prevents wait_for() timeout from cancelling the future itself.
                found = await asyncio.wait_for(asyncio.shield(result_future), timeout=12)
                return house_id, found, None
            except asyncio.TimeoutError:
                await page.wait_for_timeout(3000)
                if result_future.done() and not result_future.cancelled():
                    try:
                        return house_id, result_future.result(), None
                    except Exception:
                        pass
                return house_id, None, "firstDisplay API response not captured"
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return house_id, None, f"{type(exc).__name__}: {exc}"
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass


async def fetch_missing(missing):
    if not missing:
        return []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
        try:
            raw_results = await asyncio.gather(
                *(fetch_one(browser, semaphore, hid) for hid in missing),
                return_exceptions=True,
            )
            results = []
            for hid, result in zip(missing, raw_results):
                if isinstance(result, BaseException):
                    results.append((hid, None, f"{type(result).__name__}: {result}"))
                else:
                    results.append(result)
            return results
        finally:
            await browser.close()


def main():
    state = load_json(DATA_PATH, {"listings": []})
    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}

    sinyi = [
        x
        for x in state.get("listings", [])
        if x.get("source") == "信義房屋" and x.get("houseId")
    ]
    house_ids = sorted({str(x.get("houseId")) for x in sinyi})
    missing = [
        hid for hid in house_ids if not (cache.get(hid) or {}).get("timestamp")
    ]

    errors = []
    fetched = 0
    if missing:
        try:
            results = asyncio.run(fetch_missing(missing))
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            results = []
            errors.append(f"batch: {type(exc).__name__}: {exc}")

        for hid, value, error in results:
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
    state["timeNormalization"]["sinyiFirstDisplayMissing"] = max(
        0, len(house_ids) - applied
    )
    state["timeNormalization"]["sinyiFirstDisplayErrors"] = errors[-20:]
    state["timeNormalization"]["sinyiFirstDisplayMode"] = "playwright_network_capture_safe"

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Sinyi firstDisplay: total={len(house_ids)}, cached/applied={applied}, "
        f"fetched={fetched}, missing={len(house_ids)-applied}"
    )
    for line in errors[-10:]:
        print(" -", line)


if __name__ == "__main__":
    main()
