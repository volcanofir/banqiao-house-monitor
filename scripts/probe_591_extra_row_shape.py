"""Inspect raw extra rows beyond 591 legacy API totalRows/page capacity.

No canonical files are changed.
"""
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-extra-row-shape.json")
TARGETS = [
    ("板橋區光復街", core.WATCH_591_STREETS["板橋區光復街"]),
    ("板橋區三民路二段", core.WATCH_591_STREETS["板橋區三民路二段"]),
    ("板橋區中山路二段", core.WATCH_591_STREETS["板橋區中山路二段"]),
]


def set_params(url, **updates):
    p=urlparse(url)
    q=dict(parse_qsl(p.query,keep_blank_values=True))
    for k,v in updates.items():
        q[k]=str(v)
    q["timestamp"]=str(int(time.time()*1000))
    return urlunparse(p._replace(query=urlencode(q)))


def slim(item,index):
    keys=sorted(item.keys()) if isinstance(item,dict) else []
    selected={}
    if isinstance(item,dict):
        for k in keys:
            if (
                k.lower() in {
                    "post_id","postid","houseid","house_id","id","title","address","address_new",
                    "region","region_name","section","section_name","street_name","is_newhouse",
                    "is_recommend","recommend","recommend_type","type","kind","is_full","label",
                    "company","role_name","is_pro_advertisement","sh_type","refreshtime","posttime"
                }
                or "recommend" in k.lower()
                or "advert" in k.lower()
            ):
                selected[k]=item.get(k)
    return {"index":index,"keys":keys,"selected":selected}


async def capture_template(browser,road,sid):
    context=await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width":390,"height":844},
        is_mobile=True,has_touch=True,locale="zh-TW",timezone_id="Asia/Taipei",
    )
    page=await context.new_page()
    await page.route("**/*",lambda route: route.abort() if route.request.resource_type in {"image","font","media"} else route.continue_())
    captured=[]
    page.on("response",lambda response: captured.append(response.url) if response.status==200 and (
        monitor_fast.API_591_V1 in response.url or (monitor_fast.API_591_V2 in response.url and "action=list" in response.url)
    ) else None)
    await page.goto(core.build_591_page_url(road,sid),wait_until="domcontentloaded",timeout=20000)
    for _ in range(30):
        if captured: break
        await page.wait_for_timeout(250)
    if not captured:
        await context.close()
        raise RuntimeError(f"{road}: no template")
    return context,captured[-1]


async def fetch(context,url):
    r=await context.request.get(url,headers={
        "Accept":"application/json, text/plain, */*",
        "Referer":"https://m.591.com.tw/",
        "Origin":"https://m.591.com.tw",
    },timeout=20000)
    if r.status!=200:
        raise RuntimeError(f"HTTP {r.status}")
    return await r.json()


async def inspect_target(browser,road,sid):
    context,template=await capture_template(browser,road,sid)
    try:
        out={"road":road,"runs":[]}
        for rep in range(2):
            base=monitor_fast.build_api_url(template,sid,0,1)
            url=set_params(base,recom_community=0)
            payload=await fetch(context,url)
            total=int(payload.get("totalRows") or 0)
            data=payload.get("data") if isinstance(payload,dict) else None
            rows=data if isinstance(data,list) else []
            expected=min(30,total)
            out["runs"].append({
                "totalRows":total,
                "rawLen":len(rows),
                "expectedCoreOnPage":expected,
                "allRows":[slim(x,i) for i,x in enumerate(rows)],
                "tailBeyondExpected":[slim(x,i) for i,x in enumerate(rows) if i>=expected],
            })
            await asyncio.sleep(0.3)
        return out
    finally:
        await context.close()


async def main():
    async with async_playwright() as p:
        browser=await monitor_fast.launch_591_browser(p)
        try:
            results=[]
            for road,sid in TARGETS:
                results.append(await inspect_target(browser,road,sid))
        finally:
            await browser.close()
    report={"mode":"591_extra_row_shape_probe_v1","targets":results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "targets":[
            {
                "road":x["road"],
                "runs":[
                    {
                        "totalRows":r["totalRows"],
                        "rawLen":r["rawLen"],
                        "expectedCoreOnPage":r["expectedCoreOnPage"],
                        "tailBeyondExpected":[y["selected"] for y in r["tailBeyondExpected"]],
                    } for r in x["runs"]
                ],
            } for x in results
        ]
    },ensure_ascii=False))

asyncio.run(main())
