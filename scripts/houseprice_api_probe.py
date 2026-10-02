import json, urllib.parse, requests
from pathlib import Path

OUT=Path("docs/preview/houseprice-api-probe.json")
H={
  "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
  "Accept":"application/json,text/plain,*/*",
  "Accept-Language":"zh-TW,zh;q=0.9",
  "Referer":"https://www.houseprice.tw/",
  "Origin":"https://www.houseprice.tw",
}
city="新北市"; district="板橋區"; kw="中山路二段"
path="/".join(urllib.parse.quote(x,safe="") for x in [city+"_city",district+"_zip",kw+"_kw"])
urls=[
  f"https://buy.houseprice.tw/ws/BuyCaseList/Search/{path}/",
  f"https://buy.houseprice.tw/ws/BuyCaseList/Search/{path}",
  "https://buy.houseprice.tw/ws/webCase/FocusHouse?City="+urllib.parse.quote(city)+"&Page=1&Size=60",
]
payloads=[
  {"City":city,"Zip":district,"Keyword":kw,"Page":1,"Rows":30},
  {"City":city,"District":district,"Keyword":kw,"Page":1,"Rows":30},
  {"City":city,"ZipName":district,"KeyWord":kw,"Page":1,"Rows":30},
  {"City":city,"Page":1,"Rows":30},
]
out={"gets":[],"posts":[]}
for u in urls:
  try:
    r=requests.get(u,headers=H,timeout=30)
    out["gets"].append({"url":u,"status":r.status_code,"contentType":r.headers.get("content-type"),"body":r.text[:12000]})
  except Exception as e:
    out["gets"].append({"url":u,"error":f"{type(e).__name__}: {e}"})
api="https://www.houseprice.tw/ws/buygetWebCase/"
for p in payloads:
  try:
    r=requests.post(api,headers={**H,"Content-Type":"application/json"},json=p,timeout=30)
    rec={"payload":p,"status":r.status_code,"contentType":r.headers.get("content-type"),"body":r.text[:16000]}
    try:
      data=r.json()
      cases=data.get("webCaseGroupings") or []
      rec["jsonSummary"]={
        "keys":list(data.keys()),
        "count":data.get("count",data.get("totalCount")),
        "caseCount":len(cases),
        "firstCases":[{
          k:c.get(k) for k in ["sid","caseName","simpAddress","totalPrice","buildPin","fromFloor","upFloor","newKeyInDate","groupCount"]
        } for c in cases[:8]]
      }
    except Exception:
      pass
    out["posts"].append(rec)
  except Exception as e:
    out["posts"].append({"payload":p,"error":f"{type(e).__name__}: {e}"})
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({
 "gets":[(x.get("status"),x.get("url")) for x in out["gets"]],
 "posts":[(x.get("status"),(x.get("jsonSummary") or {}).get("caseCount"),x.get("payload")) for x in out["posts"]]
},ensure_ascii=False))
