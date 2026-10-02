import json, requests
H={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*"}
urls=[
 "https://ws-rent.houseprice.tw/",
 "https://ws-rent.houseprice.tw/swagger",
 "https://ws-rent.houseprice.tw/swagger/index.html",
 "https://ws-rent.houseprice.tw/swagger/v1/swagger.json",
 "https://ws-rent.houseprice.tw/openapi.json",
 "https://ws-rent.houseprice.tw/health",
]
out=[]
for u in urls:
    try:
        r=requests.get(u,headers=H,timeout=20,allow_redirects=True)
        out.append({"url":u,"status":r.status_code,"final":r.url,"ct":r.headers.get("content-type"),"body":r.text[:12000]})
    except Exception as e:
        out.append({"url":u,"error":f"{type(e).__name__}: {e}"})
print(json.dumps(out,ensure_ascii=False))
