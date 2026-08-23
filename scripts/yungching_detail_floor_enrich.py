"""PREVIEW-only Yongching official detail-page floor enrichment.

The list snapshot is captured through Surfshark + Chromium. For rows without a floor,
open that exact official Yongching house page in Chromium and accept floor data only
from the current property's header or 基本資訊 section. Never scan recommendation
sections for a floor. The same Chromium HTTP 200 response may be used as a fallback
when its current-property section is clearer than the live DOM.
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
            evidence = text[max(0, pos - 90):pos + 110] if pos >= 0 else text[:200]
            return floor, evidence, "current-property-section"

    return None, None, None


def slice_basic_info(body: str):
    body = compact(body)
    start = body.find("基本資訊")
    if start < 0:
        return ""
    ends = []
    for marker in ("特色說明", "房屋特色", "周邊環境", "實價登錄", "附近成交"):
        p = body.find(marker, start + 4)
        if p > start:
            ends.append(p)
    end = min(ends) if ends else min(len(body), start + 6500)
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


def chinese_floor_number(raw):
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    d = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    if raw == "十":
        return 10
    if "十" in raw:
        left, right = raw.split("十", 1)
        tens = d.get(left, 1) if left else 1
        ones = d.get(right, 0) if right else 0
        return tens * 10 + ones
    return d.get(raw)


def explicit_title_floors(title):
    text = str(title or "")
    floors = set()
    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            floors.add(n)
    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        n = chinese_floor_number(raw)
        if n:
            floors.add(n)
    return floors


def subject_floors(floor):
    text = str(floor or "")
    m = re.fullmatch(r"(\d{1,2})(?:~(\d{1,2}))?/(\d{1,2})樓", text)
    if not m:
        return set()
    lo = int(m.group(1)); hi = int(m.group(2) or m.group(1)); total = int(m.group(3))
    if not (1 <= lo <= hi <= total <= 99):
        return set()
    return set(range(lo, hi + 1))


def title_floor_conflict(title, floor):
    expected = explicit_title_floors(title)
    actual = subject_floors(floor)
    return bool(expected and actual and expected.isdisjoint(actual)), sorted(expected), sorted(actual)


def rendered_floor_context(page):
    """Diagnostic helper kept for the focused test; matching never trusts global snippets."""
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
          return {snippets, body:clean(document.body ? document.body.innerText : '').slice(0,140000)};
        }"""
    )
    snippets = result.get("snippets") or []
    body = result.get("body") or ""
    return " | ".join(snippets), body, snippets[:20]


def response_text(response):
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
    return bool(
        row.get("floor") in (None, "")
        and row.get("url")
        and str(row.get("type") or "").strip() not in SKIP_TYPES
    )


def find_floor(dom_focused, dom_body, official_response_text):
    """Accept only sections belonging to the current listing; never global recommendation text."""
    candidates = (
        ("dom-current-header", current_header(dom_body)),
        ("dom-basic-info", slice_basic_info(dom_body)),
        ("chromium-response-current-header", current_header(official_response_text)),
        ("chromium-response-basic-info", slice_basic_info(official_response_text)),
    )
    for mode, section in candidates:
        if not section:
            continue
        floor, evidence, _ = floor_from_detail_text(section, allow_unlabelled=True)
        if floor:
            return floor, evidence, mode
    return None, None, None


def main():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    targets = [row for row in listings if should_enrich(row)][:MAX_DETAIL_PAGES]
    diagnostics = []
    enriched = 0
    case_ids = 0
    rejected_conflicts = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()

        for index, row in enumerate(targets, 1):
            info = {
                "id": row.get("id"), "road": row.get("road"), "title": row.get("title"),
                "url": row.get("url"), "http": None, "floor": None,
            }
            try:
                response = page.goto(row["url"], wait_until="domcontentloaded", timeout=35000)
                info["http"] = response.status if response else None
                official_text = response_text(response)
                render_full_detail(page)
                focused, body, snippets = rendered_floor_context(page)

                floor, evidence, mode = find_floor(focused, body, official_text)
                case_id = official_case_id(body) or official_case_id(official_text)
                conflict, expected_floors, actual_floors = title_floor_conflict(row.get("title"), floor)
                if conflict:
                    info["rejectedFloor"] = floor
                    info["titleExpectedFloors"] = expected_floors
                    info["parsedFloors"] = actual_floors
                    floor = None
                    mode = "rejected-title-floor-conflict"
                    evidence = "案名有明確樓層且與詳情頁解析結果衝突，為避免抓到推薦物件樓層而拒絕補值"
                    rejected_conflicts += 1

                info.update({
                    "floor": floor, "mode": mode, "evidence": evidence,
                    "officialCaseId": case_id,
                    "domHasBasicInfo": "基本資訊" in body,
                    "responseHasBasicInfo": "基本資訊" in official_text,
                    "domHeader": current_header(body)[-700:],
                    "responseHeader": current_header(official_text)[-700:],
                    "finalUrl": page.url,
                })

                if info["http"] == 200 and case_id:
                    row["officialCaseId"] = case_id
                    case_ids += 1
                if info["http"] == 200 and floor:
                    row["floor"] = floor
                    row["floorSourceMode"] = "yungching_official_detail_dom" if mode.startswith("dom-") else "yungching_official_detail_chromium_response"
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
        "source": "Yongching official detail via Surfshark + Chromium; current listing header/basic-info only",
        "attempted": len(targets),
        "enriched": enriched,
        "officialCaseIdEnriched": case_ids,
        "rejectedTitleFloorConflicts": rejected_conflicts,
        "remainingMissing": sum(1 for row in listings if should_enrich(row)),
        "skippedTypes": sorted(SKIP_TYPES),
        "method": "current listing DOM header/basic-info first; same Chromium response current header/basic-info fallback; no global recommendation floor parsing",
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DIAG.write_text(json.dumps({
        "generatedAt": stamp, "previewOnly": True, "attempted": len(targets),
        "enriched": enriched, "officialCaseIdEnriched": case_ids,
        "rejectedTitleFloorConflicts": rejected_conflicts, "rows": diagnostics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["detailFloorEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
