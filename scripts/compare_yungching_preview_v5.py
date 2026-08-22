import json
import re

import compare_yungching_preview_v4 as v4

# PREVIEW v5:
# - Keep v4 order: 591 -> Sinyi -> company.
# - Add floor as a first-class matching signal.
# - Add a conservative 591 regroup rule for near-identical area/price when
#   both titles share a meaningful property keyword such as 收租.
# - Protect company matching from a partial-but-HTTP-200 company fetch by
#   reusing the previous healthy road snapshot when the fresh road count
#   collapses abnormally.

ORIGINAL_591_PAIR = v4.pair_591_info
ORIGINAL_CROSS_SOURCE = v4.cross_source_cluster_info
ORIGINAL_COMPANY_SCORE = v4.prev.base.score
ORIGINAL_FETCH_COMPANY = v4.prev.base.fetch_company

KEYWORDS = {
    "收租", "頂加", "露台", "露臺", "店面", "店辦", "透天", "邊間", "河景",
    "景觀", "採光", "三房", "四房", "兩房", "公寓", "電梯", "一樓", "頂樓",
}

COMPANY_GUARD_STATS = {
    "enabled": True,
    "rule": "前次至少8筆且本次下降50%以上並少至少5筆，或前次至少5筆但本次變0筆時，沿用前次正常路段公司資料",
    "triggeredRoadCount": 0,
    "roads": [],
}


def guarded_fetch_company():
    company, logs, status = ORIGINAL_FETCH_COMPANY()
    path = v4.prev.OUT_PATH
    if not path.exists():
        return company, logs, status

    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logs.append(f"公司資料異常保護：無法讀取前次 Preview 快照，略過保護（{type(exc).__name__}）")
        return company, logs, status

    previous_status = previous.get("roadStatus") or {}
    previous_listings = previous.get("companyListings") or []

    for road in v4.prev.base.ROADS:
        fresh_status = status.get(road) or {}
        old_status = previous_status.get(road) or {}

        # This guard is specifically for partial responses that still look
        # technically successful. Real fetch failures continue through the
        # existing HAR fallback / unavailable logic.
        if not fresh_status.get("available") or not old_status.get("available"):
            continue

        fresh_rows = [x for x in company if x.get("road") == road]
        old_rows = [dict(x) for x in previous_listings if x.get("road") == road]
        if not old_rows:
            continue

        fresh_count = len(fresh_rows)
        old_count = len(old_rows)
        drop = old_count - fresh_count

        large_collapse = old_count >= 8 and fresh_count * 2 <= old_count and drop >= 5
        zero_collapse = old_count >= 5 and fresh_count == 0
        if not (large_collapse or zero_collapse):
            continue

        # Replace only the anomalous road. Other roads keep the fresh result.
        company = [x for x in company if x.get("road") != road]
        for row in old_rows:
            row["guardedFromPreviousSnapshot"] = True
            company.append(row)

        fresh_status.update({
            "available": True,
            "count": old_count,
            "mode": "previous_snapshot_guard",
            "guarded": True,
            "freshCount": fresh_count,
            "previousCount": old_count,
            "guardReason": "公司公開資料本輪數量異常縮水，沿用前次正常路段快照避免誤判未接回",
        })
        COMPANY_GUARD_STATS["roads"].append({
            "road": road,
            "freshCount": fresh_count,
            "previousCount": old_count,
            "drop": drop,
        })
        logs.append(
            f"公司資料異常保護：{road} 前次 {old_count} 筆，本次僅 {fresh_count} 筆；沿用前次正常資料。"
        )

    COMPANY_GUARD_STATS["triggeredRoadCount"] = len(COMPANY_GUARD_STATS["roads"])
    return company, logs, status


def chinese_floor_number(raw):
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if raw == "十":
        return 10
    if "十" in raw:
        left, right = raw.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(raw)


def floors_from_text(text, company_text=False):
    text = str(text or "")
    floors = set()

    # For strings such as "9/11 樓", the first number is the subject floor and
    # the second is the total floor count. Never treat the total as the unit floor.
    slash_spans = []
    for m in re.finditer(r"(\d{1,2})\s*/\s*(\d{1,2})\s*樓", text):
        floors.add(int(m.group(1)))
        slash_spans.append(m.span())

    if slash_spans:
        chars = list(text)
        for start, end in slash_spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            floors.add(n)

    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        n = chinese_floor_number(raw)
        if n:
            floors.add(n)

    return floors


def listing_floors(x, company=False):
    floors = set()
    if not x:
        return floors

    fields = [x.get("title"), x.get("address")]
    if company:
        fields.append(x.get("text"))
    for field in fields:
        floors |= floors_from_text(field, company_text=company)

    # A regrouped 591/Sinyi record may contain additional source titles with an
    # explicit floor even when the representative title does not.
    for m in (x.get("mergedListings") or []):
        floors |= floors_from_text(m.get("title"))
        floors |= floors_from_text(m.get("address"))
    return floors


def shared_keywords(a, b):
    at = str(a.get("title") or "")
    bt = str(b.get("title") or "")
    return sorted(k for k in KEYWORDS if k in at and k in bt)


def floor_relation(a, b, b_company=False):
    af = listing_floors(a)
    bf = listing_floors(b, company=b_company)
    if af and bf:
        if af & bf:
            return "match", sorted(af), sorted(bf)
        return "conflict", sorted(af), sorted(bf)
    return "unknown", sorted(af), sorted(bf)


def pair_591_info(a, b):
    ok, info = ORIGINAL_591_PAIR(a, b)
    relation, af, bf = floor_relation(a, b)
    info = dict(info or {})
    info["floorRelation"] = relation
    info["floorsA"] = af
    info["floorsB"] = bf

    if relation == "conflict":
        info["floorConflict"] = True
        return False, info
    if ok:
        return True, info

    aa, ba = v4.area_of(a), v4.area_of(b)
    ap, bp = v4.price_of(a), v4.price_of(b)
    ad = abs(aa - ba) if aa is not None and ba is not None else None
    pd = abs(ap - bp) if ap is not None and bp is not None else None
    kws = shared_keywords(a, b)

    # Conservative extra regroup rule: same road + essentially same area +
    # <=30萬 price gap + at least one meaningful shared property characteristic.
    # Explicit different floors always veto the merge.
    keyword_corroborated = bool(
        ad is not None and ad <= 0.05 and
        pd is not None and pd <= 30 and
        kws
    )
    if keyword_corroborated:
        info["areaDelta"] = round(ad, 2)
        info["priceDelta"] = round(pd, 1)
        info["sharedPropertyKeywords"] = kws
        info["nearFingerprintKeywordMerge"] = True
        return True, info

    return False, info


def cross_source_cluster_info(sinyi, m591_group):
    level, score, info = ORIGINAL_CROSS_SOURCE(sinyi, m591_group)
    info = dict(info or {})
    relation, sf, mf = floor_relation(sinyi, m591_group)
    info["floorRelation"] = relation
    info["sinyiFloors"] = sf
    info["listing591Floors"] = mf

    # Explicitly different floors mean they are not the same unit even when area
    # and asking price are almost identical.
    if relation == "conflict":
        info["reason"] = "信義與591有明確樓層衝突，不自動整併"
        info["floorConflict"] = True
        return "no", -99, info

    # When the floor agrees, prefer that Sinyi row over another same-area/price
    # Sinyi candidate whose floor is unknown. This resolves cases like 9F vs 10F.
    if relation == "match":
        score += 8
        info["floorMatch"] = True
        ad = info.get("areaDelta")
        pd = info.get("priceDelta")
        if level != "strong" and ad is not None and ad <= 0.30 and pd is not None and pd <= 80:
            level = "strong"
            info["reason"] = "樓層一致，且坪數與價格接近，改以信義為主合併"

    return level, score, info


def company_score(ext, yc):
    score, info = ORIGINAL_COMPANY_SCORE(ext, yc)
    info = dict(info or {})
    relation, ef, cf = floor_relation(ext, yc, b_company=True)
    info["floorRelation"] = relation
    info["externalFloors"] = ef
    info["companyFloors"] = cf

    # Floor is stronger than a small asking-price difference. If both sides
    # explicitly state different floors, reject this company candidate.
    if relation == "conflict":
        info["floorConflict"] = True
        info["reason"] = "外部案件與公司候選樓層明確不同"
        return -99, info

    if relation == "match":
        score += 8
        info["floorMatch"] = True

    return score, info


def main():
    # Patch only PREVIEW matching/fetch functions. Production crawler/data are untouched.
    v4.pair_591_info = pair_591_info
    v4.cross_source_cluster_info = cross_source_cluster_info
    v4.prev.base.score = company_score
    v4.prev.base.fetch_company = guarded_fetch_company
    v4.main()

    path = v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware"
    payload["note"] = (
        "PREVIEW：591先重新互相比對，再與信義整併且信義為主，最後比公司庫存。"
        "樓層列為重要比對條件：明確樓層衝突不合併、不配對；樓層一致會提高優先權。"
        "591間若坪數幾乎相同、價差30萬內且有共同物件特徵，可再整併。"
        "公司公開資料若某路段在技術上成功但數量異常縮水，會沿用前次正常路段快照，避免大量誤判未接回。"
    )
    payload["floorAwareMatching"] = True
    payload["companyDataGuard"] = dict(COMPANY_GUARD_STATS)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "floorAwareMatching": True,
        "companyDataGuard": COMPANY_GUARD_STATS,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
