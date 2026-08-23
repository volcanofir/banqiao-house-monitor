"""Record a PREVIEW-only Yongching HAR for API discovery.

The HAR itself is intentionally kept out of git and uploaded only as a short-lived
GitHub Actions artifact. A sanitized JSON summary is written to docs/preview so we can
inspect endpoint shapes without persisting cookies, authorization headers or bodies.
This file is also the explicit push trigger for the isolated HAR diagnostic workflow.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as base


OUT_DIR = Path("artifacts/yungching-har")
HAR_PATH = OUT_DIR / "yungching-network.har"
SUMMARY_PATH = Path("docs/preview/yungching-har-summary.json")
SNAPSHOT_PATH = Path("docs/preview/yungching-browser-snapshot.json")
ROAD = "板橋區中山路二段"


def pg_url(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "pg"]
    query.append(("pg", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def sanitized_url(url: str) -> dict:
    try:
        parts = urlsplit(url)
        keys = sorted({k for k, _ in parse_qsl(parts.query, keep_blank_values=True)})
        return {
            "origin": f"{parts.scheme}://{parts.netloc}",
            "path": parts.path,
            "queryKeys": keys,
        }
    except Exception:
        return {"origin": None, "path": str(url)[:300], "queryKeys": []}


def detail_from_snapshot():
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    for row in snap.get("listings") or []:
        if row.get("road") == ROAD and row.get("id"):
            return f"{base.BASE}/house/{row['id']}"
    return None


def summarize_har(path: Path, navigation: dict) -> dict:
    har = json.loads(path.read_text(encoding="utf-8"))
    entries = ((har.get("log") or {}).get("entries") or [])
    endpoints = {}
    for e in entries:
        req = e.get("request") or {}
        resp = e.get("response") or {}
        url = str(req.get("url") or "")
        safe = sanitized_url(url)
        key = (
            str(req.get("method") or "GET"),
            safe.get("origin"), safe.get("path"), tuple(safe.get("queryKeys") or []),
            str(e.get("_resourceType") or ""),
        )
        item = endpoints.setdefault(key, {
            "method": key[0],
            "origin": key[1],
            "path": key[2],
            "queryKeys": list(key[3]),
            "resourceType": key[4] or None,
            "count": 0,
            "statuses": set(),
            "mimeTypes": set(),
        })
        item["count"] += 1
        status = resp.get("status")
        if status is not None:
            item["statuses"].add(status)
        mime = ((resp.get("content") or {}).get("mimeType"))
        if mime:
            item["mimeTypes"].add(mime)

    rows = []
    for item in endpoints.values():
        item["statuses"] = sorted(item["statuses"])
        item["mimeTypes"] = sorted(item["mimeTypes"])
        rows.append(item)

    def importance(x):
        rt = str(x.get("resourceType") or "").lower()
        mime = " ".join(x.get("mimeTypes") or []).lower()
        path_text = str(x.get("path") or "").lower()
        score = 0
        if rt in {"xhr", "fetch"}: score += 20
        if "json" in mime: score += 15
        if any(k in path_text for k in ("api", "search", "list", "house", "buy", "mansion")): score += 5
        if x.get("origin") == "https://buy.yungching.com.tw": score += 3
        return (-score, x.get("origin") or "", x.get("path") or "")

    rows.sort(key=importance)
    candidate = [x for x in rows if (
        str(x.get("resourceType") or "").lower() in {"xhr", "fetch"}
        or any("json" in m.lower() for m in (x.get("mimeTypes") or []))
    )]
    return {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "road": ROAD,
        "harStoredInGit": False,
        "harArtifactName": "yungching-network-har",
        "requestEntryCount": len(entries),
        "uniqueEndpointShapeCount": len(rows),
        "navigation": navigation,
        "candidateApiEndpointCount": len(candidate),
        "candidateApiEndpoints": candidate[:120],
        "allEndpointShapes": rows[:250],
        "privacy": "summary excludes request/response headers, cookies, query values and request bodies",
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    navigation = {"page1": {}, "page2": {}, "detail": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            record_har_path=str(HAR_PATH),
            record_har_mode="full",
            record_har_content="embed",
        )
        page = context.new_page()

        page1 = base.road_url(ROAD)
        r1 = page.goto(page1, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)
        navigation["page1"] = {
            "url": sanitized_url(page.url),
            "http": r1.status if r1 else None,
            "title": page.title()[:160],
        }

        page2 = pg_url(page1, 2)
        r2 = page.goto(page2, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)
        active2 = page.locator(".paginationPageListItem.actived, .paginationPageListItem.active")
        navigation["page2"] = {
            "url": sanitized_url(page.url),
            "http": r2.status if r2 else None,
            "activePagerText": active2.first.inner_text(timeout=2000).strip() if active2.count() else None,
        }

        detail_link = None
        links = page.locator('a[href*="/house/"]')
        for i in range(min(links.count(), 80)):
            href = links.nth(i).get_attribute("href")
            if href and "/house/" in href:
                detail_link = href
                break
        detail_source = "page2-anchor"
        if not detail_link:
            detail_link = detail_from_snapshot()
            detail_source = "verified-snapshot-fallback"
        if detail_link:
            if detail_link.startswith("/"):
                detail_link = base.BASE + detail_link
            rd = page.goto(detail_link, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4500)
            navigation["detail"] = {
                "url": sanitized_url(page.url),
                "http": rd.status if rd else None,
                "title": page.title()[:160],
                "source": detail_source,
            }
        else:
            navigation["detail"] = {"error": "no /house/ link and no verified snapshot fallback"}

        context.close()
        browser.close()

    if not HAR_PATH.exists() or HAR_PATH.stat().st_size < 1000:
        raise RuntimeError(f"HAR was not created or is unexpectedly small: {HAR_PATH}")

    summary = summarize_har(HAR_PATH, navigation)
    summary["harBytes"] = HAR_PATH.stat().st_size
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "harBytes": summary["harBytes"],
        "requestEntryCount": summary["requestEntryCount"],
        "candidateApiEndpointCount": summary["candidateApiEndpointCount"],
        "page1": navigation["page1"],
        "page2": navigation["page2"],
        "detail": navigation["detail"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
