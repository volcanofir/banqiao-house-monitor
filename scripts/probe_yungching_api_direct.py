import base64
import hashlib
import json
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROAD = "中山路二段"
AREA = "新北市-板橋區"
BASE = "https://buy.yungching.com.tw"
LIST_PAGE = f"{BASE}/list/{quote(AREA)}_c/{quote(ROAD)}_kw?od=80"
API = f"{BASE}/api/v2/list"

def derive():
    password = hashlib.sha256(b"YungChing.Buy").digest()
    salt = bytes([2, 7, 0, 5, 1, 3, 8, 0])
    dk = hashlib.pbkdf2_hmac("sha1", password, salt, 1000, 48)
    return dk[:32], dk[32:48]

def decrypt_data(value):
    key, iv = derive()
    ct = base64.b64decode(value)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    raw = unpad.update(padded) + unpad.finalize()
    return json.loads(raw.decode("utf-8"))

def fetch_page(session, pg):
    params = {
        "area": AREA,
        "pinType": 0,
        "isAddRoom": "true",
        "keyword": ROAD,
        "filter": 0,
        "pg": pg,
        "ps": 30,
    }
    r = session.get(API, params=params, timeout=20)
    print("PAGE_HTTP", pg, r.status_code, r.url)
    r.raise_for_status()
    wrapper = r.json()
    print("WRAPPER", pg, {
        "status": wrapper.get("status"),
        "apiVersion": wrapper.get("apiVersion"),
        "method": wrapper.get("method"),
        "dataLen": len(str(wrapper.get("data") or "")),
    })
    if wrapper.get("status") != "Success" or not wrapper.get("data"):
        raise RuntimeError(f"bad wrapper page {pg}: {wrapper}")
    return decrypt_data(wrapper["data"])

def main():
    s = requests.Session()
    s.headers.update({
        "accept": "application/json, text/plain, */*",
        "referer": LIST_PAGE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    })
    p1 = fetch_page(s, 1)
    pages = int((p1.get("pa") or {}).get("totalPageCount") or 1)
    results = [p1]
    for pg in range(2, pages + 1):
        results.append(fetch_page(s, pg))

    rows = []
    for x in results:
        rows.extend(x.get("list") or [])
    uniq = {x.get("caseSId"): x for x in rows if x.get("caseSId") is not None}
    prefix = "新北市板橋區" + ROAD
    exact = [x for x in uniq.values() if str(x.get("address") or "").startswith(prefix)]
    exact.sort(key=lambda x: int(x.get("caseSId") or 0))

    out = {
        "road": ROAD,
        "pages": pages,
        "apiTotalCount": p1.get("totalCount"),
        "paTotalItemCount": (p1.get("pa") or {}).get("totalItemCount"),
        "rawRows": len(rows),
        "uniqueRows": len(uniq),
        "exactRoadRows": len(exact),
        "sample": [
            {
                "caseSId": x.get("caseSId"),
                "caseName": x.get("caseName"),
                "address": x.get("address"),
                "price": x.get("price"),
                "regArea": (x.get("pinInfo") or {}).get("regArea"),
                "floor": x.get("floorInfo"),
                "pattern": x.get("patternInfo"),
            }
            for x in exact[:8]
        ],
    }
    print("=== YC_DIRECT_API_RESULT ===")
    print(json.dumps(out, ensure_ascii=False))
    if len(exact) < 1:
        raise RuntimeError("No exact-road listings after decrypt/filter")

if __name__ == "__main__":
    main()
