"""Scheme A Preview v7: safe floor parsing and one-to-one company matches.

Prevents concatenated DOM strings such as `主32.333/3樓` from becoming floor 33.
Company rows prefer their structured official `floor`. A single Yongching company
listing may not automatically mark multiple external property groups as inventory.
"""

import json
import re
from collections import Counter, defaultdict

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v5 as v5
import compare_yungching_preview_v6 as v6


def safe_floor_numbers(text, company_text=False):
    text = str(text or "").replace("～", "~")
    floors = set()
    spans = []
    for m in re.finditer(r"(\d{1,2})(?:\s*[~-]\s*(\d{1,2}))?\s*/\s*(\d{1,2})\s*樓", text):
        raw_lo, raw_hi, total = m.group(1), m.group(2), int(m.group(3))
        if not (1 <= total <= 99):
            continue
        if raw_hi is not None:
            lo, hi = int(raw_lo), int(raw_hi)
            if 1 <= lo <= hi <= total and hi - lo <= 10:
                floors.update(range(lo, hi + 1))
        else:
            n = int(raw_lo)
            if 1 <= n <= total:
                floors.add(n)
            elif len(raw_lo) == 2:
                suffix = int(raw_lo[-1])
                if 1 <= suffix <= total:
                    floors.add(suffix)
        spans.append(m.span())

    if spans:
        chars = list(text)
        for start, end in spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    range_spans = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[~-]\s*(\d{1,2})\s*樓", text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 99 and hi - lo <= 10:
            floors.update(range(lo, hi + 1))
        range_spans.append(m.span())
    if range_spans:
        chars = list(text)
        for start, end in range_spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            floors.add(n)

    digits = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        if raw == "十":
            n = 10
        elif "十" in raw:
            left, right = raw.split("十", 1)
            n = digits.get(left, 1) * 10 + digits.get(right, 0)
        else:
            n = digits.get(raw)
        if n:
            floors.add(n)
    return floors


def safe_listing_floor_tokens(x):
    floors = set()
    if not x:
        return floors
    floors |= safe_floor_numbers(x.get("title"))
    floors |= safe_floor_numbers(x.get("address"))
    for m in (x.get("mergedListings") or []):
        floors |= safe_floor_numbers(m.get("title"))
        floors |= safe_floor_numbers(m.get("address"))
    return floors


def guard_company_candidate_reuse(payload):
    """Downgrade duplicate automatic company matches to review.

    If one official Yongching ID is the candidate for two different external groups,
    the external grouping is ambiguous. Neither group is allowed to stay auto-stock.
    """
    by_candidate = defaultdict(list)
    for row in payload.get("comparisons") or []:
        if row.get("status") != "company_match":
            continue
        candidate = row.get("companyCandidate") or {}
        cid = str(candidate.get("id") or "")
        if cid:
            by_candidate[cid].append(row)

    duplicated = {cid: rows for cid, rows in by_candidate.items() if len(rows) > 1}
    affected = 0
    for cid, rows in duplicated.items():
        group_ids = [x.get("groupId") for x in rows]
        for row in rows:
            row["status"] = "review"
            row["statusLabel"] = "待確認"
            row["companyCandidateReuseReview"] = True
            row["companyCandidateReuseGroupIds"] = group_ids
            row["reason"] = (str(row.get("reason") or "") + "；同一永慶公司案件同時命中多個外部群組，禁止自動計入庫存").strip("；")
            affected += 1

    counts = Counter(str(x.get("status") or "unavailable") for x in (payload.get("comparisons") or []))
    payload["counts"] = {
        "company_match": counts.get("company_match", 0),
        "review": counts.get("review", 0),
        "missing": counts.get("missing", 0),
        "unavailable": counts.get("unavailable", 0),
    }
    payload["companyCandidateReuseGuard"] = {
        "enabled": True,
        "duplicateCandidateCount": len(duplicated),
        "affectedGroupCount": affected,
        "candidateIds": sorted(duplicated),
        "rule": "同一永慶官方案件不得自動把多個外部群組同時判定為庫存；重複命中全部降為待確認",
    }


def main():
    v5.floors_from_text = safe_floor_numbers
    v4.title_floor_tokens = safe_floor_numbers
    v4.listing_floor_tokens = safe_listing_floor_tokens
    v6.main()

    path = v5.v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    guard_company_candidate_reuse(payload)
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware_official_rendered_v7"
    payload["safeFloorParser"] = True
    payload["safeFloorParserRule"] = "subject floor must be physically valid against total floor; glued area digits are trimmed instead of becoming impossible floors"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "safeFloorParser": True,
        "companyCandidateReuseGuard": payload.get("companyCandidateReuseGuard"),
        "counts": payload.get("counts"),
        "mode": payload["mode"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
