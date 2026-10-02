import json, requests
from datetime import datetime, timezone

API="https://sinyiwebapi.sinyi.com.tw/filterObject.php"

BASE={
 "machineNo":"","ipAddress":"","osType":3,"model":"web","deviceVersion":"Linux",
 "appVersion":"140.0.0.0","deviceType":3,"apType":3,"browser":1,"memberId":"",
 "domain":"www.sinyi.com.tw","utmSource":"","utmMedium":"","utmCampaign":"",
 "utmCode":"","requestor":1,"utmContent":"","utmTerm":"","sinyiGroup":1,
 "filter":{"exludeSameTrade":False,"objectStatus":0,"retType":2,"retRange":["220"],"mapType":1,"objectType":[]},
 "page":1,"pageCnt":18,"sort":"0","isReturnTotal":True
}
HEADERS={
 "Accept":"application/json, text/plain, */*",
 "Content-Type":"application/json",
 "Origin":"https://www.sinyi.com.tw",
 "Referer":"https://www.sinyi.com.tw/",
 "User-Agent":"Mozilla/5.0"
}

def run(label, payload, headers):
    try:
        r=requests.post(API,json=payload,headers=headers,timeout=30)
        out={"label":label,"status":r.status_code,"contentType":r.headers.get("content-type")}
        try:
            j=r.json()
            c=j.get("content") if isinstance(j,dict) else None
            arr=(c or {}).get("object") if isinstance(c,dict) else None
            out.update({
              "retResult":j.get("retResult") if isinstance(j,dict) else None,
              "retCode":j.get("retCode") if isinstance(j,dict) else None,
              "retMsg":j.get("retMsg") if isinstance(j,dict) else None,
              "page":(c or {}).get("page") if isinstance(c,dict) else None,
              "totalCnt":(c or {}).get("totalCnt") if isinstance(c,dict) else None,
              "objectCount":len(arr) if isinstance(arr,list) else None,
              "sampleFields":sorted(arr[0].keys()) if isinstance(arr,list) and arr else [],
            })
        except Exception:
            out["bodyPrefix"]=r.text[:300]
        print(json.dumps(out,ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"label":label,"error":f"{type(e).__name__}: {e}"},ensure_ascii=False))

run("minimal",dict(BASE),dict(HEADERS))
p=dict(BASE); p["pageCnt"]=100
run("minimal-pageCnt100",p,dict(HEADERS))
