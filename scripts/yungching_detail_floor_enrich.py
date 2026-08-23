"""PREVIEW-only Yongching official detail-page floor enrichment.

Input: docs/preview/yungching-browser-snapshot.json produced through Surfshark + Chromium.
For rendered list cards that do not expose a subject floor, open the official Yongching
house detail page in the same network path and extract the current property's floor from
its rendered/current-response basic information. No third-party inventory is used.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
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

    if allow_unlabelled:
        floor = v3.safe_parse_floor(text)
        if floor:
            pos = text.find(floor)
            evidence = text[max(0, pos - 80):pos + 100] if pos >= 0 else text[:180]
            return floor, evidence, "current-property-section"

    return None, None, None


def slice_basic_info(body: str):
    """Isolate the current property's 基本資訊 block before recommendation content."""
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


def current_header(body: str):
    body = compact(body)
    if not body:
        return ""
    end = body.find("基本資訊")
    if end < 0:
        end = min(6500, len(body))
    return body[:end]


def official_case_id(text: str):
    m = re.search(r"\b(YC\d{5,12})\b", str(text or ""), re.I)
    return m.group(1).upper() if m else None


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


def response_text(response):
    """Return readable text from the same official HTTP 200 loaded by Chromium."""
    if not response:
        return ""
    try:
        html = response.text()
    except Exception:
        return ""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        return compact(soup.get_text(" ", strip=True))[:180000]
    except Exception:
        return compact(re.sub(r"<[^>]+>", " ", html))[:180000]


def render_full_detail(page):
    """Wait for current listing specs, then trigger lazy rendered sections by scrolling."""
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


def find_floor(dom_focused, dom_body, official_response_text):
    """Prefer rendered DOM; use only the same Chromium official response as fallback."""
    dom_basic = slice_basic_info(dom_body)
    floor, evidence, mode = floor_from_detail_text(dom_basic, allow_unlabelled=True)
    if floor:
        return floor, evidence, "dom-basic-info"

    floor, evidence, mode = floor_from_detail_text(dom_focused, allow_unlabelled=False)
    if floor:
        return floor, evidence, "dom-labelled"

    floor, evidence, mode = floor_from_detail_text(dom_body, allow_unlabelled=False)
    if floor:
        return floor, evidence, "dom-body-labelled"

    header = current_header(dom_body)
    floor, evidence, mode = floor_from_detail_text(header, allow_unlabelled=True)
    if floor:
        return floor, evidence, "dom-current-header"

    response_basic = slice_basic_info(official_response_text)
    floor, evidence, mode = floor_from_detail_text(response_basic, allow_unlabelled=True)
    if floor:
        return floor, evidence, "chromium-response-basic-info"

    floor, evidence, mode = floor_from_detail_text(official_response_text, allow_unlabelled=False)
    if floor:
        return floor, evidence, "chromium-response-labelled"

    response_header = current_header(official_response_text)
    floor, evidence, mode = floor_from_detail_text(response_header, allow_unlabelled=True)
    if floor:
        return floor, evidence, "chromium-response-current-header"

    return None, None, None


def main():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    targets = [row for row in listings if should_enrich(row)][:MAX_DETAIL_PAGES]
    diagnostics = []
    enriched = 0
    case_ids = 0

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
                official_text = response_text(response)
                render_full_detail(page)
                focused, body, snippets = rendered_floor_context(page)

                floor, evidence, mode = find_floor(focused, body, official_text)
                case_id = official_case_id(body) or official_case_id(official_text)

                info["floor"] = floor
                info["mode"] = mode
                info["evidence"] = evidence
                info["officialCaseId"] = case_id
                info["domHasBasicInfo"] = "基本資訊" in body
                info["responseHasBasicInfo"] = "基本資訊" in official_text
                info["domBasicInfo"] = slice_basic_info(body)[:700]
                info["responseBasicInfo"] = slice_basic_info(official_text)[:700]
                info["snippets"] = snippets[:8]
                info["finalUrl"] = page.url

                if info["http"] == 200 and case_id:
                    row["officialCaseId"] = case_id
                    case_ids += 1
                if info["http"] == 200 and floor:
                    row["floor"] = floor
                    row["floorSourceMode"] = "yungching_official_detail_dom" if str(mode).startswith("dom-") else "yungching_official_detail_chromium_response"
                    row["floorEvidence"] = evidence
                    enriched += 1
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            diagnostics.append(info)
            print(f"Yongching detail floor {index}/{len(targets)} {row.get('id')}: HTTP {info.get('http')} floor={info.get('floor')} case={info.get('officialCaseId')}")

        browser.close()

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["detailFloorEnrichment"] = {
        "generatedAt": stamp,
        "source": "Yongching official detail via Surfshark + Chromium; rendered DOM first, same Chromium HTTP response fallback",
        "attempted": len(targets),
        "enriched": enriched,
        "officialCaseIdEnriched": case_ids,
        "remainingMissing": sum(1 for row in listings if should_enrich(row)),
        "skippedTypes": sorted(SKIP_TYPES),
        "method": "rendered DOM basic-info/header first; same Chromium official response basic-info/header fallback",
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DIAG.write_text(json.dumps({
        "generatedAt": stamp,
        "previewOnly": True,
        "attempted": len(targets),
        "enriched": enriched,
        "officialCaseIdEnriched": case_ids,
        "rows": diagnostics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["detailFloorEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
