"""Compare current 591 seven-context crawler with one-warmup shared-session crawler.

Both paths use the SAME legacy mobile 591 API and the SAME parser/IDs.
No canonical data is mutated.
"""
import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-shared-warmup-report.json")


async def make_context(browser):
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )
    return context


async def capture_one_template(context):
    road, sid = next(iter(core.WATCH_591_STREETS.items()))
    page = await context.new_page()

    async def route_handler(route):
        if route.request.resource_type in {"image", "font", "media"}:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)
    captured = []

    def on_response(response):
        url = response.url
        if response.status == 200 and (
            monitor_fast.API_591_V1 in url
            or (monitor_fast.API_591_V2 in url and "action=list" in url)
        ):
            captured.append(url)

    page.on("response", on_response)
    try:
        bootstrap = core.build_591_page_url(road, sid)
        for round_no in (1, 2):
            target = bootstrap if round_no == 1 else bootstrap + f"&_shared={int(time.time())}"
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            for tick in range(24):
                if captured:
                    break
                if tick in (6, 12, 18):
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass
                await page.wait_for_timeout(250)
            if captured:
                break
        if not captured:
            raise RuntimeError("shared warmup did not capture 591 list API")
        return captured[-1]
    finally:
        await page.close()


async def fetch_road(context, template, road, sid, semaphore):
    rows = []
    seen = set()
    page_stats = []
    async with semaphore:
        for page_no in range(1, 11):
            first_row = (page_no - 1) * 30
            api_url = monitor_fast.build_api_url(template, sid, first_row, page_no)
            payload = None
            last_error = None
            started = time.perf_counter()
            for attempt, delay in enumerate((0, 0.35, 0.8), start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await context.request.get(
                        api_url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Referer": "https://m.591.com.tw/",
                            "Origin": "https://m.591.com.tw",
                        },
                        timeout=12000,
                    )
                    if response.status == 200:
                        payload = await response.json()
                        break
                    last_error = f"HTTP {response.status}"
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"

            if payload is None:
                return {
                    "road": road,
                    "ok": False,
                    "error": f"page {page_no}: {last_error}",
                    "rows": [],
                    "pageStats": page_stats,
                }

            parsed, raw_count = core.parse_591_api_payload(payload, road)
            new_rows = [x for x in parsed if x["id"] not in seen]
            for row in new_rows:
                seen.add(row["id"])
                rows.append(row)

            page_stats.append({
                "page": page_no,
                "rawCount": raw_count,
                "exactCount": len(parsed),
                "newCount": len(new_rows),
                "seconds": round(time.perf_counter() - started, 3),
            })
            if raw_count == 0:
                break
            if page_no > 1 and not new_rows:
                break
            if raw_count < 30:
                break

    return {"road": road, "ok": True, "rows": rows, "pageStats": page_stats}


async def shared_fetch():
    started = time.perf_counter()
    async with async_playwright() as p:
        browser = await monitor_fast.launch_591_browser(p)
        try:
            context = await make_context(browser)
            try:
                template = await capture_one_template(context)
                warmup_done = time.perf_counter()
                semaphore = asyncio.Semaphore(7)
                tasks = [
                    fetch_road(context, template, road, sid, semaphore)
                    for road, sid in core.WATCH_591_STREETS.items()
                ]
                road_results = await asyncio.gather(*tasks)
            finally:
                await context.close()
        finally:
            await browser.close()

    all_rows = []
    ok = True
    for rr in road_results:
        if not rr["ok"]:
            ok = False
        all_rows.extend(rr["rows"])
    return {
        "ok": ok,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "warmupSeconds": round(warmup_done - started, 3),
        "apiFetchSeconds": round(time.perf_counter() - warmup_done, 3),
        "rows": all_rows,
        "roads": road_results,
    }


def by_road(rows):
    out = {road: {} for road in core.WATCH_591_STREETS}
    for row in rows:
        road = row.get("road")
        rid = row.get("id")
        if road in out and rid:
            out[road][str(rid)] = row
    return out


def comparable(row):
    return {
        "title": row.get("title"),
        "address": row.get("address"),
        "price": row.get("price"),
        "size": row.get("size"),
        "postTime": row.get("postTime"),
    }


def main():
    baseline_started = time.perf_counter()
    baseline_rows, baseline_ok, baseline_message, baseline_logs = asyncio.run(
        monitor_fast.fast_fetch_591()
    )
    baseline_elapsed = round(time.perf_counter() - baseline_started, 3)
    if not baseline_ok:
        raise RuntimeError("baseline crawler failed: " + baseline_message)

    shared = asyncio.run(shared_fetch())
    if not shared["ok"]:
        errors = [x for x in shared["roads"] if not x["ok"]]
        raise RuntimeError("shared crawler incomplete: " + json.dumps(errors, ensure_ascii=False))

    base = by_road(baseline_rows)
    fast = by_road(shared["rows"])
    roads = []
    total_field_mismatch = 0
    total_base_only = 0
    total_shared_only = 0

    for road in core.WATCH_591_STREETS:
        b = base[road]
        f = fast[road]
        common = sorted(set(b) & set(f))
        field_mismatch = []
        for rid in common:
            if comparable(b[rid]) != comparable(f[rid]):
                field_mismatch.append({
                    "id": rid,
                    "baseline": comparable(b[rid]),
                    "shared": comparable(f[rid]),
                })
        base_only = sorted(set(b) - set(f))
        shared_only = sorted(set(f) - set(b))
        total_field_mismatch += len(field_mismatch)
        total_base_only += len(base_only)
        total_shared_only += len(shared_only)
        rr = next(x for x in shared["roads"] if x["road"] == road)
        roads.append({
            "road": road,
            "baselineCount": len(b),
            "sharedCount": len(f),
            "baselineOnlyIds": base_only,
            "sharedOnlyIds": shared_only,
            "fieldMismatchCount": len(field_mismatch),
            "fieldMismatches": field_mismatch[:20],
            "sharedPageStats": rr["pageStats"],
        })

    report = {
        "mode": "591_legacy_mobile_shared_warmup_probe_v1",
        "baselineElapsedSeconds": baseline_elapsed,
        "baselineMessage": baseline_message,
        "sharedElapsedSeconds": shared["elapsedSeconds"],
        "sharedWarmupSeconds": shared["warmupSeconds"],
        "sharedApiFetchSeconds": shared["apiFetchSeconds"],
        "baselineCount": len(baseline_rows),
        "sharedCount": len(shared["rows"]),
        "baselineOnlyCount": total_base_only,
        "sharedOnlyCount": total_shared_only,
        "fieldMismatchCount": total_field_mismatch,
        "allIdSetsMatch": total_base_only == 0 and total_shared_only == 0,
        "allComparedFieldsMatch": total_field_mismatch == 0,
        "roads": roads,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        k: report[k] for k in (
            "baselineElapsedSeconds", "sharedElapsedSeconds",
            "sharedWarmupSeconds", "sharedApiFetchSeconds",
            "baselineCount", "sharedCount",
            "baselineOnlyCount", "sharedOnlyCount",
            "fieldMismatchCount", "allIdSetsMatch", "allComparedFieldsMatch",
        )
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
