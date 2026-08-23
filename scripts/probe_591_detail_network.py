"""Probe 591 public detail pages for structured floor/community/layout evidence.

Diagnostic only; does not modify monitored or canonical Preview data.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

OUT=Path('docs/preview/591-detail-network-probe.json')
SAMPLES=['20251660','20729207','20731702','20523222']
KEY_RE=re.compile(r'(floor|樓|room|layout|community|comm|address|house|post|building|kind|type)',re.I)


def scalar(v): return v is None or isinstance(v,(str,int,float,bool))

def walk(x,path='$',depth=0,out=None):
    if out is None: out=[]
    if depth>10 or len(out)>=400: return out
    if isinstance(x,dict):
        for k,v in x.items():
            p=f'{path}.{k}'
            if KEY_RE.search(str(k)) and scalar(v) and len(str(v))<=300:
                out.append({'path':p,'key':str(k),'value':v})
            walk(v,p,depth+1,out)
    elif isinstance(x,list):
        for i,v in enumerate(x[:100]): walk(v,f'{path}[{i}]',depth+1,out)
    return out

async def one(browser,pid):
    ctx=await browser.new_context(locale='zh-TW',timezone_id='Asia/Taipei',viewport={'width':390,'height':844},is_mobile=True,has_touch=True,user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')
    page=await ctx.new_page(); tasks=[]; responses=[]
    async def inspect(resp):
        req=resp.request; ctype=(resp.headers.get('content-type') or '').lower()
        if req.resource_type not in ('xhr','fetch') and 'json' not in ctype: return
        rec={'url':resp.url,'status':resp.status,'resourceType':req.resource_type,'contentType':ctype}
        try:
            text=await resp.text()
            try: data=json.loads(text)
            except Exception: return
            fields=walk(data)
            relevant=[x for x in fields if ('floor' in x['key'].lower() or '樓' in x['key'] or pid in str(x.get('value','')))]
            if relevant or pid in text:
                rec['fields']=fields[:160]
                rec['containsId']=pid in text
                responses.append(rec)
        except Exception: pass
    def on_response(resp): tasks.append(asyncio.create_task(inspect(resp)))
    page.on('response',on_response)
    result={'id':pid,'url':f'https://m.591.com.tw/v2/sale/{pid}','responses':responses}
    try:
        r=await page.goto(result['url'],wait_until='domcontentloaded',timeout=45000)
        result['http']=r.status if r else None
        await page.wait_for_timeout(5000)
        body=await page.locator('body').inner_text(timeout=5000)
        pats=[]
        for pat in [r'.{0,50}樓層.{0,80}',r'.{0,50}\d{1,2}\s*/\s*\d{1,2}\s*樓.{0,50}',r'.{0,50}\d{1,2}\s*樓.{0,50}']:
            pats += re.findall(pat,body,re.S)[:12]
        result['domFloorSnippets']=[re.sub(r'\s+',' ',x).strip()[:180] for x in pats[:20]]
        result['bodyHasFloorLabel']='樓層' in body
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
    if tasks: await asyncio.gather(*tasks,return_exceptions=True)
    result['responseCount']=len(responses)
    await ctx.close(); return result

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True,args=['--disable-dev-shm-usage'])
        try: results=await asyncio.gather(*(one(browser,x) for x in SAMPLES))
        finally: await browser.close()
    out={'capturedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'previewOnly':True,'samples':results}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'id':x['id'],'http':x.get('http'),'responseCount':x.get('responseCount'),'bodyHasFloorLabel':x.get('bodyHasFloorLabel'),'domFloorSnippets':x.get('domFloorSnippets')} for x in results],ensure_ascii=False))

if __name__=='__main__': asyncio.run(main())
