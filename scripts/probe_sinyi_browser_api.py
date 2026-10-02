import json, sys
import requests
from playwright.sync_api import sync_playwright

TARGET="https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip"

def main():
    captured=[]
    captured_request=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width":1440,"height":1000},
        )
        page=context.new_page()

        def on_request(req):
            if "sinyiwebapi.sinyi.com.tw/filterObject.php" not in req.url or captured_request:
                return
            try:
                captured_request.append({
                    "headers": req.all_headers(),
                    "postData": json.loads(req.post_data or "{}"),
                })
            except Exception as e:
                captured_request.append({"error": f"{type(e).__name__}: {e}"})

        def on_response(resp):
            if "sinyiwebapi.sinyi.com.tw/filterObject.php" not in resp.url:
                return
            try:
                j=resp.json()
                c=j.get("content") if isinstance(j,dict) else {}
                arr=(c or {}).get("object") if isinstance(c,dict) else None
                captured.append({
                    "status":resp.status,
                    "retResult":j.get("retResult"),
                    "retCode":j.get("retCode"),
                    "page":(c or {}).get("page"),
                    "totalCnt":(c or {}).get("totalCnt"),
                    "objectCount":len(arr) if isinstance(arr,list) else None,
                    "sampleFields":sorted(arr[0].keys()) if isinstance(arr,list) and arr else [],
                })
            except Exception as e:
                captured.append({"status":resp.status,"error":f"{type(e).__name__}: {e}"})

        page.on("request",on_request)
        page.on("response",on_response)
        page.goto(TARGET,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(10000)
        secondary=[]
        if captured_request and not captured_request[0].get("error"):
            base_headers=captured_request[0]["headers"]
            safe_headers={
                k:v for k,v in base_headers.items()
                if k.lower() in {"accept","content-type","origin","referer","user-agent","code","sat","sid"}
            }
            base_payload=captured_request[0]["postData"]
            for label,page_no,page_cnt in [("page2",2,18),("pageCnt100",1,100)]:
                payload=dict(base_payload)
                payload["page"]=page_no
                payload["pageCnt"]=page_cnt
                try:
                    rr=requests.post("https://sinyiwebapi.sinyi.com.tw/filterObject.php",
                        json=payload,headers=safe_headers,timeout=30)
                    jj=rr.json()
                    cc=jj.get("content") if isinstance(jj,dict) else {}
                    aa=(cc or {}).get("object") if isinstance(cc,dict) else None
                    secondary.append({
                        "label":label,"status":rr.status_code,
                        "retResult":jj.get("retResult") if isinstance(jj,dict) else None,
                        "retCode":jj.get("retCode") if isinstance(jj,dict) else None,
                        "page":(cc or {}).get("page") if isinstance(cc,dict) else None,
                        "totalCnt":(cc or {}).get("totalCnt") if isinstance(cc,dict) else None,
                        "objectCount":len(aa) if isinstance(aa,list) else None,
                    })
                except Exception as e:
                    secondary.append({"label":label,"error":f"{type(e).__name__}: {e}"})
        print(json.dumps({"captured":captured,"secondary":secondary},ensure_ascii=False))
        browser.close()
    if not captured or not any(x.get("retResult") for x in captured):
        raise SystemExit("No successful filterObject response captured")

if __name__=="__main__":
    main()
