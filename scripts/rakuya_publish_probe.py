"""Diagnostic: inspect one Rakuya detail page for source publication metadata.

Writes docs/preview/rakuya-publish-probe.json only. No production data mutation.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

URL = "https://www.rakuya.com.tw/sell_item/info?ehid=014c7635624974c"
OUT = Path("docs/preview/rakuya-publish-probe.json")

DATE_RE = re.compile(r"(?<!\d)(?:1\d{2}|20\d{2})[./-]\d{1,2}[./-]\d{1,2}(?!\d)")
KEY_RE = re.compile(r"(?:刊登|上架|發佈|發布|publish|posted|created|createTime|datePublished|uploadDate|online|startTime)", re.I)


def snippets(text, limit=80):
    out=[]
    seen=set()
    for m in list(KEY_RE.finditer(text))[:250] + list(DATE_RE.finditer(text))[:250]:
        a=max(0,m.start()-180); b=min(len(text),m.end()+260)
        s=" ".join(text[a:b].split())
        if s and s not in seen:
            seen.add(s); out.append(s)
        if len(out)>=limit: break
    return out


def main():
    result={"url":URL,"responses":[],"bodySnippets":[],"htmlSnippets":[],"globals":[],"storage":{}}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        context=browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei")
        page=context.new_page()

        def on_response(resp):
            try:
                ctype=(resp.headers or {}).get("content-type","")
                u=resp.url
                if not ("json" in ctype.lower() or resp.request.resource_type in {"xhr","fetch"} or "/api/" in u):
                    return
                txt=resp.text()
                hit=KEY_RE.search(txt) or DATE_RE.search(txt) or "014c7635624974c" in txt
                if not hit:
                    return
                result["responses"].append({
                    "url":u,
                    "status":resp.status,
                    "contentType":ctype,
                    "snippets":snippets(txt,30),
                    "prefix":" ".join(txt[:1200].split()),
                })
            except Exception as exc:
                pass

        page.on("response",on_response)
        resp=page.goto(URL,wait_until="domcontentloaded",timeout=45000)
        result["httpStatus"]=resp.status if resp else None
        page.wait_for_timeout(7000)
        try:
            page.wait_for_load_state("networkidle",timeout=10000)
        except Exception:
            pass
        body=page.locator("body").inner_text(timeout=10000)
        html=page.content()
        result["title"]=page.title()
        result["bodySnippets"]=snippets(body,120)
        result["htmlSnippets"]=snippets(html,120)
        result["bodyDateMatches"]=DATE_RE.findall(body)[:100]
        result["htmlDateMatches"]=DATE_RE.findall(html)[:100]
        result["globals"]=page.evaluate("""() => Object.keys(window).filter(k => /sell|house|item|detail|estate/i.test(k)).slice(0,200)""")
        result["storage"]=page.evaluate("""() => ({local:Object.fromEntries(Object.entries(localStorage)), session:Object.fromEntries(Object.entries(sessionStorage))})""")
        browser.close()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"responses":len(result["responses"]),"bodyDates":result["bodyDateMatches"][:20],"htmlDates":result["htmlDateMatches"][:20]},ensure_ascii=False))

if __name__=="__main__":
    main()
