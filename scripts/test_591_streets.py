import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://m.591.com.tw/v2/sale"
ROADS = {
    "中山路二段": "27507",
    "三民路二段": "27485",
    "光復街": "27550",
    "萬安街": "27630",
    "林森街": "27574",
    "三民路一段": "27484",
    "翠華街": "27644",
}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://m.591.com.tw/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
}


def uniq(values):
    return list(dict.fromkeys(values))


def endpoint_candidates(text):
    patterns = [
        r'["\'](https?://[^"\']{5,220})["\']',
        r'["\']([^"\']*(?:api|ajax|search|list)[^"\']{0,180})["\']',
    ]
    found = []
    for pattern in patterns:
        for value in re.findall(pattern, text, re.I):
            value = value.replace('\\/', '/')
            if any(token in value.lower() for token in ("api", "ajax", "search", "list", "sale")):
                found.append(value)
    return uniq(found)[:25]


def inspect_html(session, road, streetid):
    params = {
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": streetid,
        "keywords": road,
    }
    response = session.get(BASE, params=params, headers=HEADERS, timeout=30)
    body = response.text
    soup = BeautifulSoup(body, "html.parser")

    house_ids = uniq(re.findall(r'house(?:_?id)?[^0-9]{0,20}(\d{5,})', body, re.I))
    detail_ids = uniq(re.findall(r'(?:detail/\d/|/home/|/sale/)(\d{5,})', body, re.I))
    all_numeric_hrefs = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r'(\d{5,})', href)
        if m:
            all_numeric_hrefs.append(m.group(1))
    all_numeric_hrefs = uniq(all_numeric_hrefs)

    script_sources = [urljoin(response.url, s.get("src")) for s in soup.find_all("script", src=True)]
    inline_scripts = [s.get_text("", strip=False) for s in soup.find_all("script") if not s.get("src")]
    inline_text = "\n".join(inline_scripts)

    print("=" * 90)
    print(f"ROAD={road} streetid={streetid}")
    print(f"HTTP={response.status_code} bytes={len(body)} final_url={response.url}")
    print(f"title={(soup.title.get_text(' ', strip=True) if soup.title else '-')[:120]}")
    print(f"houseid_tokens={len(house_ids)} sample={house_ids[:10]}")
    print(f"detail_ids={len(detail_ids)} sample={detail_ids[:10]}")
    print(f"numeric_href_ids={len(all_numeric_hrefs)} sample={all_numeric_hrefs[:10]}")
    print(f"scripts={len(script_sources)} inline_scripts={len(inline_scripts)}")

    next_data = soup.find("script", id="__NEXT_DATA__")
    print(f"__NEXT_DATA__={'yes' if next_data else 'no'}")
    print(f"inline_endpoint_candidates={json.dumps(endpoint_candidates(inline_text), ensure_ascii=False)}")

    return {
        "road": road,
        "streetid": streetid,
        "status": response.status_code,
        "bytes": len(body),
        "house_ids": house_ids,
        "detail_ids": detail_ids,
        "numeric_href_ids": all_numeric_hrefs,
        "script_sources": script_sources,
        "inline_endpoints": endpoint_candidates(inline_text),
    }


def inspect_js(session, script_sources):
    print("=" * 90)
    print("JS BUNDLE ENDPOINT SCAN")
    seen = set()
    checked = 0
    for src in script_sources:
        if src in seen or checked >= 20:
            continue
        seen.add(src)
        checked += 1
        try:
            r = session.get(src, headers=HEADERS, timeout=20)
        except Exception as exc:
            print(f"JS_FAIL {src} :: {exc}")
            continue
        if r.status_code != 200:
            print(f"JS_HTTP_{r.status_code} {src}")
            continue
        candidates = endpoint_candidates(r.text)
        strong = [
            x for x in candidates
            if any(k in x.lower() for k in ("search/list", "sale/list", "ajax", "/api/", "house"))
        ]
        if strong:
            print(f"JS={src}")
            for item in strong[:15]:
                print("  ", item[:300])
    print(f"checked_js={checked}")


def main():
    session = requests.Session()
    results = []
    scripts = []
    for road, streetid in ROADS.items():
        try:
            result = inspect_html(session, road, streetid)
            results.append(result)
            scripts.extend(result["script_sources"])
        except Exception as exc:
            print("=" * 90)
            print(f"ROAD={road} streetid={streetid} ERROR={exc}")

    inspect_js(session, uniq(scripts))

    print("=" * 90)
    print("SUMMARY")
    for result in results:
        print(
            f"{result['road']}({result['streetid']}): HTTP {result['status']}, "
            f"bytes {result['bytes']}, houseid {len(result['house_ids'])}, "
            f"detail {len(result['detail_ids'])}, href-id {len(result['numeric_href_ids'])}"
        )


if __name__ == "__main__":
    main()
