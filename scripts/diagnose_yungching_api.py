import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("docs/preview/yungching-api-diagnostic.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://buy.yungching.com.tw/list/%E6%96%B0%E5%8C%97%E5%B8%82-%E6%9D%BF%E6%A9%8B%E5%8D%80_c/%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5_kw?pg=2",
    "Cache-Control": "no-cache",
}
LIST_URL = (
    "https://buy.yungching.com.tw/api/v2/list?"
    "area=%E6%96%B0%E5%8C%97%E5%B8%82-%E6%9D%BF%E6%A9%8B%E5%8D%80"
    "&pinType=0&isAddRoom=true"
    "&keyword=%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5"
    "&filter=0&pg=2&ps=30"
)
TARGETS = [
    "https://www.yungching.com.tw/api/v1/common/version",
    "https://www.yungching.com.tw/",
    "https://buy.yungching.com.tw/",
    "https://buy.yungching.com.tw/list/新北市-板橋區_c/中山路二段_kw?od=80",
]

# These exact frontend bundle URLs were observed in the user's HAR initiator stacks.
FRONTEND_BUNDLES = [
    "https://buy.yungching.com.tw/mansion/main-ZNWPTI42.js",
    "https://buy.yungching.com.tw/mansion/chunk-MF2WPFIH.js",
    "https://buy.yungching.com.tw/mansion/chunk-3IKAXKWR.js",
    "https://buy.yungching.com.tw/mansion/chunk-3PH2YWOD.js",
    "https://buy.yungching.com.tw/mansion/chunk-4VPZXZT6.js",
    "https://buy.yungching.com.tw/mansion/chunk-6ATXNMP2.js",
    "https://buy.yungching.com.tw/mansion/chunk-6L7KAHDP.js",
    "https://buy.yungching.com.tw/mansion/chunk-A56WRQK4.js",
    "https://buy.yungching.com.tw/mansion/chunk-ARI4OJ6I.js",
    "https://buy.yungching.com.tw/mansion/chunk-BP2QEKMM.js",
    "https://buy.yungching.com.tw/mansion/chunk-BZNACKJH.js",
    "https://buy.yungching.com.tw/mansion/chunk-GXOG6DQ4.js",
    "https://buy.yungching.com.tw/mansion/chunk-H7GWVBCK.js",
    "https://buy.yungching.com.tw/mansion/chunk-NZO5ZNED.js",
    "https://buy.yungching.com.tw/mansion/chunk-P5YEMSDT.js",
    "https://buy.yungching.com.tw/mansion/chunk-PCETGO47.js",
    "https://buy.yungching.com.tw/mansion/chunk-UQGOQCUW.js",
    "https://buy.yungching.com.tw/mansion/chunk-WKRERN32.js",
    "https://buy.yungching.com.tw/mansion/chunk-YFWT6MF3.js",
    "https://buy.yungching.com.tw/mansion/chunk-ZHJY5Z23.js",
]

API_PATTERNS = [
    re.compile(r"https?://[A-Za-z0-9._:-]*yungching\.com\.tw[^\"'`\\\s<>]+", re.I),
    re.compile(r"(?<![A-Za-z0-9_])(/api/(?:v\d+/)?[A-Za-z0-9_?&=./%{}:-]+)", re.I),
]
CRYPTO_TERMS = [
    "/api/v2/list", "decrypt", "AES", "CryptoJS", "atob", "Base64", "base64",
    "CBC", "ECB", "Pkcs7", "Utf8", "enc.Utf8", "createDecipher", "subtle.decrypt",
]


def get(session, url, timeout=20, headers=None):
    try:
        r = session.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "url": url,
            "status": r.status_code,
            "finalUrl": r.url,
            "contentType": r.headers.get("content-type"),
            "length": len(r.content),
            "text": r.text if len(r.text) <= 3_000_000 else r.text[:3_000_000],
        }
    except Exception as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"}


def extract_candidates(text, base_url):
    out = set()
    for pattern in API_PATTERNS:
        for m in pattern.finditer(text or ""):
            value = m.group(0)
            if value.startswith("/"):
                value = urljoin(base_url, value)
            value = value.rstrip("),;]}\\")
            if any(x in value.lower() for x in ("api", "house", "list", "search", "object")):
                out.add(value)
    return sorted(out)


def inspect_list_response(item):
    summary = {k: v for k, v in item.items() if k != "text"}
    text = item.get("text") or ""
    if item.get("status") != 200:
        summary["bodyPrefix"] = text[:180]
        return summary
    try:
        obj = json.loads(text)
    except Exception as exc:
        summary["jsonError"] = str(exc)
        summary["bodyPrefix"] = text[:180]
        return summary
    summary["apiStatus"] = obj.get("status")
    summary["method"] = obj.get("method")
    data = obj.get("data")
    summary["dataType"] = type(data).__name__
    if isinstance(data, str):
        summary["dataChars"] = len(data)
        summary["dataPrefix"] = data[:32]
        try:
            raw = base64.b64decode(data, validate=True)
            summary["base64Valid"] = True
            summary["decodedBytes"] = len(raw)
            summary["decodedMod16"] = len(raw) % 16
            summary["decodedPrefixHex"] = raw[:16].hex()
        except Exception as exc:
            summary["base64Valid"] = False
            summary["base64Error"] = str(exc)
    return summary


def compact_snippet(text, pos, radius=260):
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    return re.sub(r"\s+", " ", text[start:end])


def inspect_bundle(item):
    summary = {k: v for k, v in item.items() if k != "text"}
    text = item.get("text") or ""
    hits = []
    if item.get("status") == 200 and text:
        for term in CRYPTO_TERMS:
            pos = text.find(term)
            if pos >= 0:
                hits.append({"term": term, "position": pos, "snippet": compact_snippet(text, pos)})
        # Candidate literal keys/IVs near crypto-related code. We only record literals; no secrets/cookies are involved.
        literal_candidates = []
        for m in re.finditer(r"[\"']([A-Za-z0-9_\-+/=.!@#$%^&*]{16}|[A-Za-z0-9_\-+/=.!@#$%^&*]{24}|[A-Za-z0-9_\-+/=.!@#$%^&*]{32})[\"']", text):
            value = m.group(1)
            nearby = text[max(0, m.start()-350):min(len(text), m.end()+350)].lower()
            if any(k.lower() in nearby for k in ("aes", "decrypt", "encrypt", "iv", "key", "utf8", "base64")):
                literal_candidates.append({"value": value, "position": m.start()})
            if len(literal_candidates) >= 30:
                break
        summary["literalCandidates"] = literal_candidates
    summary["cryptoHits"] = hits
    return summary


def main():
    session = requests.Session()

    list_item = get(session, LIST_URL, timeout=25, headers=HEADERS)
    list_api_test = inspect_list_response(list_item)

    checks = []
    html_sources = []
    for url in TARGETS:
        item = get(session, url)
        checks.append({k: v for k, v in item.items() if k != "text"})
        if item.get("status") == 200 and "html" in str(item.get("contentType", "")).lower():
            html_sources.append(item)

    scripts = []
    candidates = set()
    for src_item in html_sources:
        base = src_item.get("finalUrl") or src_item["url"]
        html = src_item.get("text", "")
        candidates.update(extract_candidates(html, base))
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.select("script[src]"):
            src = urljoin(base, tag.get("src") or "")
            host = urlparse(src).netloc.lower()
            if host.endswith("yungching.com.tw") and src not in scripts:
                scripts.append(src)

    script_results = []
    for src in scripts[:40]:
        item = get(session, src, timeout=25)
        summary = {k: v for k, v in item.items() if k != "text"}
        found = []
        if item.get("status") == 200:
            found = extract_candidates(item.get("text", ""), item.get("finalUrl") or src)
            candidates.update(found)
        summary["candidateCount"] = len(found)
        summary["candidates"] = found[:80]
        script_results.append(summary)

    bundle_results = []
    for src in FRONTEND_BUNDLES:
        item = get(session, src, timeout=25, headers=HEADERS)
        bundle_results.append(inspect_bundle(item))

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "preview_diagnostic",
        "listApiTest": list_api_test,
        "checks": checks,
        "scriptCount": len(scripts),
        "scripts": script_results,
        "candidateCount": len(candidates),
        "candidates": sorted(candidates)[:300],
        "frontendBundleProbe": bundle_results,
        "note": "PREVIEW only. Frontend bundle URLs come from the user's public-site HAR initiator stacks; no login/internal system is used.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "listApiTest": list_api_test,
        "checks": checks,
        "bundleStatuses": [{"url": x.get("url"), "status": x.get("status"), "length": x.get("length"), "hits": [h["term"] for h in x.get("cryptoHits", [])]} for x in bundle_results],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
