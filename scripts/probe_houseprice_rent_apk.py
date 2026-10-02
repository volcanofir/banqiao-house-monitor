import json, zipfile, requests
from pathlib import Path
import houseprice_apk_probe as hp

WORK=Path("/tmp/5168-rent-decompile"); WORK.mkdir(exist_ok=True)
XAPK=WORK/"5168.xapk"
if not XAPK.exists():
    with requests.get(hp.DOWNLOAD,headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=90,allow_redirects=True) as rr:
        rr.raise_for_status()
        with XAPK.open("wb") as f:
            for chunk in rr.iter_content(1024*1024):
                if chunk:f.write(chunk)
unpack=WORK/"xapk"; unpack.mkdir(exist_ok=True)
with zipfile.ZipFile(XAPK) as z:z.extractall(unpack)
apk=next((p for p in unpack.rglob("*.apk") if p.name=="com.houseprice.hp5168.apk"),None) or next(iter(unpack.rglob("*.apk")))

from loguru import logger
logger.remove()
from androguard.misc import AnalyzeAPK
a,d,dx=AnalyzeAPK(str(apk))
dexes=d if isinstance(d,list) else [d]

result={"apiService":[],"rentMethods":[],"rentFields":[],"apiInvocations":[]}
for dex in dexes:
  for cls in dex.get_classes():
    cname=cls.get_name()
    if "houseprice/hp5168" not in cname: continue

    if cname.endswith("/ApiService;"):
      for m in cls.get_methods():
        rec={"name":m.get_name(),"descriptor":m.get_descriptor()}
        try:
          rec["annotations"]=str(m.get_annotations())
        except Exception as e:
          rec["annotationsError"]=str(e)
        result["apiService"].append(rec)

    if any(x in cname for x in ["ForRent","MonthlyRental","CommunityForRent","RentDeal"]):
      fields=[]
      try:
        for f in cls.get_fields():
          fields.append({"name":f.get_name(),"descriptor":f.get_descriptor()})
      except Exception: pass
      if fields:
        result["rentFields"].append({"class":cname,"fields":fields})
      for m in cls.get_methods():
        result["rentMethods"].append({"class":cname,"name":m.get_name(),"descriptor":m.get_descriptor()})

    for m in cls.get_methods():
      try:
        code=m.get_code()
        if not code: continue
        ins=[f"{i.get_name()} {i.get_output()}" for i in code.get_bc().get_instructions()]
        hits=[x for x in ins if "ApiService;->" in x]
        if hits:
          # Only keep callsites that either invoke a rent-named API method or have
          # rent-related class/method context.
          if any("Rent" in x or "rent" in x for x in hits) or "Rent" in cname or "Rent" in m.get_name():
            consts=[x for x in ins if "const-string" in x]
            result["apiInvocations"].append({
              "class":cname,"method":m.get_name(),"descriptor":m.get_descriptor(),
              "calls":hits[:80],"constStrings":consts[:120]
            })
      except Exception: pass

print(json.dumps(result,ensure_ascii=False))
