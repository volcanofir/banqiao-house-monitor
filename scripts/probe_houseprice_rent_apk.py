import json, re, subprocess, sys, zipfile, tempfile, requests
from pathlib import Path

# Reuse the known XAPK URL from houseprice_apk_probe.py
import houseprice_apk_probe as hp

work=Path("/tmp/5168-rent-decompile")
work.mkdir(exist_ok=True)
xapk=work/"5168.xapk"
if not xapk.exists():
    with requests.get(hp.DOWNLOAD,headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=90,allow_redirects=True) as rr:
        rr.raise_for_status()
        with xapk.open("wb") as f:
            for chunk in rr.iter_content(1024*1024):
                if chunk:
                    f.write(chunk)

with zipfile.ZipFile(xapk) as z:
    z.extractall(work/"xapk")
apk=next((p for p in (work/"xapk").rglob("*.apk") if p.name=="com.houseprice.hp5168.apk"),None)
if not apk:
    apk=next((p for p in (work/"xapk").rglob("*.apk")),None)
if not apk:
    raise SystemExit("APK not found")

from androguard.misc import AnalyzeAPK
a,d,dx=AnalyzeAPK(str(apk))
needles=["/api/{kind}/List","ForRentCard","MonthlyRentalCard","SearchHouseListRequest","RentDeal","CommunityForRent"]
out={"apk":apk.name,"matches":[]}

for cls in d.get_classes():
    cname=cls.get_name()
    if "houseprice/hp5168" not in cname:
        continue
    for m in cls.get_methods():
        try:
            code=m.get_code()
            if not code: continue
            ins=list(code.get_bc().get_instructions())
            strings=[]
            for insn in ins:
                s=insn.get_output()
                if "string" in insn.get_name():
                    strings.append(s)
            joined="\n".join(strings)
            if any(n in joined for n in needles) or any(n in cname or n in m.get_name() for n in ["Rent","ForRent"]):
                out["matches"].append({
                    "class":cname,
                    "method":m.get_name(),
                    "descriptor":m.get_descriptor(),
                    "strings":strings[:120],
                })
        except Exception:
            pass

# Also inspect xrefs for exact interesting strings
for needle in needles:
    try:
        sa=dx.strings.get(needle)
        if sa:
            refs=[]
            for c,m in sa.get_xref_from():
                refs.append({"class":c.name,"method":m.name,"descriptor":m.descriptor})
            out.setdefault("xrefs",{})[needle]=refs
    except Exception as e:
        out.setdefault("errors",[]).append(f"{needle}: {e}")

print(json.dumps(out,ensure_ascii=False))
