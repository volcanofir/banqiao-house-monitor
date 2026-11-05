"""Preview-only 591 field probe using the already verified public wareList entry.

Observes only field-key names/coverage, not addresses or listing bodies. A failed
detail request is diagnostic only and never changes a snapshot or status.
"""
import asyncio
import json
from collections import Counter
from urllib.parse import urlencode
from playwright.async_api import async_playwright
from diagnose_591_warelist_integrity import HOME, ROADS, SEARCH, UA

GET_FIELDS=r"""() => {
  const unref=x=>x?.__v_isRef?x.value:x;
  const sale=window.__NUXT__?.pinia?.['sale-list'];
  const rows=unref(sale?.wareList);
  if(!Array.isArray(rows))return {ok:false};
  const wanted=['floor','floors','floorStr','floor_str','floor_num','totalfloor',
   'totalFloor','origin_floor','layout','layoutStr','layout_str','community',
   'community_addr','community_id','kind','kindStr','price_has_carport',
   'room','rooms','houseage','houseAge','address','address_new','street_name',
   'posttime','houseid','post_id'];
  const counts=Object.fromEntries(wanted.map(k=>[k,rows.filter(x=>
   x?.[k]!==null && x?.[k]!==undefined && x?.[k]!=='' && x?.[k]!==false).length]));
  return {ok:true,count:rows.length,keys:[...new Set(rows.flatMap(x=>Object.keys(x||{})))].sort(),
          counts, sampleIds:rows.slice(0,2).map(x=>String(x?.post_id||x?.houseid||'').replace(/^S/,''))};
}"""
async def main():
  async with async_playwright() as p:
    browser=await p.chromium.launch(channel='chrome',headless=True,args=['--disable-dev-shm-usage'])
    context=await browser.new_context(user_agent=UA,viewport={'width':390,'height':844},
                is_mobile=True,has_touch=True,locale='zh-TW',timezone_id='Asia/Taipei')
    page=await context.new_page()
    try:
      home=await page.goto(HOME,wait_until='domcontentloaded',timeout=25000)
      if not home or home.status!=200: raise RuntimeError('Verified wareList HOME unavailable')
      samples=[]
      for road,sid in ROADS.items():
        q={'keywords':road.replace('板橋區',''),'regionid':'3','section':'26',
           'streetid':sid,'firstRow':'0','page':'1','shType':'list','itm_source':'main',
           'itm_medium':'home','itm_campaign':'prime_position','itm_content':'sale','type':'2'}
        r=await page.goto(SEARCH+'?'+urlencode(q),wait_until='domcontentloaded',timeout=23000)
        if not r or r.status!=200:raise RuntimeError('public sale page not 200')
        obj=await page.evaluate(GET_FIELDS)
        if not obj.get('ok'): raise RuntimeError('wareList state missing')
        samples.append({'road':road,'rows':obj['count'],'keys':obj['keys'],'fieldCounts':obj['counts']})
      print('FIELD_PROBE '+json.dumps({'roads':samples},ensure_ascii=False))
      # Same first-page browser context, sample only two normal detail links.
      if False: pass
    finally:
      await context.close()
      await browser.close()
if __name__=='__main__': asyncio.run(main())
