import json, requests, urllib.parse
from pathlib import Path

OUT=Path("docs/preview/houseprice-priceanalyze-probe.json")
BASE="https://app.houseprice.tw"
UA="5168/4.0.1 Android"
CASE_SID=33221169
GROUP_SID=28718235
CASE_URL="https://buy.houseprice.tw/house/33221169_930688/"

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

def walk(v,p="data",out=None):
    if out is None: out=[]
    if isinstance(v,dict):
        for k,val in v.items():
            q=f"{p}.{k}"
            if isinstance(val,(str,int,float,bool)) or val is None:
                if any(t in q.lower() for t in ["date","time","group","sid","history","publish","keyin","webcase","priceanalyze"]):
                    out.append({"path":q,"value":val})
            else:
                walk(val,q,out)
    elif isinstance(v,list):
        for i,val in enumerate(v[:200]):
            walk(val,f"{p}[{i}]",out)
    return out

def record(resp,label):
    rec={"label":label,"url":resp.url,"status":resp.status_code,"contentType":resp.headers.get("content-type")}
    try:
        j=resp.json()
        rec["jsonType"]=type(j).__name__
        rec["jsonKeys"]=list(j.keys()) if isinstance(j,dict) else None
        rec["interesting"]=walk(j)[:800]
        rec["body"]=json.dumps(j,ensure_ascii=False)[:30000]
    except Exception:
        rec["body"]=resp.text[:5000]
    return rec

def main():
    s=requests.Session()
    ar=s.get(BASE+"/api/AuthToken",params={"deviceId":"banqiao-priceanalyze-probe"},headers={"User-Agent":UA},timeout=30)
    ar.raise_for_status()
    token=find_token(ar.json())
    if not token: raise RuntimeError("token not found")
    s.headers.update({"User-Agent":UA,"Accept":"application/json","Authorization":"Bearer "+token})

    out={"authStatus":ar.status_code,"tests":[]}

    # First inspect the exact case detail for any hidden group/price-analysis pointer.
    r=s.get(BASE+"/api/Case/Info",params={"caseSid":CASE_SID},timeout=30)
    out["tests"].append(record(r,"CaseInfo"))

    gets=[
      (f"/api/PriceAnalyze/{GROUP_SID}/WebCaseRealtor","WebCaseRealtor-group"),
      (f"/api/PriceAnalyze/{CASE_SID}/WebCaseRealtor","WebCaseRealtor-case"),
      (f"/api/PriceAnalyze/{GROUP_SID}/SaleRecord","SaleRecord-group"),
      (f"/api/PriceAnalyze/{CASE_SID}/SaleRecord","SaleRecord-case"),
      (f"/api/PriceAnalyze/{GROUP_SID}/SurroundingRoad","SurroundingRoad-group"),
      (f"/api/PriceAnalyze/{GROUP_SID}/SurroundingCommunity","SurroundingCommunity-group"),
      (f"/api/PriceAnalyze/PriceAnalyze?sid={GROUP_SID}","PriceAnalyze-GET-sid-group"),
      (f"/api/PriceAnalyze/PriceAnalyze?groupId={GROUP_SID}","PriceAnalyze-GET-groupId"),
      (f"/api/PriceAnalyze/PriceAnalyze?caseSid={CASE_SID}","PriceAnalyze-GET-caseSid"),
      (f"/api/PriceAnalyze/TotalCount?sid={GROUP_SID}","TotalCount-sid-group"),
      (f"/api/PriceAnalyze/TotalCount?groupId={GROUP_SID}","TotalCount-groupId"),
      ("/api/PriceAnalyze/UrlValidation?url="+urllib.parse.quote(CASE_URL,safe=""),"UrlValidation"),
    ]
    for path,label in gets:
        try:
            rr=s.get(BASE+path,timeout=25)
            out["tests"].append(record(rr,label))
        except Exception as e:
            out["tests"].append({"label":label,"path":path,"error":f"{type(e).__name__}: {e}"})

    posts=[
      ("/api/PriceAnalyze/PriceAnalyze",{"sid":GROUP_SID},"PriceAnalyze-POST-sid-group"),
      ("/api/PriceAnalyze/PriceAnalyze",{"groupId":GROUP_SID},"PriceAnalyze-POST-groupId"),
      ("/api/PriceAnalyze/PriceAnalyze",{"caseSid":CASE_SID},"PriceAnalyze-POST-caseSid"),
      ("/api/PriceAnalyze/PriceAnalyze",{"url":CASE_URL},"PriceAnalyze-POST-url"),
    ]
    for path,payload,label in posts:
        try:
            rr=s.post(BASE+path,json=payload,timeout=25)
            rec=record(rr,label); rec["requestPayload"]=payload
            out["tests"].append(rec)
        except Exception as e:
            out["tests"].append({"label":label,"path":path,"requestPayload":payload,"error":f"{type(e).__name__}: {e}"})

    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps([{"label":x.get("label"),"status":x.get("status"),"interesting":x.get("interesting",[])[:8]} for x in out["tests"]],ensure_ascii=False))

if __name__=="__main__": main()
