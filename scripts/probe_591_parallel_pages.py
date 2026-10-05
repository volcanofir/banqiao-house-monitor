"""Compare current 591 crawler with parallel pagination on the same legacy mobile API.

No canonical data is mutated.
"""
import asyncio
import json
import math
import time
from pathlib import Path

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-parallel-pages-report.json")
PAGE_SIZE = 30
MAX_PAGE_CONCURRENCY_PER_ROAD = 4


async def fetch_page(context, template_url, street_id, road, page_no):
    first_row = (page_no - 1) * PAGE_SIZE
    api_url = monitor_fast.build_api_url(template_url, street_id, first_row, page_no)
    last_error = None
    started = time.perf_counter()
    for attempt, delay in enumerate((0, 0.4, 1.0), start=1):
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
                rows, raw_count = core.parse_591_api_payload(payload, road)
                total_rows = 0
                if isinstance(payload, dict):
                    try:
                        total_rows = int(payload.get("totalRows") or 0)
                    except Exception:
                        total_rows = 0
                return {
                    "ok": True,
                    "page": page_no,
                    "payload": payload,
                    "rows": rows,
                    "rawCount": raw_count,
                    "totalRows": total_rows,
                    "seconds": round(time.perf_counter() - started, 3),
                }
            last_error = f"HTTP {response.status}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": False,
        "page": page_no,
        "error": last_error,
        "seconds": round(time.perf_counter() - started, 3),
    }


async def fetch_one_road(browser, road, street_id):
    logs = []
    started = time.perf_counter()
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
    page = await context.new_page()

    async def route_handler(route):
        if route.request.resource_type in {"image", "font", "media"}:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)
    captured = []

    def on_response(response):
        u = response.url
        if response.status == 200 and (
            monitor_fast.API_591_V1 in u
            or (monitor_fast.API_591_V2 in u and "action=list" in u)
        ):
            captured.append(u)

    page.on("response", on_response)

    try:
        bootstrap_url = core.build_591_page_url(road, street_id)
        for round_no in (1, 2):
            target = bootstrap_url
            if round_no == 2:
                target += f"&_parallel={int(time.time())}-{round_no}"
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                logs.append(f"warmup {round_no}: {type(exc).__name__}")
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
            return {"road": road, "ok": False, "error": "no API template", "rows": []}

        template = captured[-1]
        first = await fetch_page(context, template, street_id, road, 1)
        if not first["ok"]:
            return {"road": road, "ok": False, "error": first.get("error"), "rows": []}

        total_rows = first.get("totalRows") or 0
        if total_rows > 0:
            total_pages = max(1, math.ceil(total_rows / PAGE_SIZE))
        else:
            # Metadata absent: preserve conservative old behavior by not guessing.
            total_pages = 1

        pages = [first]
        if total_pages > 1:
            sem = asyncio.Semaphore(MAX_PAGE_CONCURRENCY_PER_ROAD)

            async def guarded(page_no):
                async with sem:
                    return await fetch_page(context, template, street_id, road, page_no)

            tail = await asyncio.gather(*[
                guarded(n) for n in range(2, total_pages + 1)
            ])
            pages.extend(tail)

        failed = [x for x in pages if not x.get("ok")]
        if failed:
            return {
                "road": road,
                "ok": False,
                "error": f"failed pages {[x.get('page') for x in failed]}",
                "rows": [],
                "pages": pages,
            }

        by_id = {}
        for pg in sorted(pages, key=lambda x: x["page"]):
            for row in pg["rows"]:
                by_id[row["id"]] = row

        return {
            "road": road,
            "ok": True,
            "totalRows": total_rows,
            "totalPages": total_pages,
            "rows": list(by_id.values()),
            "pages": [
                {
                    "page": x["page"],
                    "rawCount": x["rawCount"],
                    "exactCount": len(x["rows"]),
                    "seconds": x["seconds"],
                }
                for x in sorted(pages, key=lambda x: x["page"])
            ],
            "elapsedSeconds": round(time.perf_counter() - started, 3),
            "logs": logs,
        }
    finally:
        await context.close()


async def fast_parallel_pages():
    started = time.perf_counter()
    async with async_playwright() as p:
        browser = await monitor_fast.launch_591_browser(p)
        try:
            results = await asyncio.gather(*[
                fetch_one_road(browser, road, sid)
                for road, sid in core.WATCH_591_STREETS.items()
            ])
        finally:
            await browser.close()

    ok = all(x.get("ok") for x in results)
    rows = []
    for x in results:
        rows.extend(x.get("rows") or [])
    return {
        "ok": ok,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "rows": rows,
        "roads": results,
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
        raise RuntimeError("baseline failed: " + baseline_message)

    candidate = asyncio.run(fast_parallel_pages())
    if not candidate["ok"]:
        raise RuntimeError(
            "parallel-pages failed: "
            + json.dumps([x for x in candidate["roads"] if not x.get("ok")], ensure_ascii=False)
        )

    b = by_road(baseline_rows)
    c = by_road(candidate["rows"])
    road_reports = []
    base_only_total = 0
    cand_only_total = 0
    mismatch_total = 0

    for road in core.WATCH_591_STREETS:
        br = b[road]
        cr = c[road]
        base_only = sorted(set(br) - set(cr))
        cand_only = sorted(set(cr) - set(br))
        common = sorted(set(br) & set(cr))
        mismatches = []
        for rid in common:
            if comparable(br[rid]) != comparable(cr[rid]):
                mismatches.append({
                    "id": rid,
                    "baseline": comparable(br[rid]),
                    "candidate": comparable(cr[rid]),
                })
        base_only_total += len(base_only)
        cand_only_total += len(cand_only)
        mismatch_total += len(mismatches)
        meta = next(x for x in candidate["roads"] if x["road"] == road)
        road_reports.append({
            "road": road,
            "baselineCount": len(br),
            "candidateCount": len(cr),
            "baselineOnlyIds": base_only,
            "candidateOnlyIds": cand_only,
            "fieldMismatchCount": len(mismatches),
            "fieldMismatches": mismatches[:20],
            "totalRows": meta.get("totalRows"),
            "totalPages": meta.get("totalPages"),
            "elapsedSeconds": meta.get("elapsedSeconds"),
            "pages": meta.get("pages"),
        })

    report = {
        "mode": "591_legacy_parallel_pages_probe_v1",
        "baselineElapsedSeconds": baseline_elapsed,
        "candidateElapsedSeconds": candidate["elapsedSeconds"],
        "baselineCount": len(baseline_rows),
        "candidateCount": len(candidate["rows"]),
        "baselineOnlyCount": base_only_total,
        "candidateOnlyCount": cand_only_total,
        "fieldMismatchCount": mismatch_total,
        "allIdSetsMatch": base_only_total == 0 and cand_only_total == 0,
        "allComparedFieldsMatch": mismatch_total == 0,
        "baselineMessage": baseline_message,
        "roads": road_reports,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        k: report[k] for k in (
            "baselineElapsedSeconds",
            "candidateElapsedSeconds",
            "baselineCount",
            "candidateCount",
            "baselineOnlyCount",
            "candidateOnlyCount",
            "fieldMismatchCount",
            "allIdSetsMatch",
            "allComparedFieldsMatch",
        )
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
