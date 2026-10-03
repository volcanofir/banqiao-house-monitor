import json
import re
import requests

URL = "https://buy.yungching.com.tw/mansion/chunk-2ETE3COE.js"

def find_balanced_function(src: str, start: int):
    brace = src.find("{", start)
    if brace < 0:
        return None
    depth = 0
    in_s = None
    esc = False
    for i in range(brace, len(src)):
        c = src[i]
        if in_s:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_s:
                in_s = None
            continue
        if c in ("'", '"', "`"):
            in_s = c
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i+1]
    return None

r = requests.get(URL, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
print("HTTP", r.status_code, "LEN", len(r.text))
r.raise_for_status()
txt = r.text

exp = txt.rfind("export{")
if exp < 0:
    exp = txt.rfind("export {")
print("EXPORT_POS", exp)
print("EXPORT_TAIL", txt[max(0,exp-2500):])

tail = txt[exp:] if exp >= 0 else txt[-6000:]
mappings = {}
for target in ("q","s"):
    m = re.search(r"([A-Za-z_$][\w$]*)\s+as\s+"+re.escape(target)+r"(?:[,}])", tail)
    if m:
        mappings[target]=m.group(1)
print("MAPPINGS", json.dumps(mappings, ensure_ascii=False))

for target, local in mappings.items():
    positions=[]
    for needle in [f"async function {local}(",f"function {local}(",f"var {local}=",f"let {local}=",f"const {local}="]:
        pos=txt.find(needle)
        if pos>=0:
            positions.append((pos,needle))
    if positions:
        positions.sort()
        pos,needle=positions[0]
        fn=find_balanced_function(txt,pos)
        print(f"=== {target} LOCAL {local} POS {pos} NEEDLE {needle} ===")
        print(fn if fn else txt[max(0,pos-4000):pos+18000])
    else:
        print(f"=== {target} LOCAL {local} NOT_DIRECTLY_DEFINED ===")
        # Show all local occurrences to resolve alias chains.
        occ=[m.start() for m in re.finditer(r"\b"+re.escape(local)+r"\b",txt)]
        print("OCC", occ[:20])
        for p in occ[:8]:
            print(txt[max(0,p-1800):p+3500])

# Extra crypto-related context.
for needle in ["TextEncoder","TextDecoder","crypto.subtle","AES","SHA-256","decrypt","encrypt","derive","importKey"]:
    pos=txt.find(needle)
    if pos>=0:
        print(f"=== NEEDLE {needle} @ {pos} ===")
        print(txt[max(0,pos-2500):pos+7000])
