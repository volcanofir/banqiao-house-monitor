"""Capture a tiny public format fingerprint of Yongching Angular TransferState values.

Diagnostic only. Saves at most short prefix/suffix samples of the public page's
serialized transfer value, never cookies/headers or full payloads.
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
import yungching_dom_snapshot as base

OUT = Path("docs/preview/yungching-ng-state-fingerprint.json")
ROAD = "板橋區中山路二段"


def fingerprint(value):
    s = str(value or "")
    c = Counter(s)
    return {
        "chars": len(s),
        "lengthMod4": len(s) % 4,
        "prefix": s[:180],
        "suffix": s[-100:],
        "distinctChars": len(c),
        "charSet": "".join(sorted(c)),
        "topChars": c.most_common(30),
        "punctuationCounts": {x: c.get(x, 0) for x in '{}[],:>+-_=/\\|;~!@#$%^&*()\"\''},
        "startsWith": s[:12],
    }


def extract(page):
    loc = page.locator("script#ng-state")
    if not loc.count(): return {"error": "ng-state missing"}
    state = json.loads(loc.first.text_content() or "{}")
    rows = []
    for k, v in state.items():
        if str(k).startswith("transfer-buy:/api/v2/"):
            rows.append({"key": str(k), "fingerprint": fingerprint(v)})
    return {"transferCount": len(rows), "transfers": rows}


def main():
    out = {"capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "previewOnly": True, "pages": {}}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = ctx.new_page()
        r = page.goto(base.road_url(ROAD), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        out["pages"]["search"] = {"http": r.status if r else None, **extract(page)}
        # Known public detail already used in the diagnostic chain.
        rd = page.goto(f"{base.BASE}/house/5289400", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        out["pages"]["detail"] = {"http": rd.status if rd else None, **extract(page)}
        ctx.close(); b.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:{"http":v.get("http"),"transferCount":v.get("transferCount")} for k,v in out["pages"].items()},ensure_ascii=False))

if __name__ == "__main__":
    main()
