import json, requests
API="https://app.houseprice.tw"
H={"User-Agent":"5168/4.0.1 Android","Accept":"application/json","Accept-Language":"zh-TW,zh;q=0.9"}

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

r=requests.get(API+"/api/AuthToken",params={"deviceId":"banqiao-rent-probe"},headers=H,timeout=30)
r.raise_for_status()
token=find_token(r.json())
HH={**H,"Authorization":"Bearer "+token,"Content-Type":"application/json"}
base={"city":"新北市","district":["板橋區"],"keyword":"中山路二段","page":1}

tests=[]
for path in ["/api/Rent/List","/api/ForRent/List","/api/Lease/List","/api/Rental/List","/api/HouseRent/List"]:
    for method in ["POST","GET"]:
        try:
            if method=="POST":
                rr=requests.post(API+path,headers=HH,json=base,timeout=30)
            else:
                rr=requests.get(API+path,headers={k:v for k,v in HH.items() if k!="Content-Type"},params=base,timeout=30)
            rec={"method":method,"path":path,"status":rr.status_code,"contentType":rr.headers.get("content-type"),"body":rr.text[:12000]}
            try:
                jj=rr.json()
                rec["json"]=jj
            except Exception: pass
            tests.append(rec)
        except Exception as e:
            tests.append({"method":method,"path":path,"error":f"{type(e).__name__}: {e}"})

extra_payloads=[
    {**base,"kind":"Rent"},
    {**base,"kind":"rent"},
    {**base,"type":"Rent"},
    {**base,"caseType":"Rent"},
    {**base,"tradeType":"Rent"},
    {**base,"sellRentType":"Rent"},
    {**base,"rent":True},
    {**base,"isRent":True},
    {**base,"usage":21},
]
for p in extra_payloads:
    try:
        rr=requests.post(API+"/api/Case/List",headers=HH,json=p,timeout=30)
        rec={"method":"POST","path":"/api/Case/List","payload":p,"status":rr.status_code,"body":rr.text[:12000]}
        try: rec["json"]=rr.json()
        except Exception: pass
        tests.append(rec)
    except Exception as e:
        tests.append({"method":"POST","path":"/api/Case/List","payload":p,"error":f"{type(e).__name__}: {e}"})

print(json.dumps(tests,ensure_ascii=False))
