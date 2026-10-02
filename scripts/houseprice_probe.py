import json,re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

BASE="https://buy.houseprice.tw"
LIST="https://buy.houseprice.tw/list/%E6%96%B0%E5%8C%97%E5%B8%82_city/%E6%9D%BF%E6%A9%8B%E5%8D%80_zip/%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5_kw"
OUT=Path("docs/preview/houseprice-probe.json")

def parse(html,url):
    soup=BeautifulSoup(html,"html.parser")
    houses=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(url,a["href"])
        m=re.search(r"/house/(\d+)_(\d+)/?",href)
        if not m: continue
        houses.append({"href":href,"id":m.group(1),"subId":m.group(2),"text":" ".join(a.stripped_strings)[:700],"class":a.get("class")})
    pages=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(url,a["href"]); txt=" ".join(a.stripped_strings)
        if "page" in href.lower() or re.fullmatch(r"\d+",txt or ""):
            pages.append({"href":href,"text":txt,"class":a.get("class")})
    return soup,houses,pages

def api_probe():
    urls=[
      "https://ws-buy.houseprice.tw/",
      "https://ws-buy.houseprice.tw/swagger/index.html",
      "https://ws-buy.houseprice.tw/swagger/v1/swagger.json",
      "https://ws-buy.houseprice.tw/swagger.json",
      "https://ws-buycase.houseprice.tw/",
      "https://ws-buycase.houseprice.tw/swagger/index.html",
      "https://ws-buycase.houseprice.tw/swagger/v1/swagger.json",
      "https://mt.houseprice.tw/",
    ]
    out=[]
    for u in urls:
        try:
            rr=requests.get(u,timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*"})
            out.append({"url":u,"status":rr.status_code,"contentType":rr.headers.get("content-type"),"body":rr.text[:5000]})
        except Exception as e:
            out.append({"url":u,"error":f"{type(e).__name__}: {e}"})
    return out

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei")
        page=ctx.new_page()
        resp=page.goto(LIST,wait_until="domcontentloaded",timeout=45000)
        page.wait_for_timeout(5000)
        html=page.content()
        soup,houses,pages=parse(html,page.url)
        detail_url=houses[0]["href"] if houses else "https://buy.houseprice.tw/house/33221169_930688/"
        dpage=ctx.new_page()
        dresp=dpage.goto(detail_url,wait_until="domcontentloaded",timeout=45000)
        dpage.wait_for_timeout(4000)
        dhtml=dpage.content(); ds=BeautifulSoup(dhtml,"html.parser")
        result={
          "apiProbe":api_probe(),
          "listStatus":resp.status if resp else None,"listUrl":page.url,"title":page.title(),
          "bodyText":" ".join(soup.stripped_strings)[:20000],
          "houseLinks":houses[:100],"uniqueHouseLinks":len({x["href"] for x in houses}),
          "pagination":pages[:150],
          "scripts":[(sc.string or sc.get_text() or "")[:6000] for sc in soup.find_all("script") if any(k in (sc.string or sc.get_text() or "") for k in ["house","list","page","total","price"])][:40],
          "network":[{"name":x.get("name"),"initiatorType":x.get("initiatorType")} for x in page.evaluate("performance.getEntriesByType('resource').map(e=>({name:e.name,initiatorType:e.initiatorType}))") if "houseprice.tw" in x.get("name","")][:120],
          "detail":{
            "url":dpage.url,"status":dresp.status if dresp else None,"title":dpage.title(),
            "text":" ".join(ds.stripped_strings)[:25000],
            "scripts":[(sc.string or sc.get_text() or "")[:8000] for sc in ds.find_all("script") if any(k in (sc.string or sc.get_text() or "").lower() for k in ["date","time","publish","create","house","price"])][:40]
          }
        }
        browser.close()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["listStatus"],"uniqueHouseLinks":result["uniqueHouseLinks"],"pages":len(result["pagination"]),"detail":result["detail"]["url"]},ensure_ascii=False))

if __name__=="__main__": main()
