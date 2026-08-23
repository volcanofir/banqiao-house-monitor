"""Probe public structured fields in 591 list API for scheme A medium-risk groups.

Diagnostic only. Uses the same official/public 591 list flow as the monitor and writes
only selected non-sensitive listing fields. Does not modify docs/data/listings.json.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

import monitor_fast as fast
import monitor_pages as core

AUDIT = Path("docs/preview/scheme-a-weak-group-audit.json")
GAP = Path("docs/preview/company-gap.json")
OUT = Path("docs/preview/591-medium-field-probe.json")

SAFE_KEY_RE = re.compile(
    r"(floor|room|layout|community|comm|building|address|street|road|section|type|kind|"
    r"age|lat|lng|lon|price|area|ping|house|post|title|name|parking|direction|face)", re.I
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def target_ids():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    gap = json.loads(GAP.read_text(encoding="utf-8"))
    mids = {x.get("groupId") for x in audit.get("groups", []) if x.get("risk") == "medium"}
    ids = set()
    group_meta = {}
    for g in gap.get("propertyGroups") or []:
        gid = g.get("groupId")
        if gid not in mids:
            continue
        members = []
        for src in g.get("sourceListings") or []:
            cands = src.get("mergedListings") or [src]
            for x in cands:
                rid = str(x.get("id") or "")
                if rid.startswith("591:"):
                    pid = rid.split(":", 1)[1]
                    ids.add(pid)
                    members.append(pid)
        group_meta[gid] = {
            "road": g.get("road"),
            "title": g.get("title"),
            "memberIds": sorted(set(members)),
        }
    return ids, group_meta


def scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def project(item):
    out = {}
    for k, v in item.items():
        if not SAFE_KEY_RE.search(str(k)):
            continue
        if scalar(v):
            s = str(v)
            if len(s) <= 240:
                out[str(k)] = v
        elif isinstance(v, dict):
            compact = {}
            for kk, vv in v.items():
                if SAFE_KEY_RE.search(str(kk)) and scalar(vv) and len(str(vv)) <= 240:
                    compact[str(kk)] = vv
            if compact:
                out[str(k)] = compact
    return out


def item_post_id(item):
    raw = str(item.get("post_id") or item.get("postId") or item.get("houseid") or item.get("houseId") or "")
    m = re.search(r"(\d{6,})", raw)
    return m.group(1) if m else ""


async def fetch_road(browser, road, street_id, wanted):
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )
    page = await context.new_page()
    captured = []
    def on_response(resp):
        if resp.status == 200 and (fast.API_591_V1 in resp.url or (fast.API_591_V2 in resp.url and "action=list" in resp.url)):
            captured.append(resp.url)
    page.on("response", on_response)
    rows = {}
    pages = 0
    try:
        await page.goto(core.build_591_page_url(road, street_id), wait_until="domcontentloaded", timeout=25000)
        for _ in range(24):
            if captured:
                break
            await page.wait_for_timeout(250)
        if not captured:
            return {"ok": False, "error": "no list API captured", "pages": 0, "rows": {}}
        template = captured[-1]
        for page_no in range(1, 11):
            url = fast.build_api_url(template, street_id, (page_no - 1) * 30, page_no)
            resp = await context.request.get(url, headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://m.591.com.tw/",
                "Origin": "https://m.591.com.tw",
            }, timeout=15000)
            if resp.status != 200:
                return {"ok": False, "error": f"HTTP {resp.status} page {page_no}", "pages": pages, "rows": rows}
            payload = await resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                data = data.get("items") or data.get("list") or data.get("data") or []
            if not isinstance(data, list):
                data = []
            pages += 1
            for item in data:
                if not isinstance(item, dict):
                    continue
                pid = item_post_id(item)
                if pid in wanted:
                    rows[pid] = {
                        "keys": sorted(map(str, item.keys())),
                        "fields": project(item),
                    }
            if len(data) < 30:
                break
        return {"ok": True, "pages": pages, "rows": rows}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "pages": pages, "rows": rows}
    finally:
        await context.close()


async def main_async():
    wanted, groups = target_ids()
    report = {
        "capturedAt": now_iso(),
        "previewOnly": True,
        "targetGroupCount": len(groups),
        "target591IdCount": len(wanted),
        "groups": groups,
        "roads": {},
        "matchedIds": [],
        "missingIds": [],
        "fieldNameCounts": {},
    }
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        try:
            tasks = [fetch_road(browser, road, sid, wanted) for road, sid in core.WATCH_591_STREETS.items()]
            results = await asyncio.gather(*tasks)
            matched = set()
            counts = {}
            for (road, _), result in zip(core.WATCH_591_STREETS.items(), results):
                report["roads"][road] = result
                for pid, rec in (result.get("rows") or {}).items():
                    matched.add(pid)
                    for k in (rec.get("fields") or {}).keys():
                        counts[k] = counts.get(k, 0) + 1
            report["matchedIds"] = sorted(matched)
            report["missingIds"] = sorted(wanted - matched)
            report["fieldNameCounts"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
            report["complete"] = all((x or {}).get("ok") for x in report["roads"].values()) and not report["missingIds"]
        finally:
            await browser.close()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "targetGroupCount": report["targetGroupCount"],
        "target591IdCount": report["target591IdCount"],
        "matched": len(report["matchedIds"]),
        "missing": len(report["missingIds"]),
        "complete": report["complete"],
        "fieldNameCounts": report["fieldNameCounts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main_async())
