"""Diagnostic: inspect one rendered Rakuya detail page for publication metadata.

Writes docs/preview/rakuya-publish-probe.json only. No production data mutation.
"""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL="https://www.rakuya.com.tw/sell_item/info?ehid=014c7635624974c"
OUT=Path("docs/preview/rakuya-publish-probe.json")
DATE_RE=re.compile(r"(?<!\d)(?:1\d{2}|20\d{2})[./-]\d{1,2}[./-]\d{1,2}(?!\d)")
KEY_RE=re.compile(r"(?:刊登|上架|發佈|發布|publish|posted|created|createTime|datePublished|uploadDate|online|startTime)",re.I)

def contexts(text,limit=120):
    hits=[]
    seen=set()
    for m in list(KEY_RE.finditer(text))+list(DATE_RE.finditer(text)):
        s=" ".join(text[max(0,m.start()-220):min(len(text),m.end()+320)].split())
        if s and s not in seen:
            seen.add(s); hits.append(s)
        if len(hits)>=limit: break
    return hits

def main():
    result={"url":URL,"network":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        context=browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei")
        page=context.new_page()
        seen=set()
        def record(req):
            u=req.url
            if u in seen: return
            seen.add(u)
            if req.resource_type in {"xhr","fetch","document","script"} or "/api/" in u:
                result["network"].append({"type":req.resource_type,"method":req.method,"url":u})
        page.on("request",record)
        resp=page.goto(URL,wait_until="domcontentloaded",timeout=45000)
        result["httpStatus"]=resp.status if resp else None
        page.wait_for_timeout(9000)
        body=page.locator("body").inner_text(timeout=10000)
        html=page.content()
        result["title"]=page.title()
        result["bodyContexts"]=contexts(body)
        result["htmlContexts"]=contexts(html)
        result["bodyDates"]=DATE_RE.findall(body)[:200]
        result["htmlDates"]=DATE_RE.findall(html)[:200]
        result["scriptSrcs"]=page.locator("script[src]").evaluate_all("els => els.map(e => e.src)")
        result["performance"]=page.evaluate("""() => performance.getEntriesByType('resource').map(e=>({name:e.name,initiatorType:e.initiatorType})).filter(e=>['fetch','xmlhttprequest','script'].includes(e.initiatorType))""")
        result["globals"]=page.evaluate("""() => Object.keys(window).filter(k=>/sell|house|item|detail|estate/i.test(k)).slice(0,200)""")
        browser.close()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"network":len(result["network"]),"bodyDates":result["bodyDates"][:30],"contexts":result["bodyContexts"][:10]},ensure_ascii=False))

if __name__=="__main__":
    main()
