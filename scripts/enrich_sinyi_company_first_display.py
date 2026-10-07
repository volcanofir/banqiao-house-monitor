"""Enrich 16-store Sinyi listings with the official original firstDisplay time.

Fast path:
1. Open ONE Sinyi detail page in Playwright.
2. Capture the live getObjectContent.php request headers/body (sid/sat/code included).
3. Reuse that request shape to fetch all remaining houseNo values directly via HTTP.

Fallback:
Only IDs that fail direct API retrieval use the older per-detail-page Playwright
network capture. Resolved firstDisplay values are persisted in the shared cache.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from playwright.async_api import async_playwright

from enrich_sinyi_first_display import (
    fetch_missing,
    load_json,
    parse_first_display,
)

DATA = Path("docs/company/sinyi-banqiao-stores.json")
CACHE = Path("docs/data/sinyi-first-display-cache.json")
API_URL = "https://sinyiwebapi.sinyi.com.tw/getObjectContent.php"
API_NAME = "getObjectContent.php"
DIRECT_CONCURRENCY = 8
DIRECT_TIMEOUT = 20
DIRECT_PASSES = 2


def apply_cache(rows, cache):
    resolved = 0
    missing = []
    for row in rows:
        hid = str(row.get("houseNo") or "").strip()
        if not hid:
            continue
        if row.get("firstDisplay"):
            resolved += 1
            continue
        hit = cache.get(hid) or {}
        if hit.get("firstDisplay"):
            row["firstDisplay"] = hit.get("firstDisplay")
            row["firstDisplayTimestamp"] = hit.get("timestamp")
            resolved += 1
        else:
            missing.append(hid)
    return resolved, sorted(set(missing))


async def bootstrap_api_request(house_id):
    """Open one detail page and capture Sinyi's live API request shape."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
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
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            async def inspect_request(request):
                if API_NAME not in request.url or future.done():
                    return
                try:
                    headers = await request.all_headers()
                    body = request.post_data_json
                    if callable(body):
                        body = body()
                    if not isinstance(body, dict):
                        raw = request.post_data or "{}"
                        body = json.loads(raw)
                    if str(body.get("houseNo") or "").upper() != str(house_id).upper():
                        return

                    keep = {
                        "accept",
                        "content-type",
                        "origin",
                        "referer",
                        "user-agent",
                        "code",
                        "sat",
                        "sid",
                    }
                    clean_headers = {
                        str(k).lower(): str(v)
                        for k, v in headers.items()
                        if str(k).lower() in keep
                    }
                    for required in ("sid", "sat", "code"):
                        if not clean_headers.get(required):
                            raise RuntimeError(f"bootstrap missing header: {required}")
                    if not future.done():
                        future.set_result(
                            {
                                "headers": clean_headers,
                                "body": dict(body),
                            }
                        )
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)

            def on_request(request):
                asyncio.create_task(inspect_request(request))

            page.on("request", on_request)
            url = f"https://www.sinyi.com.tw/buy/house/{house_id}?breadcrumb=list"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return await asyncio.wait_for(asyncio.shield(future), timeout=15)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            await browser.close()


def direct_fetch_one(house_id, bootstrap):
    headers = dict(bootstrap["headers"])
    headers.setdefault("accept", "application/json, text/plain, */*")
    headers.setdefault("content-type", "application/json")
    headers.setdefault("origin", "https://www.sinyi.com.tw")
    headers.setdefault("referer", "https://www.sinyi.com.tw/")

    body = dict(bootstrap["body"])
    body["houseNo"] = house_id
    body.setdefault("agentId", "")
    body.setdefault("memberPhone", "")
    body.setdefault("showOff", 0)

    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json=body,
            timeout=DIRECT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, dict):
            return house_id, None, f"no content retCode={payload.get('retCode') if isinstance(payload, dict) else None}"
        if str(content.get("houseNo") or "").upper() != house_id.upper():
            return house_id, None, "houseNo mismatch"
        raw = content.get("firstDisplay")
        timestamp = parse_first_display(raw)
        if not raw or not timestamp:
            return house_id, None, "firstDisplay missing"
        return house_id, {"firstDisplay": raw, "timestamp": timestamp}, None
    except Exception as exc:
        return house_id, None, f"{type(exc).__name__}: {exc}"


def direct_fetch_many(house_ids, bootstrap):
    results = []
    with ThreadPoolExecutor(max_workers=DIRECT_CONCURRENCY) as pool:
        futures = {
            pool.submit(direct_fetch_one, hid, bootstrap): hid
            for hid in house_ids
        }
        for future in as_completed(futures):
            hid = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append((hid, None, f"{type(exc).__name__}: {exc}"))
    return results


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    payload = load_json(DATA, {})
    rows = payload.get("listings") or []
    cache = load_json(CACHE, {})
    if not isinstance(cache, dict):
        cache = {}

    _, missing = apply_cache(rows, cache)
    direct_fetched = 0
    fallback_fetched = 0
    errors = []

    # HAR-confirmed fast path: one browser bootstrap, then direct API requests.
    for pass_no in range(1, DIRECT_PASSES + 1):
        if not missing:
            break
        bootstrap_id = missing[0]
        try:
            bootstrap = asyncio.run(bootstrap_api_request(bootstrap_id))
            print(
                f"firstDisplay API pass={pass_no} bootstrap={bootstrap_id} "
                f"remaining={len(missing)} sid={bootstrap['headers'].get('sid','')[:8]}..."
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            errors.append(f"bootstrap pass {pass_no}: {type(exc).__name__}: {exc}")
            break

        next_missing = []
        for hid, value, error in direct_fetch_many(missing, bootstrap):
            if value:
                cache[str(hid)] = value
                direct_fetched += 1
            else:
                next_missing.append(str(hid))
                if error:
                    errors.append(f"api {hid}: {error}")
        save_cache(cache)
        apply_cache(rows, cache)
        missing = sorted(set(next_missing))
        print(
            f"firstDisplay API pass={pass_no} directFetched={direct_fetched} "
            f"unresolved={len(missing)}"
        )

    # Browser fallback only for the minority that direct API could not resolve.
    if missing:
        print(f"firstDisplay browser fallback count={len(missing)}")
        try:
            results = asyncio.run(fetch_missing(missing))
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            results = []
            errors.append(f"fallback batch: {type(exc).__name__}: {exc}")

        still_missing = []
        for hid, value, error in results:
            if value and value.get("firstDisplay"):
                cache[str(hid)] = value
                fallback_fetched += 1
            else:
                still_missing.append(str(hid))
                if error:
                    errors.append(f"fallback {hid}: {error}")
        missing = sorted(set(still_missing))
        save_cache(cache)

    resolved, still_missing = apply_cache(rows, cache)

    # Preserve official original publish time on recent removed listings too.
    for row in payload.get("recentRemoved") or []:
        hid = str(row.get("houseNo") or "").strip()
        hit = cache.get(hid) or {}
        if not row.get("firstDisplay") and hit.get("firstDisplay"):
            row["firstDisplay"] = hit.get("firstDisplay")
            row["firstDisplayTimestamp"] = hit.get("timestamp")

    payload["firstDisplayMode"] = "api_direct_bootstrap_with_browser_fallback"
    payload["firstDisplayTotal"] = len(
        {str(x.get("houseNo")) for x in rows if x.get("houseNo")}
    )
    payload["firstDisplayResolved"] = resolved
    payload["firstDisplayDirectFetchedThisRun"] = direct_fetched
    payload["firstDisplayBrowserFallbackFetchedThisRun"] = fallback_fetched
    payload["firstDisplayFetchedThisRun"] = direct_fetched + fallback_fetched
    payload["firstDisplayMissing"] = len(still_missing)
    payload["firstDisplayMissingIds"] = still_missing
    payload["firstDisplayErrors"] = errors[-100:]
    payload["firstDisplayComplete"] = not still_missing

    DATA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_cache(cache)

    print(
        json.dumps(
            {
                "mode": payload["firstDisplayMode"],
                "total": payload["firstDisplayTotal"],
                "resolved": resolved,
                "directFetched": direct_fetched,
                "browserFallbackFetched": fallback_fetched,
                "missing": len(still_missing),
                "complete": payload["firstDisplayComplete"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
