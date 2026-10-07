import json, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

OUT = Path("docs/company/sinyi-banqiao-stores.json")
MAX_PAGES = 30
STORES = [
    ("R420","板橋中山店"),("R340","板橋中正店"),("R574","板橋亞東店"),("R471","板橋府中店"),
    ("R688","板橋重慶店"),("R120","板橋店"),("R820","新埔捷運店"),("R502","板橋江翠店"),
    ("R683","板橋新海店"),("R550","板新捷運店"),("R834","新埔新站店"),("R647","新板特區店"),
    ("RJ61","江翠重劃店"),("RJ13","華江重劃店"),("R951","樹林溪洲店"),("R833","江翠雙十店"),
]
HEADERS = {
    "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1",
    "Accept-Language":"zh-TW,zh;q=0.9",
    "Referer":"https://www.sinyi.com.tw/",
}

def store_url(code,name):
    return f"https://www.sinyi.com.tw/buy/list/{code}-{quote(name)}-store"

def number(value):
    try:
        n=float(value)
        return int(n) if n.is_integer() else n
    except Exception:
        return None

def fetch_store(code,name):
    last=None
    for attempt in range(1,4):
        try:
            seen=set(); rows_all=[]; pages=[]; total=None
            for page in range(1,MAX_PAGES+1):
                url=f"{store_url(code,name)}/publish-desc/{page}"
                r=requests.get(url,headers=HEADERS,timeout=30)
                r.raise_for_status()
                tag=BeautifulSoup(r.text,"html.parser").find("script",id="__NEXT_DATA__")
                if not tag or not tag.string:
                    raise RuntimeError("__NEXT_DATA__ missing")
                payload=json.loads(tag.string)
                reducer=(((payload.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
                page_rows=reducer.get("list") or []
                if total is None:
                    total=int(reducer.get("totalCnt") or 0)
                added=0
                for item in page_rows:
                    hid=str(item.get("houseNo") or "").strip()
                    if not hid or hid in seen:
                        continue
                    seen.add(hid); rows_all.append(item); added+=1
                pages.append({"page":page,"parsed":len(page_rows),"added":added,"uniqueTotal":len(seen)})
                if len(seen)>=total or not page_rows:
                    break
            if total is None or len(seen)!=total:
                raise RuntimeError(f"incomplete {len(seen)}/{total}")
            return rows_all,total,pages,attempt
        except Exception as exc:
            last=exc
            if attempt<3:
                time.sleep(attempt*2)
    raise RuntimeError(str(last))

def main():
    updated=datetime.now(timezone.utc).isoformat(timespec="seconds")
    stores=[]; listings=[]; failures=[]
    for code,name in STORES:
        try:
            raw,total,pages,attempt=fetch_store(code,name)
            for item in raw:
                hid=str(item.get("houseNo") or "").strip()
                listings.append({
                    "id":f"{code}:{hid}",
                    "storeCode":code,
                    "storeName":name,
                    "houseNo":hid,
                    "name":str(item.get("name") or "").strip(),
                    "address":str(item.get("address") or "").strip(),
                    "price":number(item.get("totalPrice")),
                    "areaBuilding":number(item.get("areaBuilding")),
                    "layout":item.get("layout") or item.get("totalLayout"),
                    "floor":item.get("floor"),
                    "totalfloor":item.get("totalfloor"),
                    "age":item.get("age"),
                    "community":item.get("commName"),
                    "firstDisplay":item.get("firstDisplay"),
                    "url":f"https://www.sinyi.com.tw/buy/house/{quote(hid)}?breadcrumb=list",
                })
            stores.append({
                "storeCode":code,"storeName":name,"status":"ok",
                "totalCount":total,"sourceTotalCount":total,
                "sourceUrl":store_url(code,name),
                "branchUrl":f"https://www.sinyi.com.tw/branch/{code}-store",
                "pages":pages,"attempt":attempt,
            })
            print(code,name,total)
        except Exception as exc:
            failures.append({"storeCode":code,"storeName":name,"error":str(exc)})
            stores.append({
                "storeCode":code,"storeName":name,"status":"error",
                "totalCount":0,"sourceTotalCount":None,
                "sourceUrl":store_url(code,name),
                "branchUrl":f"https://www.sinyi.com.tw/branch/{code}-store",
                "error":str(exc),
            })
            print(code,name,"ERROR",exc)

    payload={
        "source":"信義房屋",
        "scope":"user_selected_16_banqiao_stores",
        "updatedAt":updated,
        "storeCount":16,
        "healthyStoreCount":sum(x["status"]=="ok" for x in stores),
        "totalStoreListings":len(listings),
        "uniquePropertyCount":len({x["houseNo"] for x in listings}),
        "stores":stores,
        "failures":failures,
        "listings":listings,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    if failures:
        raise RuntimeError(json.dumps(failures,ensure_ascii=False))

if __name__=="__main__":
    main()
