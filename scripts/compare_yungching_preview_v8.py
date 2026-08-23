"""Scheme A Preview v8: Sinyi structured floors + unresolved company near-tie guard.

Uses a Preview-only Sinyi-enriched external snapshot. Structured Sinyi floors become
first-class grouping/matching evidence. After v7 comparison, any automatic company
match that still has two different strong Yongching candidates within two score
points is downgraded to review instead of guessing.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v5 as v5
import compare_yungching_preview_v7 as v7

ENRICHED = Path("docs/preview/scheme-a-external-enriched.json")
SINYI_STATS = Path("docs/preview/sinyi-floor-enrichment.json")

ORIGINAL_COMPACT = v4.prev.compact_listing
ORIGINAL_SAFE_LISTING_FLOORS = v7.safe_listing_floor_tokens


def compact_listing_with_structured_floor(x):
    row = ORIGINAL_COMPACT(x)
    for key in (
        "floor", "structuredFloor", "structuredTotalFloor", "floorSourceMode",
        "sinyiCommId", "sinyiCommName", "sinyiObjectId", "sinyiObjectType",
    ):
        if x.get(key) is not None:
            row[key] = x.get(key)
    return row


def safe_listing_floor_tokens_with_structured(x):
    floors = set(ORIGINAL_SAFE_LISTING_FLOORS(x))
    if not x:
        return floors
    raw = x.get("floor")
    if raw not in (None, ""):
        floors |= v7.safe_floor_numbers(raw)
    return floors


def is_strong(score, info):
    info = info or {}
    ad = info.get("areaDelta")
    pd = info.get("priceDelta")
    tr = info.get("titleRatio") or 0
    longest = max((len(x) for x in (info.get("shared") or [])), default=0)
    return bool(
        ad is not None and ad <= 0.30 and
        ((pd is not None and pd <= 30) or tr >= 0.42 or longest >= 4) and
        score >= 10
    )


def best_candidate_evidence(group, candidate):
    best = None
    for member in group.get("sourceListings") or []:
        score, info = v5.company_score(member, candidate)
        record = {
            "score": score,
            "info": dict(info or {}),
            "evidenceSource": member.get("source"),
            "evidenceListingId": member.get("id"),
        }
        if best is None or score > best["score"]:
            best = record
    return best or {"score": -999, "info": {}, "evidenceSource": None, "evidenceListingId": None}


def candidate_public(candidate, evidence):
    return {
        "id": candidate.get("id"),
        "officialId": candidate.get("officialId"),
        "officialCaseId": candidate.get("officialCaseId"),
        "title": candidate.get("title"),
        "area": candidate.get("area"),
        "price": candidate.get("price"),
        "floor": candidate.get("floor"),
        "score": evidence.get("score"),
        "floorRelation": (evidence.get("info") or {}).get("floorRelation"),
        "externalFloors": (evidence.get("info") or {}).get("externalFloors"),
        "companyFloors": (evidence.get("info") or {}).get("companyFloors"),
        "evidenceSource": evidence.get("evidenceSource"),
        "evidenceListingId": evidence.get("evidenceListingId"),
    }


def apply_company_near_tie_guard(payload):
    groups = {x.get("groupId"): x for x in (payload.get("propertyGroups") or [])}
    company = payload.get("companyListings") or []
    examined = 0
    near_ties = []
    downgraded = 0

    for row in payload.get("comparisons") or []:
        if row.get("status") != "company_match":
            continue
        examined += 1
        group = groups.get(row.get("groupId"))
        if not group:
            continue
        road_candidates = [x for x in company if x.get("road") == group.get("road")]
        strong = []
        for candidate in road_candidates:
            evidence = best_candidate_evidence(group, candidate)
            if is_strong(evidence["score"], evidence["info"]):
                strong.append((evidence["score"], candidate, evidence))
        strong.sort(key=lambda z: z[0], reverse=True)

        row["companyStrongCandidateCount"] = len(strong)
        if strong:
            row["companyTopStrongScore"] = strong[0][0]
        if len(strong) >= 2:
            delta = strong[0][0] - strong[1][0]
            row["companySecondStrongScore"] = strong[1][0]
            row["companyStrongScoreDelta"] = delta
            if delta <= 2 and str(strong[0][1].get("id")) != str(strong[1][1].get("id")):
                row["companyNearTieStrong"] = True
                row["status"] = "review"
                row["statusLabel"] = "待確認"
                row["companyNearTieGuardReview"] = True
                row["companyNearTieCandidates"] = [
                    candidate_public(strong[0][1], strong[0][2]),
                    candidate_public(strong[1][1], strong[1][2]),
                ]
                row["reason"] = (
                    str(row.get("reason") or "").strip("；") +
                    "；同一外部房屋仍同時命中兩筆不同永慶官方案件，且強候選分差不超過2分；禁止自動猜測，改列待確認"
                ).strip("；")
                near_ties.append({
                    "groupId": row.get("groupId"),
                    "road": group.get("road"),
                    "title": group.get("title"),
                    "scoreDelta": delta,
                    "candidates": row["companyNearTieCandidates"],
                })
                downgraded += 1
        else:
            row["companyNearTieStrong"] = False

    counts = Counter(str(x.get("status") or "unavailable") for x in (payload.get("comparisons") or []))
    payload["counts"] = {
        "company_match": counts.get("company_match", 0),
        "review": counts.get("review", 0),
        "missing": counts.get("missing", 0),
        "unavailable": counts.get("unavailable", 0),
    }
    remaining_auto_near_ties = sum(
        1 for x in (payload.get("comparisons") or [])
        if x.get("status") == "company_match" and x.get("companyNearTieStrong") is True
    )
    payload["companyNearTieGuard"] = {
        "enabled": True,
        "rule": "同一外部群組若仍有至少兩筆不同永慶 strong 候選且前兩名分差<=2，禁止自動判庫存，全部降為待確認",
        "examinedCompanyMatchCount": examined,
        "downgradedCount": downgraded,
        "remainingAutoNearTieCount": remaining_auto_near_ties,
        "groups": near_ties,
    }


def main():
    if not ENRICHED.exists() or not SINYI_STATS.exists():
        raise RuntimeError("缺少 Preview 信義樓層 enrichment；請先執行 sinyi_preview_floor_enrich.py")

    sinyi_stats = json.loads(SINYI_STATS.read_text(encoding="utf-8"))
    if sinyi_stats.get("complete") is not True:
        raise RuntimeError(f"信義樓層 enrichment 未通過完整性: {sinyi_stats}")

    # Point only the Preview comparator at the enriched copy. Production monitored
    # data stays untouched in docs/data/listings.json.
    v4.prev.DATA_PATH = ENRICHED
    v4.prev.compact_listing = compact_listing_with_structured_floor
    v7.safe_listing_floor_tokens = safe_listing_floor_tokens_with_structured

    v7.main()

    path = v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sinyiFloorEnrichment"] = sinyi_stats
    payload["sinyiStructuredFloorMatching"] = True
    apply_company_near_tie_guard(payload)
    payload["mode"] = "preview_only_591_then_sinyi_structured_floor_then_company_neartie_guard_v8"
    payload["note"] = (
        "PREVIEW v8：591先重新分組，再以信義官方列表 __NEXT_DATA__ 的結構化樓層做跨平台整併，"
        "信義為主；最後比對本輪永慶官方 DOM。若同一外部群組仍有兩筆不同永慶 strong 候選且"
        "分差<=2，不自動猜測，直接列待確認。正式監控資料 docs/data/listings.json 不被改寫。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Add a grouped 10-day off-market history without changing active company counts.
    subprocess.run([sys.executable, "scripts/add_recent_offmarket.py"], check=True)
    payload = json.loads(path.read_text(encoding="utf-8"))

    print(json.dumps({
        "mode": payload["mode"],
        "sinyiFloorEnrichment": {
            "active": sinyi_stats.get("activeSinyiCount"),
            "matched": sinyi_stats.get("matchedOfficialCount"),
            "withFloor": sinyi_stats.get("withStructuredFloorValueCount"),
        },
        "companyNearTieGuard": payload.get("companyNearTieGuard"),
        "counts": payload.get("counts"),
        "recentOffMarketCount": payload.get("recentOffMarketCount"),
        "recentOffMarketRetentionDays": payload.get("recentOffMarketRetentionDays"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()