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


# Probe the current Android app API discovered from com.houseprice.hp5168 v4.0.1.
app_base="https://app.houseprice.tw"
app={"auth":None,"tests":[]}
token=None
try:
  rr=requests.get(app_base+"/api/AuthToken",params={"deviceId":"banqiao-monitor-probe-20261002"},headers={"User-Agent":"5168/4.0.1 Android"},timeout=30)
  auth_rec={"status":rr.status_code,"contentType":rr.headers.get("content-type"),"bodyPrefix":rr.text[:3000]}
  try:
    aj=rr.json()
    auth_rec["jsonKeys"]=list(aj.keys()) if isinstance(aj,dict) else []
    def find_token(v):
      if isinstance(v,dict):
        for k,val in v.items():
          if str(k).lower() in {"token","accesstoken","access_token","authtoken"} and isinstance(val,str) and len(val)>10:
            return val
        for val in v.values():
          z=find_token(val)
          if z:return z
      elif isinstance(v,list):
        for val in v:
          z=find_token(val)
          if z:return z
      return None
    token=find_token(aj)
    auth_rec["tokenFound"]=bool(token)
    if token:
      auth_rec["bodyPrefix"]="[token redacted]"
  except Exception:
    pass
  app["auth"]=auth_rec
except Exception as e:
  app["auth"]={"error":f"{type(e).__name__}: {e}"}

app_headers={"User-Agent":"5168/4.0.1 Android","Accept":"application/json"}
if token:
  app_headers["Authorization"]="Bearer "+token

tests=[
 ("GET","/api/AppVersion",None),
 ("GET","/api/County/CityDistrict",None),
 ("GET","/api/Case/List",None),
 ("POST","/api/Case/List",{}),
 ("POST","/api/Case/List",{"city":"新北市","district":"板橋區","keyword":"中山路二段","page":1,"pageSize":20}),
 ("POST","/api/Case/List",{"City":"新北市","District":"板橋區","Keyword":"中山路二段","Page":1,"Rows":20}),
]
for method,path2,payload in tests:
  try:
    if method=="GET":
      rr=requests.get(app_base+path2,headers=app_headers,timeout=30)
    else:
      rr=requests.post(app_base+path2,headers={**app_headers,"Content-Type":"application/json"},json=payload,timeout=30)
    rec={"method":method,"path":path2,"payload":payload,"status":rr.status_code,"contentType":rr.headers.get("content-type"),"body":rr.text[:8000]}
    try:
      jj=rr.json()
      rec["jsonType"]=type(jj).__name__
      if isinstance(jj,dict):
        rec["jsonKeys"]=list(jj.keys())
    except Exception: pass
    app["tests"].append(rec)
  except Exception as e:
    app["tests"].append({"method":method,"path":path2,"payload":payload,"error":f"{type(e).__name__}: {e}"})

out["appApi"]=app
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({
  "appAuthStatus":(app.get("auth") or {}).get("status"),
  "appTokenFound":(app.get("auth") or {}).get("tokenFound"),
  "appTests":[(x.get("method"),x.get("path"),x.get("status")) for x in app.get("tests",[])]
},ensure_ascii=False))
