import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("docs/preview/yungching-api-diagnostic.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}
TARGETS = [
    "https://www.yungching.com.tw/api/v1/common/version",
    "https://www.yungching.com.tw/",
    "https://buy.yungching.com.tw/",
    "https://buy.yungching.com.tw/list/新北市-板橋區_c/中山路二段_kw?od=80",
]

API_PATTERNS = [
    re.compile(r"https?://[A-Za-z0-9._:-]*yungching\.com\.tw[^\"'`\\\s<>]+", re.I),
    re.compile(r"(?<![A-Za-z0-9_])(/api/(?:v\d+/)?[A-Za-z0-9_?&=./%{}:-]+)", re.I),
]


def get(session, url, timeout=20):
    try:
        r = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "url": url,
            "status": r.status_code,
            "finalUrl": r.url,
            "contentType": r.headers.get("content-type"),
            "length": len(r.content),
            "text": r.text if len(r.text) <= 2_000_000 else r.text[:2_000_000],
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


def main():
    session = requests.Session()
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

    probes = []
    for url in sorted(candidates):
        if len(probes) >= 80:
            break
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc.endswith("yungching.com.tw"):
            continue
        # Only probe concrete GET-like URLs; skip templates/placeholders.
        if any(ch in url for ch in "{}<>"):
            continue
        item = get(session, url, timeout=12)
        probes.append({k: v for k, v in item.items() if k != "text"})

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "preview_diagnostic",
        "checks": checks,
        "scriptCount": len(scripts),
        "scripts": script_results,
        "candidateCount": len(candidates),
        "candidates": sorted(candidates)[:300],
        "probes": probes,
        "note": "只偵測永慶公開頁面/公開前端資源中出現的 API URL，未使用登入或內部系統。",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "checks": checks,
        "scriptCount": len(scripts),
        "candidateCount": len(candidates),
        "probeCount": len(probes),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
