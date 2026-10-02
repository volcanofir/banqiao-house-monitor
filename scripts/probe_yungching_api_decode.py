import json, re, sys, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

ROAD="三民路二段"
URL=f"https://buy.yungching.com.tw/list/{quote('新北市-板橋區')}_c/{quote(ROAD)}_kw?od=80"

INIT=r"""
(() => {
  window.__ycProbe={json:[], decoded:[]};
  const op=JSON.parse;
  JSON.parse=function(s,...rest){
    try{
      if(typeof s==='string' && s.length>200){
        const hit=/三民路|中山路|house|price|address|建坪|total/i.test(s);
        window.__ycProbe.json.push({len:s.length,hit,prefix:s.slice(0,1800)});
        if(window.__ycProbe.json.length>60) window.__ycProbe.json.shift();
      }
    }catch(e){}
    return op.call(this,s,...rest);
  };
  try{
    const OD=TextDecoder.prototype.decode;
    TextDecoder.prototype.decode=function(...args){
      const out=OD.apply(this,args);
      try{
        if(typeof out==='string' && out.length>200){
          const hit=/三民路|中山路|house|price|address|建坪|total/i.test(out);
          if(hit) window.__ycProbe.decoded.push({len:out.length,prefix:out.slice(0,1800)});
          if(window.__ycProbe.decoded.length>30) window.__ycProbe.decoded.shift();
        }
      }catch(e){}
      return out;
    };
  }catch(e){}
})();
"""

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, channel="chrome")
        ctx=browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei")
        page=ctx.new_page()
        page.add_init_script(INIT)
        api=[]
        def on_response(resp):
            if "/api/v2/list" not in resp.url:
                return
            try:
                body=resp.json()
                api.append({
                    "url":resp.url,
                    "status":resp.status,
                    "apiStatus":body.get("status") if isinstance(body,dict) else None,
                    "apiVersion":body.get("apiVersion") if isinstance(body,dict) else None,
                    "dataLen":len(str(body.get("data") or "")) if isinstance(body,dict) else None,
                })
            except Exception as e:
                api.append({"url":resp.url,"status":resp.status,"error":f"{type(e).__name__}: {e}"})
        page.on("response",on_response)

        nav=page.goto(URL,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(9000)
        scripts=page.eval_on_selector_all("script[src]","els=>[...new Set(els.map(x=>x.src).filter(Boolean))]")
        probe=page.evaluate("window.__ycProbe")
        title=page.title()
        body=page.locator("body").inner_text(timeout=10000)
        print(json.dumps({
            "navHttp":nav.status if nav else None,
            "finalUrl":page.url,
            "title":title,
            "api":api,
            "bodyHasRoad":ROAD in body,
            "bodyRoadCount":body.count(ROAD),
            "jsonCaptureCount":len((probe or {}).get("json") or []),
            "jsonHits":[x for x in ((probe or {}).get("json") or []) if x.get("hit")][:12],
            "decoderHits":((probe or {}).get("decoded") or [])[:12],
            "scriptCount":len(scripts),
        },ensure_ascii=False))

        needles=["/api/v2/list","decrypt","CryptoJS","AES","crypto-js","apiVersion"]
        matches=[]
        for src in scripts:
            if "yungching" not in src:
                continue
            try:
                rr=ctx.request.get(src,timeout=30000)
                if not rr.ok:
                    continue
                txt=rr.text()
            except Exception:
                continue
            low=txt.lower()
            hit_needles=[n for n in needles if n.lower() in low]
            if not hit_needles:
                continue
            snippets=[]
            for needle in hit_needles:
                pos=low.find(needle.lower())
                if pos>=0:
                    snippets.append({"needle":needle,"snippet":txt[max(0,pos-1200):pos+3000]})
            matches.append({"src":src,"len":len(txt),"needles":hit_needles,"snippets":snippets})
        print("=== SCRIPT_MATCHES ===")
        print(json.dumps(matches[:12],ensure_ascii=False))
        browser.close()

if __name__=="__main__":
    main()
