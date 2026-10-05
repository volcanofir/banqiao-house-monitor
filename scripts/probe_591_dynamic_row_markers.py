"""Inspect unstable/dynamic rows in the legacy 591 mobile API.

Fetch selected pages three times in core mode, find IDs that are not present in all
three responses, and dump their raw fields alongside stable rows for comparison.
No canonical data is mutated.
"""
import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-dynamic-row-markers.json")
TARGETS = [
    ("板橋區中山路二段", core.WATCH_591_STREETS["板橋區中山路二段"], 2),
    ("板橋區三民路二段", core.WATCH_591_STREETS["板橋區三民路二段"], 2),
    ("板橋區光復街", core.WATCH_591_STREETS["板橋區光復街"], 1),
    ("板橋區三民路一段", core.WATCH_591_STREETS["板橋區三民路一段"], 1),
]


def norm(v):
    return "" if v is None else str(v).strip()


def id_of(item):
    if not isinstance(item, dict):
        return ""
    for key in ("post_id", "postId", "houseid", "houseId", "id"):
        v = norm(item.get(key))
        m = re.search(r"(\d{6,})", v)
        if m:
            return m.group(1)
    return ""


def force_core(url):
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["recom_community"] = "0"
    q["timestamp"] = str(int(time.time() * 1000))
    return urlunparse(p._replace(query=urlencode(q)))


async def capture(browser, road, sid):
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width":390,"height":844},
        is_mobile=True,has_touch=True,locale="zh-TW",timezone_id="Asia/Taipei",
    )
    page = await context.new_page()
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image","font","media"} else route.continue_())
    captured=[]
    page.on("response", lambda response: captured.append(response.url) if response.status==200 and (
        monitor_fast.API_591_V1 in response.url or (monitor_fast.API_591_V2 in response.url and "action=list" in response.url)
    ) else None)
    await page.goto(core.build_591_page_url(road,sid),wait_until="domcontentloaded",timeout=20000)
    for _ in range(30):
        if captured: break
        await page.wait_for_timeout(250)
    if not captured:
        await context.close()
        raise RuntimeError(f"{road}: no template")
    await page.close()
    return context, captured[-1]


async def fetch_page(context, template, sid, page_no):
    first_row=(page_no-1)*30
    url=force_core(monitor_fast.build_api_url(template,sid,first_row,page_no))
    response=await context.request.get(url,headers={
        "Accept":"application/json, text/plain, */*",
        "Referer":"https://m.591.com.tw/",
        "Origin":"https://m.591.com.tw",
    },timeout=20000)
    if response.status!=200:
        raise RuntimeError(f"HTTP {response.status}")
    payload=await response.json()
    data=payload.get("data") if isinstance(payload,dict) else None
    rows=data if isinstance(data,list) else []
    return payload, rows


def raw_summary(item,index):
    if not isinstance(item,dict):
        return {"index":index,"value":item}
    selected={}
    for k,v in item.items():
        kl=k.lower()
        if (
            k in {
                "post_id","postId","houseid","houseId","id","title","address","address_new",
                "region","region_name","section","section_name","street_name","type","kind",
                "is_newhouse","is_full","label","company","role_name","posttime","refreshtime",
                "price","total_price","area","area_str","floor","floor_str","is_pro_advertisement"
            }
            or "recommend" in kl
            or "advert" in kl
            or "promot" in kl
            or "sponsor" in kl
            or "source" in kl
        ):
            selected[k]=v
    return {
        "index":index,
        "id":id_of(item),
        "selected":selected,
        "allKeys":sorted(item.keys()),
    }


async def inspect_target(browser, road, sid, page_no):
    context,template=await capture(browser,road,sid)
    try:
        runs=[]
        raw_by_id={}
        for rep in range(3):
            payload,rows=await fetch_page(context,template,sid,page_no)
            ids=[]
            for idx,item in enumerate(rows):
                rid=id_of(item)
                if rid:
                    ids.append(rid)
                    raw_by_id.setdefault(rid,[]).append(raw_summary(item,idx))
            runs.append({
                "totalRows":int(payload.get("totalRows") or 0),
                "rawLen":len(rows),
                "ids":ids,
            })
            await asyncio.sleep(0.3)

        sets=[set(x["ids"]) for x in runs]
        stable=set.intersection(*sets) if sets else set()
        union=set.union(*sets) if sets else set()
        dynamic=sorted(union-stable)
        return {
            "road":road,
            "page":page_no,
            "runs":runs,
            "stableCount":len(stable),
            "dynamicIds":dynamic,
            "dynamicRows":{rid:raw_by_id.get(rid,[]) for rid in dynamic},
            "stableSamples":{
                rid:raw_by_id[rid][:1]
                for rid in sorted(stable)[:5]
            },
        }
    finally:
        await context.close()


async def main():
    async with async_playwright() as p:
        browser=await monitor_fast.launch_591_browser(p)
        try:
            results=[]
            for road,sid,page_no in TARGETS:
                results.append(await inspect_target(browser,road,sid,page_no))
        finally:
            await browser.close()
    report={"mode":"591_dynamic_row_marker_probe_v1","targets":results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "targets":[
            {
                "road":x["road"],
                "page":x["page"],
                "runs":[{"totalRows":r["totalRows"],"rawLen":r["rawLen"],"ids":r["ids"]} for r in x["runs"]],
                "dynamicIds":x["dynamicIds"],
                "dynamicRows":x["dynamicRows"],
            }
            for x in results
        ]
    },ensure_ascii=False))

asyncio.run(main())
