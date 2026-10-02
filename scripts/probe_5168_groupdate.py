import json, requests
from pathlib import Path
OUT=Path("docs/preview/houseprice-groupdate-probe.json")
urls=[
 "https://buy.houseprice.tw/ws/detail?id=28718235",
 "https://buy.houseprice.tw/ws/BuyCaseDetail/33221169"
]
h={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Accept":"application/json,text/plain,*/*","Referer":"https://buy.houseprice.tw/house/33221169_930688/"}
out=[]
for u in urls:
    try:
        r=requests.get(u,headers=h,timeout=30)
        rec={"url":u,"status":r.status_code,"contentType":r.headers.get("content-type"),"body":r.text[:20000]}
        try:
            j=r.json()
            rec["json"]=j
        except Exception:
            pass
        out.append(rec)
    except Exception as e:
        out.append({"url":u,"error":f"{type(e).__name__}: {e}"})
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{"url":x.get("url"),"status":x.get("status"),"error":x.get("error")} for x in out],ensure_ascii=False))
