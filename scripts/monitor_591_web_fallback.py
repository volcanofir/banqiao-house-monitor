"""Independent 591 desktop-sale API fallback for failed mobile-list bootstraps.

Fail closed: never return an incomplete page set or a partial road sample as a
successful snapshot. The canonical monitor retains its previous data on failure.
"""
import asyncio
import re
from urllib.parse import urlencode

from playwright.async_api import async_playwright

import monitor_pages as core

WEB_API = "https://bff-house.591.com.tw/v1/web/sale/list"
WEB_ENTRY = "https://sale.591.com.tw/?shType=list&regionid=3&sectionid=26"
PAGE_SIZE = 30
MAX_PAGES = 100
MAX_SOURCE_ROWS = PAGE_SIZE * MAX_PAGES


def normalize_web_sale_item(item):
    """Validate geography and transform a desktop sale item for the proven parser."""
    if not isinstance(item, dict):
        return None
    if item.get("is_newhouse") or str(item.get("type") or "") == "8":
        return None

    address = core.normalize_text(item.get("address") or item.get("address_new") or "")
    region = core.normalize_text(item.get("region_name") or "")
    district = core.normalize_text(item.get("section_name") or item.get("section") or "")
    section_id = str(item.get("section_id") or item.get("sectionid") or "").strip()
    if region and region != "新北市":
        return None
    if district and district != "板橋區":
        return None
    if section_id and section_id != "26":
        return None
    if not (district == "板橋區" or section_id == "26" or "板橋區" in address):
        return None
    if core.has_other_district(address):
        return None

    house_id = str(item.get("houseid") or item.get("post_id") or "").strip()
    match = re.search(r"(\d{6,})", house_id)
    if not match or not address:
        return None

    normalized = dict(item)
    normalized.update({
        "post_id": match.group(1),
        "region": "新北市",
        "section": "板橋區",
        "sectionid": "26",
        "address": address,
        "price": item.get("price"),
        "area": item.get("area"),
        "posttime": item.get("posttime"),
    })
    return normalized


def parse_web_page(payload):
    if not isinstance(payload, dict) or str(payload.get("status")) != "1":
        raise ValueError("591 desktop API did not report status=1")
    body = payload.get("data")
    if not isinstance(body, dict):
        raise ValueError("591 desktop API missing data object")
    items = body.get("house_list")
    if not isinstance(items, list):
        raise ValueError("591 desktop API missing house_list array")
    total = body.get("total")
    if total in (None, ""):
        raise ValueError("591 desktop API missing total row count")
    total = int(total)
    if total < 1 or total > MAX_SOURCE_ROWS:
        raise ValueError(f"591 desktop API unexpected total={total}; refusing partial data")
    return items, total


def filter_monitored_roads(items):
    rows = []
    for item in items:
        normalized = normalize_web_sale_item(item)
        if normalized is None:
            continue
        for road in core.WATCH_591_STREETS:
            matched, _ = core.parse_591_api_payload({"data": [normalized]}, road)
            rows.extend(matched)
    return core.dedupe_by_id(rows)


async def fetch_web_sale_fallback():
    logs = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                channel="chrome", headless=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    locale="zh-TW", timezone_id="Asia/Taipei",
                    viewport={"width": 1366, "height": 768},
                )
                page = await context.new_page()
                try:
                    landing = await page.goto(
                        WEB_ENTRY, wait_until="domcontentloaded", timeout=22000
                    )
                    logs.append(
                        f"591 桌面入口 HTTP {landing.status if landing else 'no-response'}；"
                        f"頁面站台 {page.url.split('/')[2] if '://' in page.url else 'unknown'}"
                    )
                except Exception as exc:
                    logs.append(f"591 桌面入口導航異常：{type(exc).__name__}")

                cookie_names = {c["name"] for c in await context.cookies()}
                logs.append(
                    "591 桌面入口已取得 T591_TOKEN cookie"
                    if "T591_TOKEN" in cookie_names
                    else "591 桌面入口未取得 T591_TOKEN cookie，仍嘗試正式 API"
                )

                total = None
                raw_count = 0
                collected = []
                seen_ids = set()
                for page_no in range(MAX_PAGES):
                    params = {
                        "type": "2", "shType": "list",
                        "regionid": "3", "sectionid": "26",
                        "sectionidStr": "26", "category": "1",
                        "firstRow": str(page_no * PAGE_SIZE),
                        "totalRows": str(total or 0),
                    }
                    url = WEB_API + "?" + urlencode(params)
                    response = await context.request.get(
                        url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Referer": "https://sale.591.com.tw/",
                            "Origin": "https://sale.591.com.tw",
                        },
                        timeout=18000,
                    )
                    if response.status != 200:
                        raise RuntimeError(
                            f"591 desktop API page {page_no + 1} HTTP {response.status}"
                        )
                    try:
                        payload = await response.json()
                    except Exception:
                        raise RuntimeError(
                            f"591 desktop API page {page_no + 1} is not JSON"
                        )
                    items, page_total = parse_web_page(payload)
                    if total is None:
                        total = page_total
                        logs.append(f"591 桌面 API 回報售屋總數 {total}")
                    elif page_total != total:
                        raise RuntimeError(
                            f"591 桌面 API 總數變動 {total} -> {page_total}，不發布不完整資料"
                        )
                    if not items:
                        raise RuntimeError(
                            f"591 desktop API page {page_no + 1} empty before completion"
                        )
                    if len(items) > PAGE_SIZE + 3:
                        raise RuntimeError(
                            f"591 desktop API page {page_no + 1} returned unexpected {len(items)} items"
                        )

                    raw_count += len(items)
                    for row in filter_monitored_roads(items):
                        if row["id"] not in seen_ids:
                            seen_ids.add(row["id"])
                            collected.append(row)
                    scanned = min((page_no + 1) * PAGE_SIZE, total)
                    if page_no == 0 or (page_no + 1) % 10 == 0 or scanned >= total:
                        logs.append(
                            f"591 桌面 API 第 {page_no + 1} 頁："
                            f"{scanned}/{total} 已掃描（API 回傳 {raw_count}），七路段 {len(collected)} 筆"
                        )
                    if scanned >= total:
                        break
                    if len(items) < PAGE_SIZE:
                        raise RuntimeError("591 desktop API premature short page; no snapshot published")
                    if page_no % 8 == 7:
                        await asyncio.sleep(1)
                if scanned < total:
                    raise RuntimeError(
                        f"591 desktop API incomplete: {scanned}/{total}"
                    )
                if not collected:
                    raise RuntimeError(
                        "591 desktop API complete but no monitored-road results"
                    )
                return collected, True, (
                    f"591 桌面售屋 API 備援完成：{scanned}/{total}，
                    f"七路段 {len(collected)} 筆。"
                ), logs
            finally:
                await browser.close()
    except Exception as exc:
        logs.append(f"591 桌面 API 備援失敗：{type(exc).__name__}: {exc}")
        return [], False, "591 桌面 API 備援失敗，保留上一輪資料。", logs


if __name__ == "__main__":
    raise SystemExit("Run through monitor_fast.py; do not publish a partial snapshot.")
