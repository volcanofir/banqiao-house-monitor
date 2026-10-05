"""Inspect the legacy 591 mobile API first-page wrapper for pagination metadata.

No canonical files are changed.
"""
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import monitor_fast
import monitor_pages as core

OUT = Path("artifacts/591-mobile-shape.json")


async def inspect():
    road, sid = next(iter(core.WATCH_591_STREETS.items()))
    async with async_playwright() as p:
        browser = await monitor_fast.launch_591_browser(p)
        try:
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
            captured = []
            def on_response(response):
                u=response.url
                if response.status==200 and (
                    monitor_fast.API_591_V1 in u
                    or (monitor_fast.API_591_V2 in u and "action=list" in u)
                ):
                    captured.append(u)
            page.on("response", on_response)

            bootstrap=core.build_591_page_url(road,sid)
            await page.goto(bootstrap,wait_until="domcontentloaded",timeout=20000)
            for _ in range(30):
                if captured:
                    break
                await page.wait_for_timeout(250)
            if not captured:
                raise RuntimeError("no 591 legacy API captured")

            api_url=monitor_fast.build_api_url(captured[-1],sid,0,1)
            response=await context.request.get(
                api_url,
                headers={
                    "Accept":"application/json, text/plain, */*",
                    "Referer":"https://m.591.com.tw/",
                    "Origin":"https://m.591.com.tw",
                },
                timeout=20000,
            )
            payload=await response.json()
            data=payload.get("data") if isinstance(payload,dict) else None
            report={
                "road":road,
                "http":response.status,
                "apiHost":urlparse(api_url).netloc,
                "topKeys":sorted(payload.keys()) if isinstance(payload,dict) else [],
                "topScalar":{k:v for k,v in payload.items() if isinstance(v,(str,int,float,bool,type(None)))} if isinstance(payload,dict) else {},
                "dataType":type(data).__name__,
                "dataKeys":sorted(data.keys()) if isinstance(data,dict) else [],
                "dataScalar":{k:v for k,v in data.items() if isinstance(v,(str,int,float,bool,type(None)))} if isinstance(data,dict) else {},
            }
            for key in ("total","totalCount","total_count","count","pageCount","page_count","lastPage","last_page","page","newPage","newPageSize"):
                if isinstance(payload,dict) and key in payload:
                    report[f"top.{key}"]=payload[key]
                if isinstance(data,dict) and key in data:
                    report[f"data.{key}"]=data[key]
            OUT.parent.mkdir(parents=True,exist_ok=True)
            OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(report,ensure_ascii=False))
            await context.close()
        finally:
            await browser.close()

asyncio.run(inspect())
