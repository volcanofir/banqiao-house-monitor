"""PREVIEW-only Yongching official detail-page floor enrichment.

Fast path order:
1. Reuse a persistent, previously verified cache for the same Yongching house ID + road.
2. For uncached rows, open the official house URL in Chromium and parse the HTTP response
   immediately. If both floor and YC case ID are present, do not wait for or scroll the DOM.
3. Only when the response is incomplete, render/scroll the current property's DOM as a
   compatibility fallback.

The list snapshot is still captured through Surfshark + Chromium, and floor data is
accepted only from the current property's header/basic-info sections. Recommendation
sections are never scanned for a floor.
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
CACHE_VERSION = 1
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
          const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
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


def find_floor_in_response(official_response_text):
    """Fast path: inspect only current-property response header/basic-info."""
    for mode, section in (
        ("chromium-response-fast-header", current_header(official_response_text)),
        ("chromium-response-fast-basic-info", slice_basic_info(official_response_text)),
    ):
        if not section:
            continue
        floor, evidence, _ = floor_from_detail_text(section, allow_unlabelled=True)
        if floor:
            return floor, evidence, mode
    return None, None, None


def load_json(path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def cache_key(row):
    return f"{row.get('id')}|{row.get('road')}"


def make_cache_entry(row, floor, case_id, source_mode, stamp):
    return {
        "id": row.get("id"),
        "road": row.get("road"),
        "url": row.get("url"),
        "title": row.get("title"),
        "floor": floor,
        "officialCaseId": case_id,
        "sourceMode": source_mode,
        "verifiedAt": stamp,
    }


def cache_entry_usable(row, entry):
    if not isinstance(entry, dict):
        return False
    if str(entry.get("id")) != str(row.get("id")):
        return False
    if str(entry.get("road") or "") != str(row.get("road") or ""):
        return False
    if row.get("url") and entry.get("url") and str(entry.get("url")) != str(row.get("url")):
        return False
    floor = entry.get("floor")
    case_id = entry.get("officialCaseId")
    if not floor or not case_id:
        return False
    conflict, _, _ = title_floor_conflict(row.get("title"), floor)
    return not conflict


def load_cache():
    # Reuse the canonical diagnostic file as the persistent cache container so no
    # separate workflow artifact is required. Newer runs keep all prior cacheEntries.
    raw = load_json(DIAG, {})
    entries = raw.get("cacheEntries") if isinstance(raw, dict) else None
    return dict(entries or {})


def seed_cache_from_previous_diagnostic(entries):
    """Bootstrap the first cache file from the last already-verified canonical run."""
    diag = load_json(DIAG, {})
    seeded = 0
    for info in diag.get("rows") or []:
        if not isinstance(info, dict):
            continue
        if info.get("http") != 200 or not info.get("id") or not info.get("road"):
            continue
        floor = info.get("floor")
        case_id = info.get("officialCaseId")
        if not floor or not case_id:
            continue
        pseudo = {
            "id": info.get("id"), "road": info.get("road"), "url": info.get("url"),
            "title": info.get("title"),
        }
        key = cache_key(pseudo)
        if key in entries:
            continue
        entries[key] = make_cache_entry(
            pseudo, floor, case_id, info.get("mode") or "previous-canonical-diagnostic",
            diag.get("generatedAt"),
        )
        seeded += 1
    return seeded


def apply_cache(row, entry):
    row["officialCaseId"] = entry.get("officialCaseId")
    row["floor"] = entry.get("floor")
    row["floorSourceMode"] = "yungching_verified_detail_cache"
    row["floorEvidence"] = f"verified cache {entry.get('verifiedAt') or ''}".strip()


def main():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    entries = load_cache()
    seeded_from_diag = seed_cache_from_previous_diagnostic(entries)
    eligible_before_cache = [row for row in listings if should_enrich(row)]
    cache_hits = 0
    cache_hit_rows = []
    for row in eligible_before_cache:
        entry = entries.get(cache_key(row))
        if not cache_entry_usable(row, entry):
            continue
        apply_cache(row, entry)
        cache_hits += 1
        cache_hit_rows.append({
            "id": row.get("id"), "road": row.get("road"), "title": row.get("title"),
            "floor": row.get("floor"), "officialCaseId": row.get("officialCaseId"),
            "mode": "verified-cache",
        })

    targets = [row for row in listings if should_enrich(row)][:MAX_DETAIL_PAGES]
    diagnostics = list(cache_hit_rows)
    enriched_live = 0
    case_ids_live = 0
    rejected_conflicts = 0
    response_fast_hits = 0
    dom_fallbacks = 0
    cache_writes = 0

    if targets:
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

                    # Fast path: the official HTTP response often already contains the
                    # current listing's YC case ID and floor in the header. When both are
                    # present, avoid all DOM waiting and scrolling.
                    floor, evidence, mode = find_floor_in_response(official_text)
                    case_id = official_case_id(official_text)
                    conflict, expected_floors, actual_floors = title_floor_conflict(row.get("title"), floor)
                    fast_ok = bool(info["http"] == 200 and floor and case_id and not conflict)

                    body = ""
                    if fast_ok:
                        response_fast_hits += 1
                    else:
                        dom_fallbacks += 1
                        render_full_detail(page)
                        focused, body, snippets = rendered_floor_context(page)
                        floor, evidence, mode = find_floor(focused, body, official_text)
                        case_id = official_case_id(body) or case_id
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
                        "fastResponseHit": fast_ok,
                        "domFallback": not fast_ok,
                        "responseHasBasicInfo": "基本資訊" in official_text,
                        "responseHeader": current_header(official_text)[-700:],
                        "finalUrl": page.url,
                    })
                    if body:
                        info["domHasBasicInfo"] = "基本資訊" in body
                        info["domHeader"] = current_header(body)[-700:]

                    if info["http"] == 200 and case_id:
                        row["officialCaseId"] = case_id
                        case_ids_live += 1
                    if info["http"] == 200 and floor:
                        row["floor"] = floor
                        if fast_ok:
                            row["floorSourceMode"] = "yungching_official_detail_chromium_response_fast"
                        else:
                            row["floorSourceMode"] = "yungching_official_detail_dom" if str(mode).startswith("dom-") else "yungching_official_detail_chromium_response"
                        row["floorEvidence"] = evidence
                        enriched_live += 1

                    if info["http"] == 200 and floor and case_id:
                        entries[cache_key(row)] = make_cache_entry(row, floor, case_id, mode, stamp)
                        cache_writes += 1
                except Exception as exc:
                    info["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
                diagnostics.append(info)
                print(
                    f"Yongching detail floor live {index}/{len(targets)} {row.get('id')}: "
                    f"HTTP {info.get('http')} floor={info.get('floor')} case={info.get('officialCaseId')} "
                    f"fast={info.get('fastResponseHit')}"
                )

            browser.close()

    remaining_missing = sum(1 for row in listings if should_enrich(row))
    payload["detailFloorEnrichment"] = {
        "generatedAt": stamp,
        "source": "Yongching verified persistent detail cache; uncached rows use official Chromium response first, current-property DOM fallback only when needed",
        "eligibleBeforeCache": len(eligible_before_cache),
        "cacheHitCount": cache_hits,
        "seededFromPreviousDiagnosticCount": seeded_from_diag,
        "liveAttempted": len(targets),
        "responseFastHitCount": response_fast_hits,
        "domFallbackCount": dom_fallbacks,
        "enriched": cache_hits + enriched_live,
        "liveEnriched": enriched_live,
        "officialCaseIdEnriched": cache_hits + case_ids_live,
        "cacheWriteCount": cache_writes,
        "cacheEntryCount": len(entries),
        "rejectedTitleFloorConflicts": rejected_conflicts,
        "remainingMissing": remaining_missing,
        "skippedTypes": sorted(SKIP_TYPES),
        "method": "verified cache -> current official Chromium HTTP response -> rendered current-property DOM fallback; no recommendation floor parsing",
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DIAG.write_text(json.dumps({
        "generatedAt": stamp,
        "previewOnly": True,
        "eligibleBeforeCache": len(eligible_before_cache),
        "cacheHitCount": cache_hits,
        "seededFromPreviousDiagnosticCount": seeded_from_diag,
        "liveAttempted": len(targets),
        "responseFastHitCount": response_fast_hits,
        "domFallbackCount": dom_fallbacks,
        "enriched": cache_hits + enriched_live,
        "liveEnriched": enriched_live,
        "officialCaseIdEnriched": cache_hits + case_ids_live,
        "cacheWriteCount": cache_writes,
        "cacheEntryCount": len(entries),
        "rejectedTitleFloorConflicts": rejected_conflicts,
        "remainingMissing": remaining_missing,
        "cacheVersion": CACHE_VERSION,
        "cachePolicy": "reuse verified Yongching house ID + exact road; refresh only uncached/incomplete rows",
        "cacheEntries": entries,
        "rows": diagnostics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["detailFloorEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
