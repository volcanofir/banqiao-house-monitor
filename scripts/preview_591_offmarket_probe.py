"""Rendered-browser confirmation for stale 591 sale listings.

Checks stale candidates concurrently while preserving the same conservative rule:
only explicit 591 invalid/off-market wording or HTTP 404/410 confirms removal.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

SOURCE = Path("docs/data/listings.json")
OUT = Path("docs/preview/591-offmarket-probe.json")
MAX_CANDIDATES = 40
STALE_GRACE_SECONDS = 60
POLL_SECONDS = 3.4
MAX_PARALLEL = 4

MARKERS = (
    "不存在此物件",
    "此物件不存在",
    "物件不存在",
    "案件已下架",
    "物件已下架",
    "找不到此案件",
    "此案件不存在",
)


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def candidate_rows(payload):
    run = (payload.get("runs") or {}).get("591") or {}
    if run.get("status") != "ok":
        return [], run.get("checkedAt")
    checked = parse_dt(run.get("checkedAt"))
    if checked is None:
        return [], run.get("checkedAt")

    rows = []
    for row in payload.get("listings") or []:
        if row.get("source") != "591" or row.get("active", True) is not True:
            continue
        last = parse_dt(row.get("lastSeenAt"))
        if last is None:
            continue
        if (checked - last).total_seconds() <= STALE_GRACE_SECONDS:
            continue
        rows.append(row)
    rows.sort(key=lambda x: str(x.get("lastSeenAt") or ""))
    return rows[:MAX_CANDIDATES], run.get("checkedAt")


def detail_urls(row):
    house_id = str(row.get("houseId") or "").strip()
    urls = []
    if house_id:
        urls.append(f"https://sale.591.com.tw/home/house/detail/2/{house_id}.html")
        urls.append(f"https://m.591.com.tw/v2/sale/{house_id}")
    if row.get("url"):
        urls.append(str(row.get("url")))
    return list(dict.fromkeys(urls))


async def rendered_probe(page, url):
    status = None
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=18000)
        status = response.status if response is not None else None
    except Exception as exc:
        return {"url": url, "httpStatus": status, "confirmed": False, "error": str(exc)[:500]}

    if status in (404, 410):
        return {
            "url": url,
            "httpStatus": status,
            "confirmed": True,
            "evidence": f"HTTP {status}",
            "marker": f"HTTP {status}",
        }

    deadline = time.monotonic() + POLL_SECONDS
    last_text = ""
    while time.monotonic() < deadline:
        try:
            text = await page.locator("body").inner_text(timeout=1000)
        except Exception:
            text = ""
        if text:
            last_text = " ".join(text.split())
            for marker in MARKERS:
                if marker in last_text:
                    return {
                        "url": url,
                        "httpStatus": status,
                        "confirmed": True,
                        "evidence": last_text[:500],
                        "marker": marker,
                    }
        await page.wait_for_timeout(150)

    return {
        "url": url,
        "httpStatus": status,
        "confirmed": False,
        "finalUrl": page.url,
        "bodySample": last_text[:500],
    }


async def check_candidate(context, row, semaphore, generated_at):
    async with semaphore:
        page = await context.new_page()
        attempts = []
        hit = None
        started = time.perf_counter()
        try:
            for url in detail_urls(row):
                result = await rendered_probe(page, url)
                attempts.append(result)
                if result.get("confirmed") is True:
                    hit = result
                    break
        finally:
            await page.close()

        record = {
            "id": row.get("id"),
            "houseId": row.get("houseId"),
            "title": row.get("title"),
            "road": row.get("road"),
            "lastSeenAt": row.get("lastSeenAt"),
            "checkedAt": generated_at,
            "attempts": attempts,
            "elapsedSeconds": round(time.perf_counter() - started, 3),
        }
        if hit:
            record.update({
                "confirmedInactive": True,
                "confirmedAt": generated_at,
                "evidenceUrl": hit.get("url"),
                "evidenceHttpStatus": hit.get("httpStatus"),
                "evidenceMarker": hit.get("marker"),
                "evidence": hit.get("evidence"),
            })
        else:
            record["confirmedInactive"] = False
        return record


async def run_parallel(candidates, generated_at):
    started = time.perf_counter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
                ),
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                locale="zh-TW",
                timezone_id="Asia/Taipei",
            )

            async def route_handler(route):
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)
            semaphore = asyncio.Semaphore(MAX_PARALLEL)
            records = await asyncio.gather(*[
                check_candidate(context, row, semaphore, generated_at)
                for row in candidates
            ])
            await context.close()
        finally:
            await browser.close()
    return records, round(time.perf_counter() - started, 3)


def main():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates, source_checked_at = candidate_rows(payload)
    generated_at = now_iso()
    records, elapsed = asyncio.run(run_parallel(candidates, generated_at))
    confirmed = [x for x in records if x.get("confirmedInactive") is True]
    uncertain = [x for x in records if x.get("confirmedInactive") is not True]

    result = {
        "previewOnly": True,
        # Keep the established mode token so the conservative apply gate remains unchanged.
        "mode": "rendered_chrome_explicit_591_inactive_marker_v1",
        "executionMode": "parallel_v1",
        "generatedAt": generated_at,
        "sourceDataUpdatedAt": payload.get("updatedAt"),
        "source591CheckedAt": source_checked_at,
        "candidateRule": "active 591 listing whose lastSeenAt is older than latest successful 591 checkedAt",
        "maxCandidates": MAX_CANDIDATES,
        "maxParallel": MAX_PARALLEL,
        "markers": list(MARKERS),
        "candidateCount": len(candidates),
        "checkedCount": len(records),
        "confirmedInactiveCount": len(confirmed),
        "confirmedInactive": confirmed,
        "uncertain": uncertain,
        "elapsedSeconds": elapsed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "candidateCount": result["candidateCount"],
        "confirmedInactiveCount": result["confirmedInactiveCount"],
        "confirmedIds": sorted(str(x.get("id")) for x in confirmed if x.get("id")),
        "confirmedMarkers": [x.get("evidenceMarker") for x in confirmed],
        "elapsedSeconds": result["elapsedSeconds"],
        "executionMode": result["executionMode"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
