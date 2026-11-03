"""One-time, read-only 591 HTML listing metadata check for the other six roads.

Visits the public mobile homepage first and the user-style search URL for
each road. Each road checks only the first and last pages, not all listings.
Outputs page status, count, total and ID overlap, never records or IDs.
This is NOT an automated harvesting pipeline and does not update production.
"""
import asyncio
import math
from urllib.parse import urlencode, urlsplit
from playwright.async_api import async_playwright

ROADS = [
    ("三民路二段", "27485"),
    ("光復街", "27550"),
    ("萬安街", "27630"),
    ("林森街", "27574"),
    ("三民路一段", "27484"),
    ("翠華街", "27644"),
]
BASE = "https://sale.591.com.tw/"
HOME = "https://m.591.com.tw/v2/"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

async def fetch_meta(page, road, streetid, offset):
    params = {
        "keywords": road,
        "regionid": "3",
        "section": "26",
        "streetid": streetid,
        "firstRow": str(offset),
        "page": str(offset // 30 + 1),
        "shType": "list",
        "itm_source": "main",
        "itm_medium": "home",
        "itm_campaign": "prime_position",
        "itm_content": "sale",
        "type": "2",
    }
    try:
        response = await page.goto(
            BASE + "?" + urlencode(params),
            wait_until="domcontentloaded",
            timeout=19000,
        )
        code = response.status if response else None
        if code != 200:
            return {"http": code, "ids": set()}
        data = await page.evaluate("""() => {
            const unref=x=>x?.__v_isRef?x.value:x;
            const s=window.__NUXT__?.pinia?.['sale-list'];
            const rows=unref(s?.wareList);
            const total=unref(s?.wareTotal);
            const p=unref(s?.searchParams);
            return {
                count: Array.isArray(rows)?rows.length:null,
                ids: Array.isArray(rows)?rows.map(x=>String(x.houseid||x.post_id||x.id||'')).filter(Boolean):[],
                total: typeof total==="number"?total:null,
                streetid: p?.streetid===undefined?null:String(p.streetid),
                firstRow: p?.firstRow===undefined?null:String(p.firstRow),
                keyword: typeof p?.keywords==="string"?p.keywords:null,
                hasNuxt:!!s
            }
        }""")
        ids = set(data.pop("ids"))
        passed = (data["streetid"] == streetid
                  and data["firstRow"] == str(offset)
                  and data["keyword"] == road
                  and isinstance(data["count"], int))
        return {"http": code, "ids": ids, "params_match": passed, **{k:v for k,v in data.items() if k != "keyword"}}
    except Exception as exc:
        return {"http": None, "ids": set(), "error": type(exc).__name__}


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(
                user_agent=UA, viewport={"width":390,"height":844},
                is_mobile=True, has_touch=True,
                locale="zh-TW", timezone_id="Asia/Taipei"
            )
            try:
                page = await context.new_page()
                try:
                    resp=await page.goto(HOME,wait_until="domcontentloaded",timeout=19000)
                    print(f"HOME_HTTP {resp.status if resp else 'none'}")
                except Exception as exc:
                    print(f"HOME_ERROR {type(exc).__name__}")
                for road, streetid in ROADS:
                    first=await fetch_meta(page,road,streetid,0)
                    total=first.get("total")
                    if not isinstance(total,int) or total <= 0 or total > 5000:
                        print(f"ROAD {road} first_http={first['http']} first_count={first.get('count')} total={total} "
                              f"params_match={first.get('params_match')} status=not_verified")
                        continue
                    pages=math.ceil(total/30)
                    last_offset=(pages-1)*30
                    last=first if last_offset == 0 else await fetch_meta(page,road,streetid,last_offset)
                    overlap=len(first["ids"] & last["ids"]) if last_offset else None
                    print(f"ROAD {road} first_http={first['http']} first_count={first.get('count')} "
                          f"total={total} pages_expected={pages} first_params_match={first.get('params_match')} "
                          f"last_offset={last_offset} last_http={last.get('http')} "
                          f"last_count={last.get('count')} last_params_match={last.get('params_match')} "
                          f"last_total={last.get('total')} first_last_id_overlap={overlap} "
                          f"last_error={last.get('error', 'none')}")
                    await asyncio.sleep(0.8)
                print("READ_ONLY aggregate metadata only, no listing IDs or details logged or stored")
            finally:
                await context.close()
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
