"""Probe whether recom_community causes unstable/promoted rows in legacy 591 API.

Compares recom_community=1 vs 0 for all seven roads, repeating each page-1 request twice.
No canonical data is mutated.
"""
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-recommendation-noise-report.json")


def set_param(url, key, value):
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q[key] = str(value)
    q["timestamp"] = str(int(time.time() * 1000))
    return urlunparse(p._replace(query=urlencode(q)))


async def fetch_json(context, url, road):
    r = await context.request.get(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://m.591.com.tw/",
            "Origin": "https://m.591.com.tw",
        },
        timeout=20000,
    )
    if r.status != 200:
        raise RuntimeError(f"{road} HTTP {r.status}")
    payload = await r.json()
    rows, raw_count = core.parse_591_api_payload(payload, road)
    total_rows = int(payload.get("totalRows") or 0) if isinstance(payload, dict) else 0
    data = payload.get("data") if isinstance(payload, dict) else None
    raw_items = data if isinstance(data, list) else []
    return {
        "http": r.status,
        "totalRows": total_rows,
        "rawCount": raw_count,
        "exactCount": len(rows),
        "ids": sorted(x["id"] for x in rows),
        "newhouseRawCount": sum(1 for x in raw_items if isinstance(x, dict) and x.get("is_newhouse") == 1),
        "recommendListCount": len(payload.get("recommendList") or []) if isinstance(payload, dict) and isinstance(payload.get("recommendList"), list) else None,
        "dataRawLen": len(raw_items),
    }


async def probe_road(browser, road, sid):
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        viewport={"width":390,"height":844},
        is_mobile=True,
        has_touch=True,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )
    page = await context.new_page()
    await page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image","font","media"}
        else route.continue_(),
    )
    captured=[]
    def on_response(response):
        u=response.url
        if response.status==200 and (
            monitor_fast.API_591_V1 in u
            or (monitor_fast.API_591_V2 in u and "action=list" in u)
        ):
            captured.append(u)
    page.on("response",on_response)

    try:
        await page.goto(core.build_591_page_url(road,sid),wait_until="domcontentloaded",timeout=20000)
        for _ in range(30):
            if captured:
                break
            await page.wait_for_timeout(250)
        if not captured:
            raise RuntimeError(f"{road}: no captured template")

        base = monitor_fast.build_api_url(captured[-1],sid,0,1)
        runs={}
        for flag in ("1","0"):
            vals=[]
            for n in range(2):
                url=set_param(base,"recom_community",flag)
                vals.append(await fetch_json(context,url,road))
                await asyncio.sleep(0.25)
            runs[flag]=vals

        return {
            "road":road,
            "streetId":sid,
            "capturedHadRecomCommunity": dict(parse_qsl(urlparse(captured[-1]).query,keep_blank_values=True)).get("recom_community"),
            "recom1":runs["1"],
            "recom0":runs["0"],
            "recom1Stable":runs["1"][0]["ids"]==runs["1"][1]["ids"],
            "recom0Stable":runs["0"][0]["ids"]==runs["0"][1]["ids"],
            "recom0Vs1FirstOnly":sorted(set(runs["0"][0]["ids"])-set(runs["1"][0]["ids"])),
            "recom1Vs0FirstOnly":sorted(set(runs["1"][0]["ids"])-set(runs["0"][0]["ids"])),
        }
    finally:
        await context.close()


async def main_async():
    started=time.perf_counter()
    async with async_playwright() as p:
        browser=await monitor_fast.launch_591_browser(p)
        try:
            results=await asyncio.gather(*[
                probe_road(browser,road,sid)
                for road,sid in core.WATCH_591_STREETS.items()
            ])
        finally:
            await browser.close()
    report={
        "mode":"591_recom_community_noise_probe_v1",
        "elapsedSeconds":round(time.perf_counter()-started,3),
        "roads":results,
        "recom1StableRoads":sum(1 for x in results if x["recom1Stable"]),
        "recom0StableRoads":sum(1 for x in results if x["recom0Stable"]),
        "roadsWithSetDifference":sum(1 for x in results if x["recom0Vs1FirstOnly"] or x["recom1Vs0FirstOnly"]),
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "elapsedSeconds":report["elapsedSeconds"],
        "recom1StableRoads":report["recom1StableRoads"],
        "recom0StableRoads":report["recom0StableRoads"],
        "roadsWithSetDifference":report["roadsWithSetDifference"],
        "roads":[
            {
                "road":x["road"],
                "recom1":x["recom1"],
                "recom0":x["recom0"],
                "r1Only":x["recom1Vs0FirstOnly"],
                "r0Only":x["recom0Vs1FirstOnly"],
            }
            for x in results
        ],
    },ensure_ascii=False))

asyncio.run(main_async())
