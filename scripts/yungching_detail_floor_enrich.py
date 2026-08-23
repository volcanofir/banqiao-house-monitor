"""PREVIEW-only Yongching official detail-page floor enrichment.

Input: docs/preview/yungching-browser-snapshot.json produced through Surfshark + Chromium.
For rendered list cards that do not expose a subject floor, open the official Yongching
house detail page in the same network path and extract the current property's floor from
its rendered 基本資訊 section. No third-party inventory is used.
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

    # Highest confidence: value rendered beside a floor specification label.
    for m in re.finditer(r"(?:所在樓層|樓層|樓別)\s*[:：]?\s*(.{0,60})", text):
        snippet = m.group(0)
        floor = v3.safe_parse_floor(snippet)
        if floor:
            return floor, snippet[:160], "labelled-subject-total"

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

    # Safe only inside the current property's own header/basic-info section.
    if allow_unlabelled:
        floor = v3.safe_parse_floor(text)
        if floor:
            pos = text.find(floor)
            evidence = text[max(0, pos - 80):pos + 100] if pos >= 0 else text[:180]
            return floor, evidence, "current-property-section"

    return None, None, None


def slice_basic_info(body: str):
    """Isolate the current property's rendered 基本資訊 block before recommendation content."""
    body = compact(body)
    start = body.find("基本資訊")
    if start < 0:
        return ""
    end_candidates = []
    for marker in ("特色說明", "房屋特色", "周邊環境", "實價登錄", "附近成交"):
        p = body.find(marker, start + 4)
        if p > start:
            end_candidates.append(p)
    end = min(end_candidates) if end_candidates else min(len(body), start + 6000)
    return body[start:end]


def rendered_floor_context(page):
    result = page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const snippets = [];
          const seen = new Set();
          for (const el of Array.from(document.querySelectorAll('body *'))) {
            const text = clean(el.innerText);
            if (!text || text.length > 320) continue;
            if (!/(所在樓層|樓層|樓別|總樓層|總樓高|基本資訊)/.test(text)) continue;
            if (seen.has(text)) continue;
            seen.add(text);
            snippets.push(text);
            if (snippets.length >= 60) break;
          }
          return {
            snippets,
            body: clean(document.body ? document.body.innerText : '').slice(0,140000),
          };
        }"""
    )
    snippets = result.get("snippets") or []
    body = result.get("body") or ""
    return " | ".join(snippets), body, snippets[:20]


def render_full_detail(page):
    """Wait for the current listing specs, then trigger lazy rendered sections by scrolling."""
    try:
        page.wait_for_function(
            "() => document.body && /基本資訊|樓層/.test(document.body.innerText || '')",
            timeout=9000,
        )
    except Exception:
        pass

    page.wait_for_timeout(800)
    for ratio in (0.2, 0.45, 0.7, 1.0):
        try:
            page.evaluate("r => window.scrollTo(0, Math.max(0, document.body.scrollHeight * r))", ratio)
        except Exception:
            pass
        page.wait_for_timeout(650)
    try:
        page.evaluate("window.scrollTo(0,0)")
    except Exception:
        pass
    page.wait_for_timeout(500)


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
                render_full_detail(page)
                focused, body, snippets = rendered_floor_context(page)
                basic = slice_basic_info(body)

                # 1) Current property's 基本資訊 block: safe to accept an unlabelled X/Y樓.
                floor, evidence, mode = floor_from_detail_text(basic, allow_unlabelled=True)
                # 2) DOM snippets containing explicit floor/basic-info labels.
                if not floor:
                    floor, evidence, mode = floor_from_detail_text(focused, allow_unlabelled=False)
                # 3) Whole body only accepts explicitly labelled floor formats.
                if not floor:
                    floor, evidence, mode = floor_from_detail_text(body, allow_unlabelled=False)
                # 4) Header fallback: before 基本資訊, still belongs to the current property.
                if not floor and body:
                    header = body[:body.find("基本資訊") if "基本資訊" in body else min(5000, len(body))]
                    floor, evidence, mode = floor_from_detail_text(header, allow_unlabelled=True)
                    if floor:
                        mode = "current-property-header"

                info["floor"] = floor
                info["mode"] = mode
                info["evidence"] = evidence
                info["basicInfo"] = basic[:700]
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
        "method": "wait basic info + full scroll + current property basic-info/header parsing",
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
