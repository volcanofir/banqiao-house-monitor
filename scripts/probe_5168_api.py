import json
from pathlib import Path
import requests

OUT=Path("docs/preview/houseprice-api-probe.json")
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36","Accept":"application/json,text/plain,*/*","Accept-Language":"zh-TW,zh;q=0.9"}

def snap(r):
    return {"status":r.status_code,"url":r.url,"contentType":r.headers.get("content-type"),"body":r.text[:20000]}

def main():
    out={}
    try:
        r=requests.get("https://buy.houseprice.tw/ws/BuyCaseList/Search/%E6%96%B0%E5%8C%97%E5%B8%82_city/",headers=H,timeout=30)
        out["buyCaseList"]=snap(r)
    except Exception as e:
        out["buyCaseList"]={"error":f"{type(e).__name__}: {e}"}
    try:
        h=dict(H)
        h.update({"Content-Type":"application/json","Origin":"https://www.houseprice.tw","Referer":"https://www.houseprice.tw/"})
        payload={"City":"新北市","Page":1,"Rows":30}
        r=requests.post("https://www.houseprice.tw/ws/buygetWebCase/",headers=h,json=payload,timeout=30)
        out["buygetWebCase"]=snap(r)
        out["requestPayload"]=payload
    except Exception as e:
        out["buygetWebCase"]={"error":f"{type(e).__name__}: {e}"}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:{kk:v.get(kk) for kk in ("status","url","error")} for k,v in out.items() if isinstance(v,dict)},ensure_ascii=False))

if __name__=="__main__": main()
