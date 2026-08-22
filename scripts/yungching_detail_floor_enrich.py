"""PREVIEW-only Yongching official detail-page floor enrichment.

Input: docs/preview/yungching-browser-snapshot.json produced through Surfshark + Chromium.
For rendered list cards that do not expose a subject floor, open the official Yongching
house detail page in the same network path and extract floor text from rendered DOM.
No third-party inventory is used.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot_v3 as v3


SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
DIAG = Path("docs/preview/yungching-detail-floor.json")
SKIP_TYPES = {"透天厝", "土地"}
MAX_DETAIL_PAGES = 80


def compact(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def floor_from_detail_text(text: str, allow_unlabelled=False):
    text = compact(text).replace("／", "/").replace("～", "~")

    # Prefer values explicitly attached to the detail specification labels.
    labelled = []
    for m in re.finditer(r"(?:所在樓層|樓層|樓別)\s*[:：]?\s*(.{0,50})", text):
        labelled.append(m.group(0))
    for snippet in labelled:
        floor = v3.safe_parse_floor(snippet)
        if floor:
            return floor, snippet[:140], "labelled-subject-total"

    # Some templates render subject floor and total floor as separate specification rows.
    subject = None
    total = None
    for pat in (
        r"(?:所在樓層|樓層|樓別)\s*[:：]?\s*(\d{1,2})(?:樓|F)\b",
        r"(?:所在樓層|樓層|樓別)\s*[:：]?\s*第?\s*(\d{1,2})\s*樓",
    ):
        m = re.search(pat, text, re.I)
        if m:
            subject = int(m.group(1))
            break
    for pat in (
        r"(?:總樓層|總樓高|樓高|共)\s*[:：]?\s*(\d{1,2})\s*樓",
        r"(?:總樓層|總樓高)\s*[:：]?\s*(\d{1,2})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            total = int(m.group(1))
            break
    if subject and total and 1 <= subject <= total <= 99:
        return f"{subject}/{total}樓", f"subject={subject}, total={total}", "separate-labels"

    # Only the already-filtered floor-specification DOM snippets may use an unlabelled
    # subject/total expression. Never scan the whole body this way because Yongching's
    # detail page can contain recommended properties with unrelated floor values.
    if allow_unlabelled:
        floor = v3.safe_parse_floor(text)
        if floor:
            return floor, text[:180], "specification-subject-total"

    return None, None, None


def rendered_floor_context(page):
    """Return focused floor-specification snippets plus body text for labelled fallback."""
    result = page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const snippets = [];
          const seen = new Set();
          for (const el of Array.from(document.querySelectorAll('body *'))) {
            const text = clean(el.innerText);
            if (!text || text.length > 240) continue;
            if (!/(所在樓層|樓層|樓別|總樓層|總樓高)/.test(text)) continue;
            if (seen.has(text)) continue;
            seen.add(text);
            snippets.push(text);
            if (snippets.length >= 40) break;
          }
          return {
            snippets,
            body: clean(document.body ? document.body.innerText : '').slice(0,120000),
          };
        }"""
    )
    focused = " | ".join(result.get("snippets") or [])
    body = result.get("body") or ""
    return focused, body, (result.get("snippets") or [])[:20]


def should_enrich(row):
    if row.get("floor") not in (None, ""):
        return False
    if not row.get("url"):
        return False
    if str(row.get("type") or "").strip() in SKIP_TYPES:
        return False
    return True


def main():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    targets = [row for row in listings if should_enrich(row)][:MAX_DETAIL_PAGES]
    diagnostics = []
    enriched = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        for index, row in enumerate(targets, 1):
            info = {
                "id": row.get("id"),
                "road": row.get("road"),
                "title": row.get("title"),
                "url": row.get("url"),
                "http": None,
                "floor": None,
            }
            try:
                response = page.goto(row["url"], wait_until="domcontentloaded", timeout=35000)
                info["http"] = response.status if response else None
                page.wait_for_timeout(1200)
                focused, body, snippets = rendered_floor_context(page)

                # Focused snippets are already constrained to floor-specification DOM.
                floor, evidence, mode = floor_from_detail_text(focused, allow_unlabelled=True)
                if not floor:
                    # Whole-body fallback accepts labelled/separate-specification formats only.
                    floor, evidence, mode = floor_from_detail_text(body, allow_unlabelled=False)

                info["floor"] = floor
                info["mode"] = mode
                info["evidence"] = evidence
                info["snippets"] = snippets[:8]
                info["finalUrl"] = page.url
                if info["http"] == 200 and floor:
                    row["floor"] = floor
                    row["floorSourceMode"] = "yungching_official_detail_dom"
                    row["floorEvidence"] = evidence
                    enriched += 1
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            diagnostics.append(info)
            print(f"Yongching detail floor {index}/{len(targets)} {row.get('id')}: HTTP {info.get('http')} floor={info.get('floor')}")

        browser.close()

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["detailFloorEnrichment"] = {
        "generatedAt": stamp,
        "source": "Yongching official house detail rendered DOM via Surfshark + Chromium",
        "attempted": len(targets),
        "enriched": enriched,
        "remainingMissing": sum(1 for row in listings if should_enrich(row)),
        "skippedTypes": sorted(SKIP_TYPES),
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DIAG.write_text(json.dumps({
        "generatedAt": stamp,
        "previewOnly": True,
        "attempted": len(targets),
        "enriched": enriched,
        "rows": diagnostics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["detailFloorEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
