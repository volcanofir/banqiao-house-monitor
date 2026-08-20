import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

DATA_PATH = Path('docs/data/listings.json')
OUT_PATH = Path('docs/data/sinyi-network-diagnostic.json')
TIME_KEY = re.compile(r'(publish|published|create|created|update|updated|online|listed|listing|date|time|start|launch|display|open|begin)', re.I)
DATE_VALUE = re.compile(r'(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{6}|20\d{2}-\d{2}-\d{2}T\d{2}:\d{2})')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def walk_time_fields(value, path='$', depth=0, out=None):
    if out is None:
        out=[]
    if depth > 12 or len(out) >= 300:
        return out
    if isinstance(value, dict):
        for k,v in value.items():
            p=f'{path}.{k}'
            if TIME_KEY.search(str(k)) and scalar(v):
                out.append({'path':p,'key':str(k),'value':v})
            elif isinstance(v,str) and DATE_VALUE.search(v) and len(v) < 200:
                out.append({'path':p,'key':str(k),'value':v,'matchedByValue':True})
            walk_time_fields(v,p,depth+1,out)
    elif isinstance(value,list):
        for i,v in enumerate(value[:100]):
            walk_time_fields(v,f'{path}[{i}]',depth+1,out)
    return out


def contains_house(value, house_id, depth=0):
    if depth > 10:
        return False
    if isinstance(value, dict):
        return any(contains_house(v,house_id,depth+1) for v in value.values())
    if isinstance(value, list):
        return any(contains_house(v,house_id,depth+1) for v in value[:200])
    return house_id.lower() in str(value or '').lower()


def relevant_objects(value, house_id, path='$', depth=0, out=None):
    if out is None:
        out=[]
    if depth > 10 or len(out) >= 50:
        return out
    if isinstance(value,dict):
        if contains_house(value,house_id) and any(house_id.lower() in str(v or '').lower() for v in value.values() if scalar(v)):
            compact={k:v for k,v in value.items() if scalar(v)}
            if compact:
                out.append({'path':path,'object':compact,'timeCandidates':walk_time_fields(value,path)[:80]})
        for k,v in value.items():
            relevant_objects(v,house_id,f'{path}.{k}',depth+1,out)
    elif isinstance(value,list):
        for i,v in enumerate(value[:200]):
            relevant_objects(v,house_id,f'{path}[{i}]',depth+1,out)
    return out


async def diagnose_one(browser, item):
    house_id=str(item.get('houseId') or '')
    result={'houseId':house_id,'title':item.get('title'),'road':item.get('road'),'url':item.get('url'),'responses':[]}
    context=await browser.new_context(locale='zh-TW', timezone_id='Asia/Taipei')
    page=await context.new_page()
    seen=set()
    tasks=[]

    async def inspect_response(resp):
        if resp.url in seen:
            return
        seen.add(resp.url)
        req=resp.request
        rtype=req.resource_type
        ctype=(resp.headers.get('content-type') or '').lower()
        if rtype not in ('xhr','fetch') and 'json' not in ctype:
            return
        rec={'url':resp.url,'status':resp.status,'resourceType':rtype,'contentType':ctype}
        try:
            body=await resp.body()
            if len(body)>3_000_000:
                rec['skipped']='body too large'
                result['responses'].append(rec)
                return
            text=body.decode('utf-8','ignore')
            try:
                payload=json.loads(text)
            except Exception:
                if house_id.lower() in text.lower():
                    rec['containsHouseId']=True
                    rec['textSnippet']=text[:1000]
                result['responses'].append(rec)
                return
            rec['containsHouseId']=contains_house(payload,house_id)
            rec['timeCandidates']=walk_time_fields(payload)[:120]
            if rec['containsHouseId']:
                rec['houseObjects']=relevant_objects(payload,house_id)[:20]
            if rec['containsHouseId'] or rec['timeCandidates']:
                result['responses'].append(rec)
        except Exception as exc:
            rec['error']=type(exc).__name__
            result['responses'].append(rec)

    def on_response(resp):
        tasks.append(asyncio.create_task(inspect_response(resp)))

    page.on('response',on_response)
    try:
        await page.goto(item.get('url'),wait_until='domcontentloaded',timeout=45000)
        await page.wait_for_timeout(10000)
        # Trigger lazy/API loads without interacting with forms.
        for frac in (0.25,0.5,0.75,1.0):
            try:
                await page.evaluate(f'window.scrollTo(0, document.body.scrollHeight*{frac})')
                await page.wait_for_timeout(1200)
            except Exception:
                pass
    except Exception as exc:
        result['navigationError']=repr(exc)
    if tasks:
        await asyncio.gather(*tasks,return_exceptions=True)
    result['apiCount']=len(result['responses'])
    result['houseApiCount']=sum(1 for x in result['responses'] if x.get('containsHouseId'))
    await context.close()
    return result


async def main():
    state=json.loads(DATA_PATH.read_text(encoding='utf-8'))
    samples=[x for x in state.get('listings',[]) if x.get('source')=='信義房屋' and x.get('houseId')][:8]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True,args=['--disable-dev-shm-usage'])
        try:
            results=[]
            for item in samples:
                results.append(await diagnose_one(browser,item))
        finally:
            await browser.close()
    all_house=[]
    for r in results:
        for resp in r.get('responses',[]):
            if resp.get('containsHouseId'):
                all_house.append({'houseId':r['houseId'],'url':resp['url'],'timeCandidates':resp.get('timeCandidates',[]),'houseObjects':resp.get('houseObjects',[])})
    report={
        'summary':{
            'checkedAt':now_iso(),
            'sampleCount':len(samples),
            'responsesKept':sum(r.get('apiCount',0) for r in results),
            'houseRelatedResponses':sum(r.get('houseApiCount',0) for r in results),
            'productionDataModified':False,
        },
        'houseRelatedResponses':all_house,
        'results':results,
    }
    OUT_PATH.parent.mkdir(parents=True,exist_ok=True)
    OUT_PATH.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':
    asyncio.run(main())
