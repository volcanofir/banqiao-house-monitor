import json, re, subprocess, zipfile, requests
from pathlib import Path
import houseprice_apk_probe as hp

WORK=Path("/tmp/5168-rent-decompile"); WORK.mkdir(exist_ok=True)
XAPK=WORK/"5168.xapk"

if not XAPK.exists():
    with requests.get(hp.DOWNLOAD,headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=90,allow_redirects=True) as rr:
        rr.raise_for_status()
        with XAPK.open("wb") as f:
            for chunk in rr.iter_content(1024*1024):
                if chunk:
                    f.write(chunk)

unpack=WORK/"xapk"; unpack.mkdir(exist_ok=True)
with zipfile.ZipFile(XAPK) as z:
    z.extractall(unpack)

apk=next((p for p in unpack.rglob("*.apk") if p.name=="com.houseprice.hp5168.apk"),None) or next(iter(unpack.rglob("*.apk")))

# 1) Keep the lightweight Androguard inventory.
from loguru import logger
logger.remove()
from androguard.misc import AnalyzeAPK
a,d,dx=AnalyzeAPK(str(apk))
dexes=d if isinstance(d,list) else [d]

result={"apiService":[],"rentMethods":[],"rentFields":[],"apiInvocations":[],"retrofitBlocks":{}}
for dex in dexes:
    for cls in dex.get_classes():
        cname=cls.get_name()
        if "houseprice/hp5168" not in cname:
            continue

        if cname.endswith("/ApiService;"):
            for m in cls.get_methods():
                result["apiService"].append({"name":m.get_name(),"descriptor":m.get_descriptor()})

        if any(x in cname for x in ["ForRent","MonthlyRental","CommunityForRent","RentDeal"]):
            fields=[]
            try:
                for f in cls.get_fields():
                    fields.append({"name":f.get_name(),"descriptor":f.get_descriptor()})
            except Exception:
                pass
            if fields:
                result["rentFields"].append({"class":cname,"fields":fields})
            for m in cls.get_methods():
                result["rentMethods"].append({"class":cname,"name":m.get_name(),"descriptor":m.get_descriptor()})

# 2) Decompile with apktool so Retrofit annotations are visible.
smali_dir=WORK/"apktool"
subprocess.run(
    ["apktool","d","-r","-f","-o",str(smali_dir),str(apk)],
    check=True,capture_output=True,text=True,timeout=240
)
api_files=list(smali_dir.rglob("ApiService.smali"))
if not api_files:
    raise RuntimeError("ApiService.smali not found after apktool decompile")

api_text=api_files[0].read_text(encoding="utf-8",errors="ignore")
targets=[
    "getCommunityForRent",
    "getCommunityForSale",
    "getNewList",
    "getFocusList",
    "getCaseRecommendList",
    "getSearchHouseListResult",
    "getSearchResultCount",
]
for name in targets:
    # Capture the complete smali method, including Retrofit method/parameter annotations.
    m=re.search(r"(?ms)^\.method[^\n]*\b"+re.escape(name)+r"\([^\n]*\n.*?^\.end method\s*$", api_text)
    if m:
        block=m.group(0)
        result["retrofitBlocks"][name]=block[:24000]

# Also extract all obvious endpoint/path strings from ApiService.smali.
paths=sorted(set(re.findall(r'"(/api/[^"]+)"',api_text)))
result["apiPaths"]=paths
result["apiServiceSmaliPath"]=str(api_files[0].relative_to(smali_dir))

print(json.dumps(result,ensure_ascii=False))
