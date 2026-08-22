import json
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import compare_yungching_preview_v2 as base

DATA_PATH = Path("docs/data/listings.json")
OUT_PATH = Path("docs/preview/company-gap.json")


def price_of(x):
    if x.get("effectivePrice") is not None:
        return base.num(x.get("effectivePrice"))
    return base.num(x.get("price"))


def area_of(x):
    return base.num(x.get("size") if x.get("size") is not None else x.get("area"))


def compact_listing(x):
    merged = []
    for m in (x.get("mergedListings") or []):
        merged.append({
            "id": m.get("id"),
            "houseId": m.get("houseId"),
            "source": m.get("source") or x.get("source"),
            "title": m.get("title"),
            "url": m.get("url"),
            "price": m.get("price"),
            "effectivePrice": m.get("effectivePrice"),
            "size": m.get("size"),
            "address": m.get("address"),
            "sourcePublishedAt": m.get("sourcePublishedAt") if m.get("sourcePublishedAt") is not None else m.get("postTime"),
            "active": m.get("active", True),
        })
    return {
        "id": x.get("id"),
        "houseId": x.get("houseId"),
        "source": x.get("source"),
        "road": x.get("road"),
        "title": x.get("title"),
        "url": x.get("url"),
        "price": x.get("price"),
        "effectivePrice": x.get("effectivePrice"),
        "size": x.get("size"),
        "address": x.get("address"),
        "sourcePublishedAt": x.get("sourcePublishedAt") if x.get("sourcePublishedAt") is not None else x.get("postTime"),
        "sourcePublishedAtType": x.get("sourcePublishedAtType"),
        "newAt": x.get("newAt"),
        "active": x.get("active", True),
        "mergedListingCount": x.get("mergedListingCount"),
        "mergedActiveListingCount": x.get("mergedActiveListingCount"),
        "mergedListings": merged,
    }


def cross_source_info(sinyi, m591):
    sa, ma = area_of(sinyi), area_of(m591)
    sp, mp = price_of(sinyi), price_of(m591)
    area_delta = abs(sa - ma) if sa is not None and ma is not None else None
    price_delta = abs(sp - mp) if sp is not None and mp is not None else None

    st = str(sinyi.get("title") or "")
    mt = str(m591.get("title") or "")
    shared = base.tokens(st) & base.tokens(mt)
    longest = max((len(x) for x in shared), default=0)
    title_ratio = SequenceMatcher(None, base.norm(st), base.norm(mt)).ratio()

    score = 0
    if area_delta is not None:
        if area_delta <= 0.08:
            score += 10
        elif area_delta <= 0.15:
            score += 8
        elif area_delta <= 0.30:
            score += 5
        elif area_delta <= 0.60:
            score += 2
        elif area_delta > 0.80:
            return "no", -99, {
                "areaDelta": round(area_delta, 2), "priceDelta": price_delta,
                "titleRatio": round(title_ratio, 3), "shared": []
            }

    if price_delta is not None:
        if price_delta <= 1:
            score += 7
        elif price_delta <= 30:
            score += 5
        elif price_delta <= 80:
            score += 4
        elif price_delta <= 150:
            score += 2
        elif price_delta <= 300:
            score += 0
        else:
            score -= 2

    if longest >= 6:
        score += 6
    elif longest >= 5:
        score += 5
    elif longest >= 4:
        score += 3
    elif longest >= 3:
        score += 2

    if title_ratio >= 0.62:
        score += 6
    elif title_ratio >= 0.50:
        score += 4
    elif title_ratio >= 0.38:
        score += 2
    elif title_ratio >= 0.28:
        score += 1

    strong = False
    if area_delta is not None:
        strong = (
            (area_delta <= 0.12 and price_delta is not None and price_delta <= 100 and (title_ratio >= 0.18 or longest >= 3)) or
            (area_delta <= 0.30 and price_delta is not None and price_delta <= 30 and (title_ratio >= 0.28 or longest >= 4)) or
            (area_delta <= 0.15 and (title_ratio >= 0.48 or longest >= 5) and (price_delta is None or price_delta <= 500)) or
            (area_delta <= 0.60 and title_ratio >= 0.62 and price_delta is not None and price_delta <= 150)
        )

    review = False
    if not strong and area_delta is not None:
        review = (
            (area_delta <= 0.30 and price_delta is not None and price_delta <= 150) or
            (area_delta <= 0.15 and (title_ratio >= 0.30 or longest >= 4) and (price_delta is None or price_delta <= 500))
        )

    return ("strong" if strong else "review" if review else "no"), score, {
        "areaDelta": None if area_delta is None else round(area_delta, 2),
        "priceDelta": None if price_delta is None else round(price_delta, 1),
        "titleRatio": round(title_ratio, 3),
        "shared": sorted(shared, key=lambda x: (-len(x), x))[:6],
    }


def raw_count(x):
    merged = x.get("mergedListings") or []
    if merged:
        return len(merged)
    c = x.get("mergedListingCount")
    try:
        return max(1, int(c))
    except Exception:
        return 1


def make_group(primary, attached_591=None, match_infos=None):
    attached_591 = attached_591 or []
    match_infos = match_infos or []
    members = [primary] + attached_591
    sources = []
    for m in members:
        if m.get("source") not in sources:
            sources.append(m.get("source"))
    compact = [compact_listing(m) for m in members]
    raw_listing_count = sum(raw_count(m) for m in members)
    return {
        "groupId": f"GROUP:{primary.get('id')}",
        "primaryId": primary.get("id"),
        "primarySource": primary.get("source"),
        "road": primary.get("road"),
        "title": primary.get("title"),
        "address": primary.get("address"),
        "price": primary.get("price"),
        "effectivePrice": primary.get("effectivePrice"),
        "size": primary.get("size"),
        "url": primary.get("url"),
        "sourcePublishedAt": primary.get("sourcePublishedAt") if primary.get("sourcePublishedAt") is not None else primary.get("postTime"),
        "sourcePublishedAtType": primary.get("sourcePublishedAtType"),
        "newAt": primary.get("newAt"),
        "active": primary.get("active", True),
        "sources": sources,
        "sourceListings": compact,
        "crossPlatformMerged": len(sources) > 1,
        "crossPlatformMatchInfo": match_infos,
        "rawListingCount": raw_listing_count,
    }


def build_groups(external):
    sinyi = [x for x in external if x.get("source") == "信義房屋"]
    m591 = [x for x in external if x.get("source") == "591"]

    # Every 591 record chooses at most one Sinyi record. A Sinyi record may absorb
    # more than one 591 record only when each match independently clears the strong threshold.
    candidates_by_591 = defaultdict(list)
    review_candidates = []
    for s in sinyi:
        for m in m591:
            if s.get("road") != m.get("road"):
                continue
            level, score, info = cross_source_info(s, m)
            if level == "strong":
                candidates_by_591[m.get("id")].append((score, s, info))
            elif level == "review":
                review_candidates.append({
                    "sinyiId": s.get("id"), "listing591Id": m.get("id"),
                    "score": score, "matchInfo": info,
                })

    attached = defaultdict(list)
    attached_info = defaultdict(list)
    matched_591 = set()
    for m in m591:
        cands = candidates_by_591.get(m.get("id")) or []
        if not cands:
            continue
        cands.sort(key=lambda z: z[0], reverse=True)
        score, s, info = cands[0]
        matched_591.add(m.get("id"))
        attached[s.get("id")].append(m)
        attached_info[s.get("id")].append({
            "listing591Id": m.get("id"), "score": score, **info
        })

    groups = []
    for s in sinyi:
        groups.append(make_group(s, attached.get(s.get("id"), []), attached_info.get(s.get("id"), [])))
    for m in m591:
        if m.get("id") not in matched_591:
            groups.append(make_group(m))

    return groups, review_candidates


def classify_group(group, company, road_status):
    best = None
    for member in group.get("sourceListings") or []:
        st, sc, yc, info = base.classify(member, company, road_status)
        rank = {"company_match": 3, "review": 2, "missing": 1, "unavailable": 0}.get(st, 0)
        row = (rank, sc, st, yc, info, member)
        if best is None or (rank, sc) > (best[0], best[1]):
            best = row
    if best is None:
        return "unavailable", 0, None, {"reason": "群組沒有可比對來源"}, None
    _, sc, st, yc, info, member = best
    info = dict(info or {})
    info["evidenceSource"] = member.get("source")
    info["evidenceListingId"] = member.get("id")
    return st, sc, yc, info, member


def resolve_company_duplicates(comparisons):
    by_company = defaultdict(list)
    for c in comparisons:
        if c.get("status") == "company_match" and c.get("companyCandidate"):
            by_company[c["companyCandidate"].get("id")].append(c)
    downgraded = 0
    for company_id, rows in by_company.items():
        if not company_id or len(rows) <= 1:
            continue
        rows.sort(key=lambda x: x.get("score", -999), reverse=True)
        keeper = rows[0]
        for row in rows[1:]:
            row["status"] = "review"
            row["statusLabel"] = "待確認"
            info = row.setdefault("matchInfo", {})
            info["reason"] = f"同一公司案件 {company_id} 已優先配對給 {keeper.get('groupId')}，避免庫存重複計數"
            info["companyCandidateConflict"] = True
            downgraded += 1
    return downgraded


def main():
    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    company, logs, road_status = base.fetch_company()
    company, snap = base.load_har_fallback(company, road_status, logs)

    uniq = {}
    for x in company:
        uniq[(x.get("road"), x.get("id"))] = x
    company = list(uniq.values())

    external = [
        x for x in state.get("listings", [])
        if x.get("active", True) and x.get("source") in {"591", "信義房屋"}
    ]
    groups, cross_reviews = build_groups(external)

    comparisons = []
    for group in groups:
        st, sc, yc, info, evidence = classify_group(group, company, road_status)
        comparisons.append({
            "groupId": group.get("groupId"),
            "primaryId": group.get("primaryId"),
            "primarySource": group.get("primarySource"),
            "road": group.get("road"),
            "status": st,
            "statusLabel": {
                "company_match": "庫存", "review": "待確認",
                "missing": "未接回", "unavailable": "尚未比對",
            }[st],
            "score": sc,
            "companyCandidate": None if not yc else {
                "id": yc.get("id"), "title": yc.get("title"), "address": yc.get("address"),
                "area": yc.get("area"), "price": yc.get("price"), "url": yc.get("url"),
                "sourceMode": yc.get("sourceMode"),
            },
            "matchInfo": info,
        })

    conflict_downgraded = resolve_company_duplicates(comparisons)
    counts = {"company_match": 0, "review": 0, "missing": 0, "unavailable": 0}
    for c in comparisons:
        counts[c["status"]] += 1

    raw_listing_count = sum(g.get("rawListingCount", 1) for g in groups)
    cross_merged = sum(1 for g in groups if g.get("crossPlatformMerged"))
    fetch_mode = "housefun_yungching_proxy" if any(
        st.get("mode") == "housefun_yungching_proxy" for st in road_status.values()
    ) else "har_snapshot"

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceDataUpdatedAt": state.get("updatedAt"),
        "mode": "preview_only_sinyi_first_grouping",
        "fetchMode": fetch_mode,
        "company": "永慶房屋",
        "companyDataSource": "好房網公開買屋頁（僅篩選永慶房屋(股)公司）＋必要時 HAR fallback",
        "companyListingCount": len(company),
        "companySnapshotCapturedAt": snap.get("capturedAt") if snap else None,
        "coveredRoads": [r for r in base.ROADS if (road_status.get(r) or {}).get("available")],
        "externalActiveCount": len(external),
        "propertyGroupCount": len(groups),
        "rawListingCount": raw_listing_count,
        "crossPlatformMergedGroupCount": cross_merged,
        "crossSourceReviewCount": len(cross_reviews),
        "companyConflictDowngradedCount": conflict_downgraded,
        "counts": counts,
        "roadStatus": road_status,
        "propertyGroups": groups,
        "comparisons": comparisons,
        "crossSourceReviewCandidates": cross_reviews,
        "companyListings": company,
        "logs": logs,
        "note": "PREVIEW：先整併信義房屋與 591，同戶時以信義為主資料、591 保留為補充來源；再以整併後房屋群組比對永慶公開直營庫存。公司庫存統計以房屋群組計算，同一公司候選若被多組搶到只保留最高分，其餘降為待確認。",
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "company": len(company), "externalTopLevel": len(external), "groups": len(groups),
        "rawListings": raw_listing_count, "crossPlatformMerged": cross_merged,
        "crossSourceReview": len(cross_reviews), "companyConflictDowngraded": conflict_downgraded,
        **counts,
    }, ensure_ascii=False))
    for line in logs:
        print(line)


if __name__ == "__main__":
    main()
