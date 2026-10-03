import json
from urllib.parse import quote
from playwright.sync_api import sync_playwright

ROAD = "中山路二段"
AREA = "新北市-板橋區"
URL = f"https://buy.yungching.com.tw/list/{quote(AREA)}_c/{quote(ROAD)}_kw?od=80"

JS = r"""
async () => {
  const road = '中山路二段';
  const area = '新北市-板橋區';

  async function derive(serviceName) {
    const salt = new Uint8Array([2,7,0,5,1,3,8,0]);
    const digest = new Uint8Array(
      await crypto.subtle.digest('SHA-256', new TextEncoder().encode(serviceName))
    );
    const baseKey = await crypto.subtle.importKey('raw', digest, 'PBKDF2', false, ['deriveBits']);
    const bits = await crypto.subtle.deriveBits(
      {name:'PBKDF2', salt, iterations:1000, hash:'SHA-1'},
      baseKey,
      384
    );
    const key = await crypto.subtle.importKey(
      'raw', bits.slice(0,32), {name:'AES-CBC'}, false, ['decrypt']
    );
    return [key, bits.slice(32,48)];
  }

  async function decryptData(value) {
    const [key, iv] = await derive('YungChing.Buy');
    const ct = new Uint8Array(Array.from(atob(value), c => c.charCodeAt(0)));
    const raw = await crypto.subtle.decrypt(
      {name:'AES-CBC', iv:new Uint8Array(iv)}, key, ct
    );
    return JSON.parse(new TextDecoder().decode(raw));
  }

  async function getPage(pg) {
    const u = new URL('/api/v2/list', location.origin);
    const params = {
      area,
      pinType: '0',
      isAddRoom: 'true',
      keyword: road,
      filter: '0',
      pg: String(pg),
      ps: '30'
    };
    for (const [k,v] of Object.entries(params)) u.searchParams.set(k,v);
    const resp = await fetch(u.toString(), {
      credentials:'include',
      headers:{accept:'application/json, text/plain, */*'}
    });
    const wrapper = await resp.json();
    if (!resp.ok || wrapper?.status !== 'Success' || !wrapper?.data) {
      throw new Error(JSON.stringify({
        http:resp.status,
        status:wrapper?.status,
        apiVersion:wrapper?.apiVersion,
        method:wrapper?.method,
        url:u.toString()
      }));
    }
    return {
      http: resp.status,
      wrapper: {
        status: wrapper.status,
        apiVersion: wrapper.apiVersion,
        method: wrapper.method,
        dataLen: String(wrapper.data).length
      },
      body: await decryptData(wrapper.data)
    };
  }

  const first = await getPage(1);
  const totalPages = Number(first.body?.pa?.totalPageCount || 1);
  const pages = [first];
  for (let pg=2; pg<=totalPages; pg++) pages.push(await getPage(pg));

  const raw = pages.flatMap(p => Array.isArray(p.body?.list) ? p.body.list : []);
  const uniq = [...new Map(raw.filter(x => x?.caseSId != null).map(x => [String(x.caseSId), x])).values()];
  const prefix = '新北市板橋區' + road;
  const exact = uniq.filter(x => String(x?.address || '').startsWith(prefix));

  return {
    road,
    totalPages,
    apiTotalCount: first.body?.totalCount ?? null,
    paTotalItemCount: first.body?.pa?.totalItemCount ?? null,
    rawRows: raw.length,
    uniqueRows: uniq.length,
    exactRoadRows: exact.length,
    wrappers: pages.map((p,i)=>({pg:i+1, ...p.wrapper})),
    sample: exact.slice(0,10).map(x=>({
      caseSId:x.caseSId ?? null,
      caseName:x.caseName ?? null,
      address:x.address ?? null,
      price:x.price ?? null,
      regArea:x?.pinInfo?.regArea ?? null,
      floorInfo:x.floorInfo ?? null,
      patternInfo:x.patternInfo ?? null
    }))
  };
}
"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = ctx.new_page()
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        status = resp.status if resp else None
        page.wait_for_timeout(1500)
        title = page.title()
        body = page.locator("body").inner_text(timeout=5000)[:3000]
        print("WARMUP", json.dumps({
            "http": status,
            "title": title,
            "roadText": ROAD in body,
            "url": page.url
        }, ensure_ascii=False))
        if status != 200 or ROAD not in body:
            raise RuntimeError("Yongching warmup failed")

        result = page.evaluate(JS)
        print("=== YC_BROWSER_DIRECT_API_RESULT ===")
        print(json.dumps(result, ensure_ascii=False))
        if int(result.get("exactRoadRows") or 0) < 1:
            raise RuntimeError("Direct API decrypt returned no exact-road rows")
        browser.close()

if __name__ == "__main__":
    main()
