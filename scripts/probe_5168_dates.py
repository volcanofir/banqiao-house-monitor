import json, requests
from pathlib import Path

OUT=Path("docs/preview/houseprice-date-probe.json")
BASE="https://app.houseprice.tw"
UA="5168/4.0.1 Android"
CASE_IDS=[16758272,32950239,33221169]

def find_token(v):
    if isinstance(v,dict):
        for k,val in v.items():
            if str(k).lower() in {"token","accesstoken","access_token","authtoken"} and isinstance(val,str) and len(val)>10:
                return val
        for val in v.values():
            z=find_token(val)
            if z:return z
    if isinstance(v,list):
        for val in v:
            z=find_token(val)
            if z:return z
    return None

def scalars(v,prefix="data",out=None):
    if out is None: out=[]
    if isinstance(v,dict):
        for k,val in v.items():
            p=prefix+"."+str(k)
            if isinstance(val,(str,int,float,bool)) or val is None:
                out.append((p,val))
            else: scalars(val,p,out)
    elif isinstance(v,list):
        for i,val in enumerate(v[:100]):
            scalars(val,prefix+f"[{i}]",out)
    return out

def compact_response(r):
    rec={"status":r.status_code,"contentType":r.headers.get("content-type")}
    try:
        j=r.json()
        rec["jsonKeys"]=list(j.keys()) if isinstance(j,dict) else []
        data=j.get("data") if isinstance(j,dict) else None
        if data is not None:
            ss=scalars(data)
            rec["dateLike"]=[
                {"path":p,"value":v} for p,v in ss
                if any(x in p.lower() for x in ["date","time","publish","create","update","online","start","end","keyin","new"])
            ][:500]
            rec["topKeys"]=list(data.keys()) if isinstance(data,dict) else None
            rec["agentLike"]=[
                {"path":p,"value":v} for p,v in ss
                if "agent" in p.lower() and not any(x in p.lower() for x in ["picture","photo","image"])
            ][:500]
    except Exception:
        rec["bodyPrefix"]=r.text[:1500]
    return rec

def main():
    s=requests.Session()
    ar=s.get(BASE+"/api/AuthToken",params={"deviceId":"banqiao-monitor-date-probe"},headers={"User-Agent":UA},timeout=30)
    token=find_token(ar.json()) if ar.ok else None
    h={"User-Agent":UA,"Accept":"application/json"}
    if token:h["Authorization"]="Bearer "+token
    out={"authStatus":ar.status_code,"tokenFound":bool(token),"swagger":[],"cases":[]}
    for path in ["/swagger/v1/swagger.json","/swagger/index.html","/openapi/v1.json","/openapi.json"]:
        try:
            r=s.get(BASE+path,headers=h,timeout=20)
            out["swagger"].append({"path":path,"status":r.status_code,"contentType":r.headers.get("content-type"),"bodyPrefix":r.text[:3000]})
        except Exception as e:
            out["swagger"].append({"path":path,"error":f"{type(e).__name__}: {e}"})
    for sid in CASE_IDS:
        item={"caseSid":sid,"tests":[]}
        tests=[
          ("GET",f"/api/Case/Info?caseSid={sid}",None),
          ("GET",f"/api/Case/Agent?caseSid={sid}",None),
          ("GET",f"/api/Case/Deal?caseSid={sid}",None),
          ("GET",f"/api/Case/DealPrice?caseSid={sid}",None),
          ("GET",f"/api/Case/New?caseSid={sid}",None),
        ]
        for method,path,payload in tests:
            try:
                r=s.get(BASE+path,headers=h,timeout=25)
                rec={"path":path,**compact_response(r)}
                item["tests"].append(rec)
            except Exception as e:
                item["tests"].append({"path":path,"error":f"{type(e).__name__}: {e}"})
        out["cases"].append(item)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"auth":out["authStatus"],"token":out["tokenFound"],"cases":[(x["caseSid"],[(t["path"],t.get("status")) for t in x["tests"]]) for x in out["cases"]]},ensure_ascii=False))

if __name__=="__main__":main()
