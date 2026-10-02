import hashlib,json,os,re,subprocess,urllib.parse,zipfile
from pathlib import Path
import requests

OUT=Path("docs/preview/houseprice-apk-endpoints.json")
XAPK=Path("/tmp/5168.xapk")
WORK=Path("/tmp/5168-xapk")
DOWNLOAD="https://download.pureapk.com/b/XAPK/Y29tLmhvdXNlcHJpY2UuaHA1MTY4XzQ2XzE1YzEzMGVk?_fn=NTE2OCVFNSVBRiVBNiVFNSU4MyVCOSVFNyU5OSVCQiVFOSU4QyU4NCVFNiVBRiU5NCVFNSU4MyVCOSVFNyU4RSU4Ql80LjAuMV9hcGtjb21iby5jb20ueGFwaw%3D%3D&_p=Y29tLmhvdXNlcHJpY2UuaHA1MTY4&as2=5104a21d4bcda90301b776cb08d3d78c6c8b01bd&c=1%7CHOUSE_AND_HOME%7Cb2lkPTkmZGV2PTUxNjglMjAlRTUlQUYlQTYlRTUlODMlQjklRTclOTklQkIlRTklOEMlODQlRTYlQUYlOTQlRTUlODMlQjklRTclOEUlOEImdD14YXBrJnM9MTgzNjU2ODcmdm49NC4wLjEmdmM9NDY&k=6d3bda1476728eb695e9a51d47b3a72b6c8b01bd"

def extract_strings(path):
    try:
        p=subprocess.run(["strings","-a",str(path)],capture_output=True,text=True,timeout=60)
        return p.stdout
    except Exception:
        return ""

def main():
    h={"User-Agent":"Mozilla/5.0"}
    with requests.get(DOWNLOAD,headers=h,stream=True,timeout=60,allow_redirects=True) as r:
        r.raise_for_status()
        with XAPK.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:f.write(chunk)
    sha=hashlib.sha256(XAPK.read_bytes()).hexdigest()
    WORK.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(XAPK) as z:z.extractall(WORK)

    apk_files=list(WORK.rglob("*.apk"))
    scan_files=[]
    for apk in apk_files:
        adir=WORK/(apk.stem+"_unzipped")
        adir.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(apk) as z:
                for n in z.namelist():
                    if re.search(r"(classes\d*\.dex|resources\.arsc|assets/|res/raw/|lib/.+\.so$)",n):
                        try:z.extract(n,adir)
                        except:pass
        except:pass
        scan_files.extend([p for p in adir.rglob("*") if p.is_file()])

    text_parts=[]
    for f in scan_files:
        s=extract_strings(f)
        if s:text_parts.append(s)
    blob="\n".join(text_parts)

    urls=sorted(set(re.findall(r'https?://[^\s"\'<>\\]{6,300}',blob)))
    urls=[u.rstrip("),.;]") for u in urls]
    domains=sorted(set(re.findall(r'(?i)(?:[a-z0-9-]+\.)+houseprice\.tw',blob)))
    api_lines=[]
    for line in blob.splitlines():
        low=line.lower()
        if ("houseprice.tw" in low or "/ws/" in low or "api" in low or "buygetwebcase" in low or "buycaselist" in low):
            line=line.strip()
            if 4<=len(line)<=500:
                api_lines.append(line)
    api_lines=sorted(set(api_lines))

    interesting_urls=[u for u in urls if any(k in u.lower() for k in ["houseprice","/ws/","api","buy","case","search"])]
    decompile={}
    base_apk=next((x for x in apk_files if x.name=="com.houseprice.hp5168.apk"),None)
    if base_apk and subprocess.run(["bash","-lc","command -v apktool >/dev/null 2>&1"]).returncode==0:
        ddir=Path("/tmp/5168-apktool")
        subprocess.run(["apktool","d","-r","-f","-o",str(ddir),str(base_apk)],capture_output=True,text=True,timeout=240)
        wanted=["ApiService.smali","SearchHouseListRequest.smali","SearchRequest.smali","SearchCountResult.smali","SearchHouseListResult.smali"]
        found={}
        for name in wanted:
            for fp in ddir.rglob(name):
                try:
                    txt=fp.read_text(encoding="utf-8",errors="ignore")
                    found[name]={"path":str(fp.relative_to(ddir)),"content":txt[:60000]}
                    break
                except Exception:
                    pass
        decompile=found

    result={
      "package":"com.houseprice.hp5168",
      "version":"4.0.1",
      "xapkBytes":XAPK.stat().st_size,
      "sha256":sha,
      "apkFiles":[str(x.relative_to(WORK)) for x in apk_files],
      "housepriceDomains":domains,
      "interestingUrls":interesting_urls[:500],
      "interestingStrings":api_lines[:1000],
      "decompile":decompile,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"bytes":result["xapkBytes"],"sha256":sha,"apkCount":len(apk_files),"domains":domains,"urlCount":len(interesting_urls),"stringCount":len(api_lines)},ensure_ascii=False))

if __name__=="__main__":main()
