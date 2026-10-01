"""Inspect Rakuya sale list HTML for the seven Banqiao watched roads.

Diagnostic only: no production/Preview data mutation.
"""

from urllib.parse import quote, urljoin
import requests
from bs4 import BeautifulSoup

ROAD="中山路二段"
URL=f"https://www.rakuya.com.tw/sell/result?zipcode=220&search=route&landmark={quote(ROAD)}"

HEADERS={
    "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language":"zh-TW,zh;q=0.9,en;q=0.7",
}

r=requests.get(URL,headers=HEADERS,timeout=30)
print("STATUS",r.status_code,"URL",r.url,"LEN",len(r.text))
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")

links=[]
for a in soup.find_all("a",href=True):
    href=urljoin(r.url,a["href"])
    if "/sell/info" in href:
        txt=" ".join(a.stripped_strings)
        links.append((href,txt,a.get("class"),a.parent.get("class") if a.parent else None))

seen=set()
uniq=[]
for x in links:
    key=x[0]
    if key in seen: continue
    seen.add(key);uniq.append(x)

print("SELL_INFO_LINKS",len(uniq))
for i,(href,txt,cls,pcls) in enumerate(uniq[:8],1):
    print("ITEM",i,href)
    print(" TEXT",txt[:600])
    print(" ACLASS",cls,"PCLASS",pcls)

print("PAGINATION CANDIDATES")
for a in soup.find_all("a",href=True):
    href=urljoin(r.url,a["href"])
    txt=" ".join(a.stripped_strings)
    if ("page=" in href.lower() or "p=" in href.lower() or "offset" in href.lower()) and "rakuya.com.tw/sell/result" in href:
        print(" PAGE",txt,href)

for key in ["total","result","pagination","pager","page"]:
    els=soup.select(f'[class*="{key}"],[id*="{key}"]')
    if els:
        print("SELECTOR",key,"COUNT",len(els))
        for el in els[:8]:
            print(" ",el.name,el.get("class"),el.get("id")," ".join(el.stripped_strings)[:500])

print("PAGINATION_HTML")
for el in soup.select(".block__pagination,#app_pagination"):
    print(str(el)[:5000])

print("COMMUNITY_LINKS")
comm=[]
for a in soup.find_all("a",href=True):
    href=urljoin(r.url,a["href"])
    if "community.rakuya.com.tw" in href:
        txt=" ".join(a.stripped_strings)
        if txt and len(txt)>20:
            comm.append((href,txt,a.get("class")))
for i,(href,txt,cls) in enumerate(comm[:30],1):
    print("COMM",i,href,cls,txt[:500])
