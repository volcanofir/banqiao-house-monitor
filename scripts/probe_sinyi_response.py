import json, time, hashlib, requests
from bs4 import BeautifulSoup
from urllib.parse import quote

ROADS=["中山路二段","三民路二段","光復街","萬安街","林森街","三民路一段","翠華街"]
HEADERS={
 "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
 "Accept-Language":"zh-TW,zh;q=0.9,en;q=0.8",
 "Cache-Control":"no-cache",
}

def url(road):
    return f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(road)}-keyword/publish-desc/1"

def inspect(resp):
    text=resp.text
    soup=BeautifulSoup(text,"html.parser")
    script=soup.find("script",id="__NEXT_DATA__")
    out={
      "status":resp.status_code,
      "finalUrl":resp.url,
      "bytes":len(text.encode("utf-8")),
      "sha12":hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
      "title":soup.title.get_text(" ",strip=True) if soup.title else None,
      "nextData":bool(script and script.string),
      "server":resp.headers.get("server"),
      "cache":resp.headers.get("x-cache") or resp.headers.get("cf-cache-status"),
      "via":resp.headers.get("via"),
      "age":resp.headers.get("age"),
      "setCookie":bool(resp.headers.get("set-cookie")),
    }
    if script and script.string:
      try:
        p=json.loads(script.string)
        out["buildId"]=p.get("buildId")
        reducer=(((p.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
        lst=reducer.get("list")
        out["listType"]=type(lst).__name__
        out["listCount"]=len(lst) if isinstance(lst,list) else None
        out["reducerKeys"]=sorted(reducer.keys())
        for k in ["total","count","totalCount","page","pageCount","isLoading","status","error"]:
          if k in reducer: out[k]=reducer.get(k)
      except Exception as e:
        out["parseError"]=f"{type(e).__name__}: {e}"
    low=text.lower()
    out["markers"]=[m for m in ["captcha","cloudflare","access denied","機器人","驗證","too many requests","429"] if m in low]
    return out

def main():
    s=requests.Session()
    for round_no in range(1,6):
      print(f"=== ROUND {round_no} ===",flush=True)
      for road in ROADS:
        try:
          r=s.get(url(road),headers=HEADERS,timeout=30,allow_redirects=True)
          print(json.dumps({"road":road,**inspect(r)},ensure_ascii=False),flush=True)
        except Exception as e:
          print(json.dumps({"road":road,"error":f"{type(e).__name__}: {e}"},ensure_ascii=False),flush=True)
        time.sleep(1.0)
      time.sleep(3)

if __name__=="__main__": main()
