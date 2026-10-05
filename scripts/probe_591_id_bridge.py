"""Isolated 591 legacy-post-id <-> web-houseid bridge probe.

Purpose:
- inspect the legacy mobile API raw fields used by the current crawler;
- build exact post_id -> houseid pairs for the seven monitored roads;
- fetch the desktop web API in the same run;
- verify whether web houseid can bridge current canonical IDs without fuzzy matching.

No canonical data is mutated.
"""
import asyncio
import concurrent.futures
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import requests
from playwright.async_api import async_playwright

ROADS = {
    "板橋區中山路二段": ("27507", ("中山路二段", "中山路2段")),
    "板橋區三民路二段": ("27485", ("三民路二段", "三民路2段")),
    "板橋區光復街": ("27550", ("光復街",)),
    "板橋區萬安街": ("27630", ("萬安街",)),
    "板橋區林森街": ("27574", ("林森街",)),
    "板橋區三民路一段": ("27484", ("三民路一段", "三民路1段")),
    "板橋區翠華街": ("27644", ("翠華街",)),
}
MOBILE_BASE = "https://m.591.com.tw/v2/sale"
WEB_API = "https://bff-house.591.com.tw/v1/web/sale/list"
OUT = Path("artifacts/591-id-bridge-report.json")
SOURCE = Path("docs/data/listings.json")
DEVICE_ID = hashlib.md5(b"banqiao-house-monitor-591-web-api").hexdigest()


def norm(v):
    text = "" if v is None else str(v)
    text = re.sub(r"\s+", " ", text).strip().replace("臺", "台")
    return (
        text.replace("中山路2段", "中山路二段")
        .replace("三民路1段", "三民路一段")
        .replace("三民路2段", "三民路二段")
    )


def mobile_page_url(road, sid):
    return MOBILE_BASE + "?" + urlencode({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": sid,
        "keywords": road.replace("板橋區", ""),
    })


def mutate_api_url(template, sid, first_row, page_no):
    p = urlparse(template)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.update({
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": sid,
        "firstRow": str(first_row),
        "newPage": str(page_no),
        "newPageSize": "30",
        "timestamp": str(int(time.time() * 1000)),
        "region_id": "3",
        "device": "touch",
    })
    return urlunparse(p._replace(query=urlencode(q)))


def unwrap_mobile(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        rows = data.get("items") or data.get("list") or data.get("data") or []
    else:
        rows = data or []
    return rows if isinstance(rows, list) else []


def exact_mobile_row(raw, aliases):
    if not isinstance(raw, dict):
        return None
    region = norm(raw.get("region") or raw.get("region_name"))
    section = norm(raw.get("section") or raw.get("section_name"))
    address = norm(raw.get("address") or raw.get("address_new"))
    if region and region != "新北市":
        return None
    if section and section != "板橋區":
        return None
    if not any(norm(a) in address for a in aliases):
        return None

    post_id = norm(raw.get("post_id") or raw.get("postId"))
    house_raw = norm(raw.get("houseid") or raw.get("houseId"))
    m = re.search(r"(\d{6,})", house_raw)
    house_id = m.group(1) if m else ""
    if not post_id or not house_id:
        return None
    return {
        "postId": post_id,
        "houseId": house_id,
        "legacyId": f"591:{post_id}",
        "webId": f"591:{house_id}",
        "title": norm(raw.get("title") or raw.get("name")),
        "address": address,
    }


async def fetch_mobile_road(browser, road, sid, aliases):
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )
    page = await context.new_page()
    await page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "font", "media"}
        else route.continue_(),
    )
    captured = []
    page.on(
        "response",
        lambda response: captured.append(response.url)
        if response.status == 200 and (
            "bff-house.591.com.tw/v1/touch/sale/list" in response.url
            or ("bff-house.591.com.tw/v2/php-api" in response.url and "action=list" in response.url)
        )
        else None,
    )

    try:
        for attempt in (1, 2):
            target = mobile_page_url(road, sid)
            if attempt == 2:
                target += f"&_bridge={int(time.time())}"
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            for _ in range(24):
                if captured:
                    break
                await page.wait_for_timeout(250)
            if captured:
                break

        if not captured:
            raise RuntimeError(f"{road}: no mobile API captured")
        template = captured[-1]
        pairs = {}
        raw_seen = set()
        page_stats = []
        for page_no in range(1, 11):
            url = mutate_api_url(template, sid, (page_no - 1) * 30, page_no)
            response = None
            last_error = None
            for retry_no, delay in enumerate((0, 0.6, 1.5), start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    candidate = await context.request.get(
                        url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Referer": "https://m.591.com.tw/",
                            "Origin": "https://m.591.com.tw",
                        },
                        timeout=20000,
                    )
                    if candidate.status == 200:
                        response = candidate
                        break
                    last_error = f"HTTP {candidate.status}"
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
            if response is None:
                raise RuntimeError(f"{road}: page {page_no} failed after retries: {last_error}")
            payload = await response.json()
            rows = unwrap_mobile(payload)
            page_stats.append({"page": page_no, "rawCount": len(rows)})
            new = 0
            for raw in rows:
                key = json.dumps(raw, ensure_ascii=False, sort_keys=True)
                if key not in raw_seen:
                    raw_seen.add(key)
                    new += 1
                pair = exact_mobile_row(raw, aliases)
                if pair:
                    pairs[pair["legacyId"]] = pair
            if not rows or len(rows) < 30 or (page_no > 1 and new == 0):
                break
        return {
            "road": road,
            "templateHost": urlparse(template).netloc,
            "pairCount": len(pairs),
            "pairs": list(pairs.values()),
            "pages": page_stats,
        }
    finally:
        await context.close()


async def fetch_mobile_all():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
        try:
            semaphore = asyncio.Semaphore(3)

            async def guarded(road, cfg):
                async with semaphore:
                    try:
                        return await fetch_mobile_road(browser, road, cfg[0], cfg[1])
                    except Exception as exc:
                        return {
                            "road": road,
                            "error": f"{type(exc).__name__}: {exc}",
                            "pairCount": 0,
                            "pairs": [],
                            "pages": [],
                        }

            tasks = [guarded(road, cfg) for road, cfg in ROADS.items()]
            return await asyncio.gather(*tasks)
        finally:
            await browser.close()


def web_page(road, sid, first_row):
    r = requests.get(
        WEB_API,
        params={
            "timestamp": str(int(time.time() * 1000)),
            "type": "2",
            "category": "1",
            "keywords": road.replace("板橋區", ""),
            "regionid": "3",
            "firstRow": str(first_row),
            "shType": "list",
            "streetid": sid,
            "match_type": "3",
        },
        headers={
            "Accept": "*/*",
            "Origin": "https://sale.591.com.tw",
            "Referer": "https://sale.591.com.tw/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0 Safari/537.36",
            "device": "pc",
            "deviceid": DEVICE_ID,
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json().get("data") or {}
    return int(data.get("total") or 0), data.get("house_list") or []


def fetch_web_road(road, sid, aliases):
    total, first = web_page(road, sid, 0)
    offsets = list(range(30, total + 30, 30))
    rows = list(first)
    if offsets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(offsets))) as ex:
            for _, page_rows in ex.map(lambda x: web_page(road, sid, x), offsets):
                rows.extend(page_rows)
    ids = set()
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("is_newhouse") == 1:
            continue
        if norm(raw.get("region_name")) not in ("", "新北市"):
            continue
        if norm(raw.get("section_name")) not in ("", "板橋區"):
            continue
        address = norm(raw.get("street_name") or raw.get("address"))
        if not any(norm(a) in address for a in aliases):
            continue
        hid = norm(raw.get("houseid") or raw.get("houseId"))
        if re.fullmatch(r"\d{6,}", hid):
            ids.add(f"591:{hid}")
    return road, ids


def fetch_web_all():
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futs = [
            ex.submit(fetch_web_road, road, cfg[0], cfg[1])
            for road, cfg in ROADS.items()
        ]
        for fut in concurrent.futures.as_completed(futs):
            road, ids = fut.result()
            results[road] = ids
    return results


def active_legacy_ids():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_road = {r: set() for r in ROADS}
    for row in data.get("listings") or []:
        if row.get("source") == "591" and row.get("active", True) is True:
            road = row.get("road")
            if road in by_road and row.get("id"):
                by_road[road].add(str(row["id"]))
    return by_road


def main():
    started = time.perf_counter()
    mobile = asyncio.run(fetch_mobile_all())
    mobile_elapsed = time.perf_counter() - started

    web_started = time.perf_counter()
    web = fetch_web_all()
    web_elapsed = time.perf_counter() - web_started

    current = active_legacy_ids()
    summary = []
    bridge = {}
    all_pairs = []
    for mr in mobile:
        road = mr["road"]
        web_ids = web.get(road, set())
        pairs = mr["pairs"]
        pair_by_legacy = {p["legacyId"]: p for p in pairs}
        pair_web_ids = {p["webId"] for p in pairs}
        exact_web_hits = [p for p in pairs if p["webId"] in web_ids]
        current_ids = current.get(road, set())
        current_mapped = [pair_by_legacy[x] for x in sorted(current_ids) if x in pair_by_legacy]
        current_web_present = [p for p in current_mapped if p["webId"] in web_ids]

        for p in pairs:
            if p["webId"] in web_ids:
                bridge[p["webId"]] = p["legacyId"]
                all_pairs.append({**p, "road": road})

        summary.append({
            "road": road,
            "mobileError": mr.get("error"),
            "mobilePairCount": len(pairs),
            "webExactCount": len(web_ids),
            "mobilePairsPresentInWeb": len(exact_web_hits),
            "mobilePairsMissingFromWeb": len(pairs) - len(exact_web_hits),
            "currentActiveLegacyCount": len(current_ids),
            "currentActiveMappedCount": len(current_mapped),
            "currentActiveMappedAndPresentInWebCount": len(current_web_present),
            "currentActiveUnmappedIds": sorted(current_ids - set(pair_by_legacy)),
            "currentActiveMappedButMissingWebIds": sorted(
                p["legacyId"] for p in current_mapped if p["webId"] not in web_ids
            ),
        })

    current_total = sum(len(v) for v in current.values())
    current_mapped_total = sum(x["currentActiveMappedCount"] for x in summary)
    current_present_total = sum(x["currentActiveMappedAndPresentInWebCount"] for x in summary)

    report = {
        "mode": "591_exact_postid_houseid_bridge_probe_v1",
        "mobileElapsedSeconds": round(mobile_elapsed, 3),
        "webElapsedSeconds": round(web_elapsed, 3),
        "currentActiveLegacyCount": current_total,
        "currentActiveMappedCount": current_mapped_total,
        "currentActiveMappedAndPresentInWebCount": current_present_total,
        "currentActiveBridgeCoverage": round(current_mapped_total / current_total, 4) if current_total else 1,
        "currentActiveWebPresenceCoverage": round(current_present_total / current_total, 4) if current_total else 1,
        "bridgeEntryCount": len(bridge),
        "bridge": bridge,
        "pairs": all_pairs,
        "roads": summary,
        "mobile": mobile,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        k: report[k] for k in (
            "mobileElapsedSeconds", "webElapsedSeconds",
            "currentActiveLegacyCount", "currentActiveMappedCount",
            "currentActiveMappedAndPresentInWebCount",
            "currentActiveBridgeCoverage", "currentActiveWebPresenceCoverage",
            "bridgeEntryCount",
        )
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
