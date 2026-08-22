import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as dom


OUT = Path("docs/preview/yungching-pagination-probe.json")
ROAD = "板橋區中山路二段"
BASE = "https://buy.yungching.com.tw"


def base_url():
    return f"{BASE}/list/{quote('新北市-板橋區')}_c/{quote('中山路二段')}_kw"


def collect_ids(page):
    # Let the actual result cards render, then use the same conservative DOM parser
    # as the Preview company snapshot so candidate URLs are compared apples-to-apples.
    page.wait_for_timeout(3000)
    for ratio in (0.5, 1.0):
        page.evaluate("r => window.scrollTo(0, document.body.scrollHeight * r)", ratio)
        page.wait_for_timeout(800)
    raw = dom.extract_cards(page, ROAD)
    ids = []
    for item in raw.get("cards") or []:
        row = dom.parse_card(item, ROAD)
        if row:
            ids.append(str(row["id"]))
    return sorted(set(ids))


def main():
    root = base_url()
    candidates = [
        ("baseline", f"{root}?od=80"),
        ("pg", f"{root}?od=80&pg=2"),
        ("page", f"{root}?od=80&page=2"),
        ("p", f"{root}?od=80&p=2"),
        ("pn", f"{root}?od=80&pn=2"),
        ("pi", f"{root}?od=80&pi=2"),
        ("path-2", f"{root}/2?od=80"),
        ("path-p2", f"{root}/p2?od=80"),
    ]

    result = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "road": ROAD,
        "candidates": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        baseline = set()
        for name, url in candidates:
            info = {"name": name, "url": url, "http": None, "count": 0}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=40000)
                info["http"] = response.status if response else None
                info["finalUrl"] = page.url
                info["title"] = page.title()[:120]
                ids = collect_ids(page)
                info["count"] = len(ids)
                info["ids"] = ids[:45]
                if name == "baseline":
                    baseline = set(ids)
                    info["newVsBaseline"] = 0
                    info["overlapBaseline"] = len(ids)
                else:
                    current = set(ids)
                    info["newVsBaseline"] = len(current - baseline)
                    info["overlapBaseline"] = len(current & baseline)
                    info["looksLikePage2"] = bool(
                        info["http"] == 200
                        and len(current) >= 1
                        and len(current - baseline) >= 3
                        and len(current & baseline) < max(5, int(len(current) * 0.75))
                    )
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            result["candidates"].append(info)
            print(name, info.get("http"), info.get("count"), info.get("newVsBaseline"), info.get("finalUrl"))

        browser.close()

    result["likelyPage2"] = [x["name"] for x in result["candidates"] if x.get("looksLikePage2")]
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"likelyPage2": result["likelyPage2"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
