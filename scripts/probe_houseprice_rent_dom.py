import json
from playwright.sync_api import sync_playwright

URL="https://rent.houseprice.tw/list/21_usage/15_zip/%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5_kw/?p=1"

with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome",headless=True,args=["--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei",viewport={"width":1280,"height":1200})
    page=ctx.new_page()
    hits=[]
    def on_response(resp):
        if "houseprice.tw" in resp.url and any(k in resp.url.lower() for k in ["api","list","search"]):
            try:
                ct=(resp.headers.get("content-type") or "")
            except Exception:
                ct=""
            hits.append({"url":resp.url,"status":resp.status,"ct":ct})
    page.on("response",on_response)
    r=page.goto(URL,wait_until="domcontentloaded",timeout=90000)
    page.wait_for_timeout(6000)
    anchors=page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a=>({
      href:a.href,
      text:(a.innerText||'').replace(/\\s+/g,' ').trim(),
      parent:(a.parentElement?.innerText||'').replace(/\\s+/g,' ').trim()
    })).filter(x=>x.href.includes('rent.houseprice.tw')).slice(0,300)""")
    body=page.locator("body").inner_text()
    print(json.dumps({
      "http":r.status if r else None,
      "title":page.title(),
      "bodyPrefix":body[:5000],
      "anchors":anchors,
      "responses":hits[-100:]
    },ensure_ascii=False))
    browser.close()
