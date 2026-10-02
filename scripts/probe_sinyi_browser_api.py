import json, sys
from playwright.sync_api import sync_playwright

TARGET="https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip"

def main():
    captured=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width":1440,"height":1000},
        )
        page=context.new_page()

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

        page.on("response",on_response)
        page.goto(TARGET,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(10000)
        print(json.dumps({"captured":captured},ensure_ascii=False))
        browser.close()
    if not captured or not any(x.get("retResult") for x in captured):
        raise SystemExit("No successful filterObject response captured")

if __name__=="__main__":
    main()
