import json, zipfile, requests
from pathlib import Path

import houseprice_apk_probe as hp

WORK=Path("/tmp/5168-rent-decompile")
WORK.mkdir(exist_ok=True)
XAPK=WORK/"5168.xapk"
OUT=Path("docs/preview/houseprice-rent-apk-probe.json")

if not XAPK.exists():
    with requests.get(
        hp.DOWNLOAD,
        headers={"User-Agent":"Mozilla/5.0"},
        stream=True,
        timeout=90,
        allow_redirects=True,
    ) as rr:
        rr.raise_for_status()
        with XAPK.open("wb") as f:
            for chunk in rr.iter_content(1024*1024):
                if chunk:
                    f.write(chunk)

unpack=WORK/"xapk"
unpack.mkdir(exist_ok=True)
with zipfile.ZipFile(XAPK) as z:
    z.extractall(unpack)

apk=next((p for p in unpack.rglob("*.apk") if p.name=="com.houseprice.hp5168.apk"),None)
if not apk:
    apk=next(iter(unpack.rglob("*.apk")),None)
if not apk:
    raise SystemExit("APK not found")

from loguru import logger
logger.remove()
from androguard.misc import AnalyzeAPK

needles=[
    "/api/{kind}/List",
    "ForRentCard",
    "MonthlyRentalCard",
    "SearchHouseListRequest",
    "RentDeal",
    "CommunityForRent",
    "rent",
    "Rent",
]
out={"apk":apk.name,"matches":[],"xrefs":{}}

try:
    a,d,dx=AnalyzeAPK(str(apk))
    dexes=d if isinstance(d,list) else [d]
    for dex in dexes:
        for cls in dex.get_classes():
            cname=cls.get_name()
            if "houseprice/hp5168" not in cname:
                continue
            for m in cls.get_methods():
                try:
                    code=m.get_code()
                    if not code:
                        continue
                    strings=[]
                    outputs=[]
                    for insn in code.get_bc().get_instructions():
                        name=insn.get_name()
                        output=insn.get_output()
                        outputs.append(f"{name} {output}")
                        if "string" in name:
                            strings.append(output)
                    joined="\n".join(strings)
                    interesting=(
                        any(n in joined for n in needles)
                        or "Rent" in cname
                        or "ForRent" in cname
                        or "Rent" in m.get_name()
                        or "ForRent" in m.get_name()
                    )
                    if interesting:
                        out["matches"].append({
                            "class":cname,
                            "method":m.get_name(),
                            "descriptor":m.get_descriptor(),
                            "strings":strings[:200],
                            "instructions":[x for x in outputs if any(n in x for n in needles)][:120],
                        })
                except Exception:
                    pass

    # String xrefs are useful for locating Retrofit path annotations and the
    # code that supplies the dynamic {kind} path parameter.
    strings=getattr(dx,"strings",{}) or {}
    for needle in needles:
        sa=strings.get(needle)
        if not sa:
            continue
        refs=[]
        try:
            for c,m in sa.get_xref_from():
                refs.append({"class":c.name,"method":m.name,"descriptor":m.descriptor})
        except Exception:
            pass
        out["xrefs"][needle]=refs
except Exception as e:
    out["analyzeError"]=f"{type(e).__name__}: {e}"

OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({
    "apk":out.get("apk"),
    "matchCount":len(out.get("matches") or []),
    "xrefs":out.get("xrefs"),
    "analyzeError":out.get("analyzeError"),
    "samples":(out.get("matches") or [])[:12],
},ensure_ascii=False))
