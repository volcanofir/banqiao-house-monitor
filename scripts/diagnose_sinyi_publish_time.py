import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path("docs/data/listings.json")
OUT_PATH = Path("docs/data/sinyi-publish-time-diagnostic.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}

TIME_KEY = re.compile(r"(publish|published|create|created|update|updated|online|listed|listing|open|start|date|time)", re.I)
TIME_VALUE = re.compile(
    r"(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?|"
    r"1[6-9]\d{8}|2\d{9}|1[6-9]\d{11}|2\d{12})"
)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def scalar(v):
    return isinstance(v, (str, int, float, bool)) or v is None


def walk(obj, path="$", out=None, depth=0):
    if out is None:
        out = []
    if depth > 16:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if TIME_KEY.search(str(k)) and scalar(v):
                out.append({"path": p, "key": str(k), "value": v})
            elif scalar(v) and isinstance(v, str) and TIME_VALUE.search(v):
                out.append({"path": p, "key": str(k), "value": v, "matchedByValue": True})
            walk(v, p, out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:500]):
            walk(v, f"{path}[{i}]", out, depth + 1)
    return out


def normalize_candidates(items):
    seen = set()
    out = []
    for item in items:
        key = (str(item.get("path")), str(item.get("value")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:300]


def extract_json_scripts(html):
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        sid = script.get("id")
        stype = script.get("type")
        if not text.strip():
            continue
        if sid == "__NEXT_DATA__" or stype in {"application/json", "application/ld+json"}:
            try:
                blocks.append({"id": sid, "type": stype, "json": json.loads(text)})
            except Exception:
                pass
    return blocks


def html_time_snippets(html):
    snippets = []
    lower = html.lower()
    terms = ["publishtime", "publishdate", "publish_time", "publish_date", "createdate", "createtime", "updatedate", "updatetime", "onlinedate", "listeddate", "上架", "刊登"]
    for term in terms:
        start = 0
        while True:
            idx = lower.find(term.lower(), start)
            if idx < 0:
                break
            snippets.append(html[max(0, idx - 100): min(len(html), idx + 220)].replace("\n", " "))
            start = idx + len(term)
            if len(snippets) >= 80:
                return snippets
    return snippets


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    return r.status_code, r.url, r.text


def search_list_record(house_id, road):
    keyword = (road or "板橋區中山路二段").replace("板橋區", "")
    url = f"https://www.sinyi.com.tw/buy/list/NewTaipei-city/220-zip/{quote(keyword)}-keyword/publish-desc/1"
    status, final_url, html = fetch(url)
    result = {"url": url, "status": status, "finalUrl": final_url, "recordFound": False, "timeCandidates": []}
    if status != 200:
        return result
    for block in extract_json_scripts(html):
        data = block["json"]
        try:
            reducer = (((data.get("props") or {}).get("initialReduxState") or {}).get("buyReducer") or {})
            rows = reducer.get("list") or []
        except Exception:
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if str(row.get("houseNo") or "") == str(house_id):
                result["recordFound"] = True
                result["rawRecord"] = row
                result["timeCandidates"] = normalize_candidates(walk(row))
                return result
    return result


def diagnose_item(item):
    house_id = item.get("houseId") or str(item.get("id") or "").split(":", 1)[-1]
    detail_url = item.get("url") or f"https://www.sinyi.com.tw/buy/house/{quote(str(house_id))}?breadcrumb=list"
    report = {
        "houseId": house_id,
        "title": item.get("title"),
        "road": item.get("road"),
        "currentStoredPostTime": item.get("postTime"),
        "currentSourcePublishedAt": item.get("sourcePublishedAt"),
        "currentSourcePublishedAtType": item.get("sourcePublishedAtType"),
        "detail": {"url": detail_url},
    }

    try:
        status, final_url, html = fetch(detail_url)
        report["detail"].update({"status": status, "finalUrl": final_url, "htmlBytes": len(html.encode("utf-8"))})
        json_blocks = extract_json_scripts(html)
        candidates = []
        block_summaries = []
        for i, block in enumerate(json_blocks):
            found = normalize_candidates(walk(block["json"]))
            candidates.extend(found)
            block_summaries.append({
                "index": i,
                "id": block.get("id"),
                "type": block.get("type"),
                "timeCandidates": found[:100],
            })
        report["detail"]["jsonBlocks"] = block_summaries
        report["detail"]["timeCandidates"] = normalize_candidates(candidates)
        report["detail"]["htmlTimeSnippets"] = html_time_snippets(html)
    except Exception as exc:
        report["detail"]["error"] = f"{type(exc).__name__}: {exc}"

    try:
        report["listPage"] = search_list_record(house_id, item.get("road"))
    except Exception as exc:
        report["listPage"] = {"error": f"{type(exc).__name__}: {exc}"}
    return report


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    sinyi = [x for x in state.get("listings", []) if x.get("source") == "信義房屋" and x.get("active", True)]
    # Sample across the current set instead of relying on one property/page shape.
    samples = sinyi[:12]
    results = [diagnose_item(item) for item in samples]

    summary = {
        "checkedAt": now_iso(),
        "sampleCount": len(results),
        "detailPages200": sum(1 for x in results if x.get("detail", {}).get("status") == 200),
        "listRecordsFound": sum(1 for x in results if x.get("listPage", {}).get("recordFound")),
        "detailPagesWithTimeCandidates": sum(1 for x in results if x.get("detail", {}).get("timeCandidates")),
        "listRecordsWithTimeCandidates": sum(1 for x in results if x.get("listPage", {}).get("timeCandidates")),
        "productionDataModified": False,
    }
    output = {"summary": summary, "results": results}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {OUT_PATH}")


if __name__ == "__main__":
    main()
