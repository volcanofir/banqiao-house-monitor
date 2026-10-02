import json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE="https://buy.houseprice.tw"
LIST="https://buy.houseprice.tw/list/%E6%96%B0%E5%8C%97%E5%B8%82_city/%E6%9D%BF%E6%A9%8B%E5%8D%80_zip/%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5_kw"
OUT=Path("docs/preview/houseprice-probe.json")
H={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1","Accept-Language":"zh-TW,zh;q=0.9"}

def main():
    s=requests.Session()
    r=s.get(LIST,headers=H,timeout=30); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    house=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(BASE,a["href"])
        m=re.search(r"/house/(\d+)_(\d+)/?",href)
        if not m: continue
        house.append({"href":href,"text":" ".join(a.stripped_strings)[:500],"class":a.get("class")})
    pages=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(BASE,a["href"])
        txt=" ".join(a.stripped_strings)
        if "page" in href.lower() or re.fullmatch(r"\d+",txt or ""):
            pages.append({"href":href,"text":txt,"class":a.get("class")})
    scripts=[]
    for sc in soup.find_all("script"):
        body=sc.string or sc.get_text() or ""
        if any(k in body for k in ["house","list","page","total","price"]):
            scripts.append(body[:4000])
            if len(scripts)>=30: break
    detail_url=house[0]["href"] if house else "https://buy.houseprice.tw/house/33221169_930688/"
    d=s.get(detail_url,headers=H,timeout=30); d.raise_for_status()
    ds=BeautifulSoup(d.text,"html.parser")
    result={
      "listStatus":r.status_code,
      "listUrl":r.url,
      "listLength":len(r.text),
      "title":soup.title.string if soup.title else None,
      "bodyText":" ".join(soup.stripped_strings)[:15000],
      "houseLinks":house[:80],
      "uniqueHouseLinks":len({x["href"] for x in house}),
      "pagination":pages[:100],
      "scripts":scripts,
      "detail":{
        "url":d.url,"status":d.status_code,"length":len(d.text),
        "title":ds.title.string if ds.title else None,
        "text":" ".join(ds.stripped_strings)[:20000],
        "scripts":[(sc.string or sc.get_text() or "")[:6000] for sc in ds.find_all("script") if any(k in (sc.string or sc.get_text() or "") for k in ["date","time","publish","create","house","price"])][:30]
      }
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"uniqueHouseLinks":result["uniqueHouseLinks"],"pages":len(result["pagination"]),"detail":result["detail"]["url"]},ensure_ascii=False))

if __name__=="__main__": main()
