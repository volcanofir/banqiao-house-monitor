"""Validate a deterministic fast path for the SAME legacy 591 mobile API.

Candidate strategy:
1. keep the current per-road mobile Chrome warmup/session;
2. force recom_community=0 to remove dynamic recommendation rows;
3. use official totalRows to determine the exact page count;
4. fetch pages 2..N concurrently;
5. trim each page to its expected core-row count before the existing parser.

Runs the current crawler once and the candidate twice. No canonical data is mutated.
"""
import asyncio
import copy
import json
import math
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core
import dedupe_listings_v2 as deduper

OUT = Path("artifacts/591-parallel-pages-report.json")
PAGE_SIZE = 30
MAX_PAGE_CONCURRENCY_PER_ROAD = 4


def force_core_mode(url):
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["recom_community"] = "0"
    q["timestamp"] = str(int(time.time() * 1000))
    return urlunparse(p._replace(query=urlencode(q)))


async def request_payload(context, url):
    last_error = None
    for delay in (0, 0.4, 1.0):
        if delay:
            await asyncio.sleep(delay)
        try:
            response = await context.request.get(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://m.591.com.tw/",
                    "Origin": "https://m.591.com.tw",
                },
                timeout=12000,
            )
            if response.status == 200:
                return await response.json()
            last_error = f"HTTP {response.status}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(last_error or "unknown request failure")


async def fetch_page(context, template_url, street_id, road, page_no, total_rows=None):
    first_row = (page_no - 1) * PAGE_SIZE
    url = force_core_mode(
        monitor_fast.build_api_url(template_url, street_id, first_row, page_no)
    )
    started = time.perf_counter()
    payload = await request_payload(context, url)

    if not isinstance(payload, dict):
        raise RuntimeError(f"{road} page {page_no}: wrapper is not dict")

    wrapper_total = int(payload.get("totalRows") or 0)
    if total_rows is None:
        total_rows = wrapper_total
    if total_rows <= 0:
        raise RuntimeError(f"{road} page {page_no}: missing totalRows")
    if wrapper_total and wrapper_total != total_rows:
        raise RuntimeError(
            f"{road} page {page_no}: totalRows changed {total_rows}->{wrapper_total}"
        )

    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"{road} page {page_no}: data is not list")

    expected = max(0, min(PAGE_SIZE, total_rows - first_row))
    if len(data) < expected:
        raise RuntimeError(
            f"{road} page {page_no}: core rows incomplete {len(data)} < {expected}"
        )

    # In core mode, any rows beyond the official page capacity are dynamic extras.
    core_data = data[:expected]
    core_payload = copy.deepcopy(payload)
    core_payload["data"] = core_data
    rows, raw_count = core.parse_591_api_payload(core_payload, road)

    return {
        "page": page_no,
        "firstRow": first_row,
        "totalRows": total_rows,
        "rawReturned": len(data),
        "coreRawCount": len(core_data),
        "parsedRawCount": raw_count,
        "exactCount": len(rows),
        "rows": rows,
        "seconds": round(time.perf_counter() - started, 3),
    }


async def fetch_one_road(browser, road, street_id):
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
        bootstrap = core.build_591_page_url(road, street_id)
        for round_no in (1, 2):
            target = bootstrap
            if round_no == 2:
                target += f"&_core={int(time.time())}-{round_no}"
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
            raise RuntimeError(f"{road}: no 591 API template")

        template = captured[-1]
        first = await fetch_page(context, template, street_id, road, 1)
        total_rows = first["totalRows"]
        total_pages = max(1, math.ceil(total_rows / PAGE_SIZE))

        pages = [first]
        if total_pages > 1:
            sem = asyncio.Semaphore(MAX_PAGE_CONCURRENCY_PER_ROAD)

            async def guarded(page_no):
                async with sem:
                    return await fetch_page(
                        context, template, street_id, road, page_no, total_rows
                    )

            pages.extend(await asyncio.gather(*[
                guarded(n) for n in range(2, total_pages + 1)
            ]))

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
            "elapsedSeconds": round(time.perf_counter() - started, 3),
            "pages": [
                {k: x[k] for k in (
                    "page", "firstRow", "rawReturned", "coreRawCount",
                    "exactCount", "seconds"
                )}
                for x in sorted(pages, key=lambda x: x["page"])
            ],
        }
    finally:
        await context.close()


async def candidate_fetch():
    started = time.perf_counter()
    async with async_playwright() as p:
        browser = await monitor_fast.launch_591_browser(p)
        try:
            roads = await asyncio.gather(*[
                fetch_one_road(browser, road, sid)
                for road, sid in core.WATCH_591_STREETS.items()
            ])
        finally:
            await browser.close()

    rows = []
    for rr in roads:
        rows.extend(rr["rows"])
    return {
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "rows": rows,
        "roads": roads,
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


def compare(left_rows, right_rows):
    left = by_road(left_rows)
    right = by_road(right_rows)
    roads = []
    left_only_total = right_only_total = mismatch_total = 0
    for road in core.WATCH_591_STREETS:
        l = left[road]
        r = right[road]
        left_only = sorted(set(l) - set(r))
        right_only = sorted(set(r) - set(l))
        mismatches = []
        for rid in sorted(set(l) & set(r)):
            if comparable(l[rid]) != comparable(r[rid]):
                mismatches.append({
                    "id": rid,
                    "left": comparable(l[rid]),
                    "right": comparable(r[rid]),
                })
        left_only_total += len(left_only)
        right_only_total += len(right_only)
        mismatch_total += len(mismatches)
        roads.append({
            "road": road,
            "leftCount": len(l),
            "rightCount": len(r),
            "leftOnlyIds": left_only,
            "rightOnlyIds": right_only,
            "fieldMismatchCount": len(mismatches),
            "fieldMismatches": mismatches[:20],
        })
    return {
        "leftOnlyCount": left_only_total,
        "rightOnlyCount": right_only_total,
        "fieldMismatchCount": mismatch_total,
        "allIdSetsMatch": left_only_total == 0 and right_only_total == 0,
        "allComparedFieldsMatch": mismatch_total == 0,
        "roads": roads,
    }


def simulate_canonical(base_state, rows, checked_at):
    state = copy.deepcopy(base_state)
    core.merge_source(
        state,
        "591",
        rows,
        True,
        "simulation",
        [],
        checked_at,
    )
    deduped, removed, raw_count = deduper.dedupe(state.get("listings") or [])
    visible = [
        x for x in deduped
        if x.get("source") == "591" and x.get("active", True) is True
    ]
    visible.sort(key=lambda x: str(x.get("id") or ""))
    return visible


def canonical_projection(rows):
    return [
        {
            "id": x.get("id"),
            "road": x.get("road"),
            "title": x.get("title"),
            "price": x.get("price"),
            "size": x.get("size"),
            "address": x.get("address"),
            "active": x.get("active", True),
            "mergedListingCount": int(x.get("mergedListingCount") or 1),
            "mergedActiveListingCount": int(x.get("mergedActiveListingCount") or (1 if x.get("active", True) else 0)),
        }
        for x in rows
    ]


def canonical_diff(left, right):
    l = {str(x.get("id")): x for x in canonical_projection(left)}
    r = {str(x.get("id")): x for x in canonical_projection(right)}
    common = sorted(set(l) & set(r))
    mismatches = [
        {"id": rid, "left": l[rid], "right": r[rid]}
        for rid in common
        if l[rid] != r[rid]
    ]
    return {
        "leftCount": len(l),
        "rightCount": len(r),
        "leftOnlyIds": sorted(set(l) - set(r)),
        "rightOnlyIds": sorted(set(r) - set(l)),
        "fieldMismatchCount": len(mismatches),
        "fieldMismatches": mismatches[:30],
        "allMatch": set(l) == set(r) and not mismatches,
    }


def main():
    baseline_started = time.perf_counter()
    baseline_rows, baseline_ok, baseline_message, _ = asyncio.run(
        monitor_fast.fast_fetch_591()
    )
    baseline_elapsed = round(time.perf_counter() - baseline_started, 3)
    if not baseline_ok:
        raise RuntimeError("baseline failed: " + baseline_message)

    candidate_a = asyncio.run(candidate_fetch())
    candidate_b = asyncio.run(candidate_fetch())

    ab = compare(candidate_a["rows"], candidate_b["rows"])
    base_a = compare(baseline_rows, candidate_a["rows"])

    base_state = core.load_state()
    checked_at = core.now_iso()
    canonical_baseline = simulate_canonical(base_state, baseline_rows, checked_at)
    canonical_a = simulate_canonical(base_state, candidate_a["rows"], checked_at)
    canonical_b = simulate_canonical(base_state, candidate_b["rows"], checked_at)
    canonical_base_a = canonical_diff(canonical_baseline, canonical_a)
    canonical_a_b = canonical_diff(canonical_a, canonical_b)

    report = {
        "mode": "591_legacy_core_parallel_pages_probe_v2",
        "baselineElapsedSeconds": baseline_elapsed,
        "candidateAElapsedSeconds": candidate_a["elapsedSeconds"],
        "candidateBElapsedSeconds": candidate_b["elapsedSeconds"],
        "baselineCount": len(baseline_rows),
        "candidateACount": len(candidate_a["rows"]),
        "candidateBCount": len(candidate_b["rows"]),
        "candidateRepeat": ab,
        "baselineVsCandidate": base_a,
        "canonicalBaselineCount": len(canonical_baseline),
        "canonicalCandidateACount": len(canonical_a),
        "canonicalCandidateBCount": len(canonical_b),
        "canonicalBaselineVsCandidateA": canonical_base_a,
        "canonicalCandidateARepeat": canonical_a_b,
        "candidateARoadMeta": [
            {
                "road": x["road"],
                "totalRows": x["totalRows"],
                "totalPages": x["totalPages"],
                "elapsedSeconds": x["elapsedSeconds"],
                "pages": x["pages"],
            }
            for x in candidate_a["roads"]
        ],
        "candidateBRoadMeta": [
            {
                "road": x["road"],
                "totalRows": x["totalRows"],
                "totalPages": x["totalPages"],
                "elapsedSeconds": x["elapsedSeconds"],
                "pages": x["pages"],
            }
            for x in candidate_b["roads"]
        ],
        "baselineMessage": baseline_message,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "baselineElapsedSeconds": baseline_elapsed,
        "candidateAElapsedSeconds": candidate_a["elapsedSeconds"],
        "candidateBElapsedSeconds": candidate_b["elapsedSeconds"],
        "baselineCount": len(baseline_rows),
        "candidateACount": len(candidate_a["rows"]),
        "candidateBCount": len(candidate_b["rows"]),
        "candidateRepeatAllIdSetsMatch": ab["allIdSetsMatch"],
        "candidateRepeatAllComparedFieldsMatch": ab["allComparedFieldsMatch"],
        "candidateRepeatLeftOnlyCount": ab["leftOnlyCount"],
        "candidateRepeatRightOnlyCount": ab["rightOnlyCount"],
        "baselineVsCandidateLeftOnlyCount": base_a["leftOnlyCount"],
        "baselineVsCandidateRightOnlyCount": base_a["rightOnlyCount"],
        "canonicalBaselineCount": len(canonical_baseline),
        "canonicalCandidateACount": len(canonical_a),
        "canonicalCandidateBCount": len(canonical_b),
        "canonicalBaselineVsCandidateAllMatch": canonical_base_a["allMatch"],
        "canonicalCandidateRepeatAllMatch": canonical_a_b["allMatch"],
        "canonicalBaselineVsCandidateLeftOnly": len(canonical_base_a["leftOnlyIds"]),
        "canonicalBaselineVsCandidateRightOnly": len(canonical_base_a["rightOnlyIds"]),
        "canonicalBaselineVsCandidateFieldMismatch": canonical_base_a["fieldMismatchCount"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
