"""Read-only comparison of user-provided 591 Banqiao street page=1/2 URLs.

Uses ordinary mobile-homepage navigation and the exact publicly supplied search
URLs, logs only aggregate listing counts and ID overlap, never IDs, auth, bodies
or listing details. No persistent data writes.
"""
import asyncio
from urllib.parse import urlencode, urlsplit, parse_qs
from playwright.async_api import async_playwright

HOME = "https://m.591.com.tw/v2/"
BASE = "https://sale.591.com.tw/"
PARAMS = {
    "keywords": "中山路二段",
    "regionid": "3",
    "section": "26",
    "streetid": "27507",
    "firstRow": "0",
    "page": "1",
    "shType": "list",
    "itm_source": "main",
    "itm_medium": "home",
    "itm_campaign": "prime_position",
    "itm_content": "sale",
    "type": "2",
}
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

def public_path(url):
    x=urlsplit(url)
    return f"{x.netloc}{x.path} query_keys={','.join(sorted(parse_qs(x.query))) or '-'}"

async def check(browser):
    context=await browser.new_context(
        user_agent=UA, viewport={"width":390, "height":844},
        is_mobile=True, has_touch=True, locale="zh-TW", timezone_id="Asia/Taipei"
    )
    try:
        page=await context.new_page()
        respmeta=[]
        def on_response(res):
            x=urlsplit(res.url)
            if x.hostname=="bff-house.591.com.tw" and (
                "sale/list" in x.path or "touch/sale/list" in x.path
            ):
                respmeta.append((res.status, x.netloc+x.path, ",".join(sorted(parse_qs(x.query)))))
        page.on("response",on_response)
        results=[]
        try:
            r=await page.goto(HOME,wait_until="domcontentloaded",timeout=24000)
            print("entry_home_http=",r.status if r else "none")
            await page.wait_for_timeout(1200)
            sale_link=page.get_by_role("link",name="中古屋")
            if await sale_link.count()==1:
                try:
                    await sale_link.click(timeout=5000)
                    await page.wait_for_timeout(2500)
                    print("natural_sale_navigation=",public_path(page.url))
                except Exception as e:
                    print("natural_sale_navigation_error=",type(e).__name__)
            else:
                print("natural_sale_link_count=",await sale_link.count())
        except Exception as e:
            print("entry_home_error=",type(e).__name__)
        for pn in (1,2):
            params=dict(PARAMS,page=str(pn))
            url=BASE+"?"+urlencode(params)
            meta_before=len(respmeta)
            try:
                r=await page.goto(url,wait_until="domcontentloaded",timeout=24000)
                status=r.status if r else None
                await page.wait_for_timeout(2200)
                if status==200:
                    summary=await page.evaluate("""() => {
                        const unwrap = x => x && x.__v_isRef ? x.value : x;
                        const s=window.__NUXT__?.pinia?.['sale-list'];
                        const list=unwrap(s?.wareList);
                        const params=unwrap(s?.searchParams);
                        const total=unwrap(s?.wareTotal);
                        const ids=Array.isArray(list)?list.map(x=>String(x.houseid||x.post_id||x.id||'')).filter(Boolean):[];
                        return {
                            hasState:!!s,
                            count:Array.isArray(list)?list.length:null,
                            idCount:ids.length,
                            ids:ids,
                            totalType:typeof total,
                            totalNumber:typeof total==='number'?total:null,
                            firstRow:params?.firstRow??null,
                            page:params?.page??null,
                            streetid:params?.streetid??null,
                            regionid:params?.regionid??null,
                            keywordMatches: typeof params?.keywords === 'string' ? params.keywords.includes('中山路二段') : null
                        };
                    }""")
                    ids=set(summary.pop("ids"))
                else:
                    summary={"hasState":False}
                    ids=set()
                results.append((pn,status,summary,ids))
                print(f"page{pn}_http={status} final={public_path(page.url)} state={summary}")
                print(f"page{pn}_api_metadata={respmeta[meta_before:][:8]}")
            except Exception as e:
                print(f"page{pn}_error={type(e).__name__}")
                results.append((pn,None,{},set()))
        if len(results)==2:
            a,b=results
            print(f"COMPARE valid_id_count_page1={len(a[3])} page2={len(b[3])} intersection={len(a[3]&b[3])} identical={bool(a[3]) and a[3]==b[3]}")
        print("READ_ONLY no listing values or IDs logged or persisted; no credentials collected")
    finally:
        await context.close()

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True,args=["--disable-dev-shm-usage"])
        try: await check(browser)
        finally: await browser.close()

if __name__=="__main__":
    asyncio.run(main())
