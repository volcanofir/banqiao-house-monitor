"""Preview-only rendered-browser confirmation for stale 591 sale listings.

This does not mutate docs/data/listings.json. It only inspects active 591 rows that were
not seen in the latest completed 591 crawl, opens their detail pages in real Chrome,
and records explicit rendered evidence such as `不存在此物件`.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SOURCE = Path("docs/data/listings.json")
OUT = Path("docs/preview/591-offmarket-probe.json")
MAX_CANDIDATES = 40
STALE_GRACE_SECONDS = 60
POLL_SECONDS = 3.4

# Keep this conservative: only explicit 591 invalid/off-market wording counts.
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
        # This is the URL shape that currently shows the rendered `不存在此物件` toast.
        urls.append(f"https://sale.591.com.tw/home/house/detail/2/{house_id}.html")
        urls.append(f"https://m.591.com.tw/v2/sale/{house_id}")
    if row.get("url"):
        urls.append(str(row.get("url")))
    return list(dict.fromkeys(urls))


def rendered_probe(page, url):
    status = None
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=18000)
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
            text = page.locator("body").inner_text(timeout=1000)
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
        page.wait_for_timeout(150)

    return {
        "url": url,
        "httpStatus": status,
        "confirmed": False,
        "finalUrl": page.url,
        "bodySample": last_text[:500],
    }


def main():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates, source_checked_at = candidate_rows(payload)
    generated_at = now_iso()
    confirmed = []
    uncertain = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
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
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font"}
            else route.continue_(),
        )

        for row in candidates:
            page = context.new_page()
            attempts = []
            hit = None
            try:
                for url in detail_urls(row):
                    result = rendered_probe(page, url)
                    attempts.append(result)
                    if result.get("confirmed") is True:
                        hit = result
                        break
            finally:
                page.close()

            record = {
                "id": row.get("id"),
                "houseId": row.get("houseId"),
                "title": row.get("title"),
                "road": row.get("road"),
                "lastSeenAt": row.get("lastSeenAt"),
                "checkedAt": generated_at,
                "attempts": attempts,
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
                confirmed.append(record)
            else:
                record["confirmedInactive"] = False
                uncertain.append(record)

        browser.close()

    result = {
        "previewOnly": True,
        "mode": "rendered_chrome_explicit_591_inactive_marker_v1",
        "generatedAt": generated_at,
        "sourceDataUpdatedAt": payload.get("updatedAt"),
        "source591CheckedAt": source_checked_at,
        "candidateRule": "active 591 listing whose lastSeenAt is older than latest successful 591 checkedAt",
        "maxCandidates": MAX_CANDIDATES,
        "markers": list(MARKERS),
        "candidateCount": len(candidates),
        "checkedCount": len(confirmed) + len(uncertain),
        "confirmedInactiveCount": len(confirmed),
        "confirmedInactive": confirmed,
        "uncertain": uncertain,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "candidateCount": result["candidateCount"],
        "confirmedInactiveCount": result["confirmedInactiveCount"],
        "confirmedIds": [x.get("id") for x in confirmed],
        "confirmedMarkers": [x.get("evidenceMarker") for x in confirmed],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
