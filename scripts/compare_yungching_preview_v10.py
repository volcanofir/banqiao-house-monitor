"""Scheme A Preview v10: integrate Rakuya into the same property grouping as 591/Sinyi.

Preview only. 591 is regrouped first, then Sinyi remains the preferred primary source.
Rakuya ads are regrouped among themselves with the same area/price/title/floor evidence,
then attached to the best existing property group when the match is strong and unambiguous.
"""

import json
from collections import defaultdict
from pathlib import Path

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v8 as v8

ORIGINAL_BUILD_GROUPS = v4.build_groups
RAKUYA_SNAPSHOT = Path("docs/preview/rakuya-seven-roads.json")
ENRICHED = Path("docs/preview/scheme-a-external-enriched.json")

RAKUYA_STATS = {
    "inputCount": 0,
    "regroupedCount": 0,
    "mergedClusterCount": 0,
    "absorbedCount": 0,
    "attachedToExistingGroupCount": 0,
    "standaloneGroupCount": 0,
    "ambiguousReviewCount": 0,
    "floorConflictBlocked": 0,
}


def raw_id(x):
    return x.get("id") or x.get("houseId") or x.get("url")


def flatten_rakuya(x):
    merged = x.get("mergedListings") or []
    if merged:
        return [dict(m) for m in merged]
    return [dict(x)]


def regroup_rakuya(rows):
    n = len(rows)
    RAKUYA_STATS["inputCount"] = n
    RAKUYA_STATS["floorConflictBlocked"] = 0
    parent = list(range(n))
    cluster_floors = {i: set(v4.listing_floor_tokens(rows[i])) for i in range(n)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri == rj:
            return True
        fi, fj = cluster_floors.get(ri, set()), cluster_floors.get(rj, set())
        if fi and fj and fi.isdisjoint(fj):
            RAKUYA_STATS["floorConflictBlocked"] += 1
            return False
        parent[rj] = ri
        cluster_floors[ri] = set(fi) | set(fj)
        cluster_floors.pop(rj, None)
        return True

    for i in range(n):
        for j in range(i + 1, n):
            ok, _ = v4.pair_591_info(rows[i], rows[j])
            if ok:
                union(i, j)

    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    out = []
    merged_clusters = 0
    absorbed = 0
    for indices in clusters.values():
        indices.sort(
            key=lambda i: str(rows[i].get("sourcePublishedAt") or rows[i].get("firstSeenAt") or ""),
            reverse=True,
        )
        rep = dict(rows[indices[0]])
        raw = []
        seen = set()
        for i in indices:
            for member in flatten_rakuya(rows[i]):
                rid = raw_id(member)
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                member["source"] = "樂屋網"
                raw.append(member)

        rep["source"] = "樂屋網"
        rep["mergedListings"] = raw
        rep["mergedListingCount"] = len(raw)
        rep["mergedActiveListingCount"] = sum(1 for x in raw if x.get("active", True))
        rep["rakuyaRegrouped"] = len(indices) > 1
        rep["rakuyaClusterFloors"] = sorted(set().union(*(v4.listing_floor_tokens(rows[i]) for i in indices)))

        if len(indices) > 1:
            merged_clusters += 1
            absorbed += len(indices) - 1
        out.append(rep)

    RAKUYA_STATS["regroupedCount"] = len(out)
    RAKUYA_STATS["mergedClusterCount"] = merged_clusters
    RAKUYA_STATS["absorbedCount"] = absorbed
    return out


def candidate_for_group(group, rakuya):
    best = None
    for member in group.get("sourceListings") or []:
        level, score, info = v4.cross_source_cluster_info(member, rakuya)
        rec = {
            "level": level,
            "score": score,
            "info": dict(info or {}),
            "member": member,
        }
        if best is None or score > best["score"]:
            best = rec
    return best


def attach_rakuya(group, rakuya, evidence):
    compact = v4.prev.compact_listing(rakuya)
    group.setdefault("sourceListings", []).append(compact)
    sources = list(group.get("sources") or [])
    if "樂屋網" not in sources:
        sources.append("樂屋網")
    group["sources"] = sources
    group["crossPlatformMerged"] = len(sources) > 1
    group["rawListingCount"] = int(group.get("rawListingCount") or 1) + v4.prev.raw_count(rakuya)
    group.setdefault("crossPlatformMatchInfo", []).append({
        "rakuyaId": rakuya.get("id"),
        "score": evidence.get("score"),
        "evidenceSource": (evidence.get("member") or {}).get("source"),
        **(evidence.get("info") or {}),
    })


def build_groups_with_rakuya(external):
    base_external = [x for x in external if x.get("source") in {"591", "信義房屋"}]
    rakuya_rows = [x for x in external if x.get("source") == "樂屋網"]

    groups, reviews = ORIGINAL_BUILD_GROUPS(base_external)
    rakuya_groups = regroup_rakuya(rakuya_rows)

    RAKUYA_STATS["attachedToExistingGroupCount"] = 0
    RAKUYA_STATS["standaloneGroupCount"] = 0
    RAKUYA_STATS["ambiguousReviewCount"] = 0

    for rk in rakuya_groups:
        candidates = []
        review_candidates = []
        for idx, group in enumerate(groups):
            if group.get("road") != rk.get("road"):
                continue
            ev = candidate_for_group(group, rk)
            if not ev:
                continue
            if ev["level"] == "strong":
                candidates.append((ev["score"], idx, ev))
            elif ev["level"] == "review":
                review_candidates.append((ev["score"], idx, ev))

        candidates.sort(key=lambda x: x[0], reverse=True)
        attached = False
        if candidates:
            top_score, top_idx, top = candidates[0]
            ambiguous = False
            if len(candidates) > 1:
                second_score, second_idx, second = candidates[1]
                ti, si = top.get("info") or {}, second.get("info") or {}
                ambiguous = bool(
                    top_score - second_score <= 1
                    and ti.get("floorRelation") != "match"
                    and si.get("floorRelation") != "match"
                    and max(ti.get("titleRatio") or 0, si.get("titleRatio") or 0) < 0.30
                    and not ti.get("shared")
                    and not si.get("shared")
                )
                if ambiguous:
                    reviews.append({
                        "rakuyaId": rk.get("id"),
                        "groupId": groups[top_idx].get("groupId"),
                        "otherGroupId": groups[second_idx].get("groupId"),
                        "score": top_score,
                        "matchInfo": ti,
                        "reason": "樂屋刊登同時高分命中兩個既有房屋群組，證據不足以唯一辨識，暫不自動整併",
                    })
                    RAKUYA_STATS["ambiguousReviewCount"] += 1

            if not ambiguous:
                attach_rakuya(groups[top_idx], rk, top)
                RAKUYA_STATS["attachedToExistingGroupCount"] += 1
                attached = True

        if not attached:
            if review_candidates and not candidates:
                review_candidates.sort(key=lambda x: x[0], reverse=True)
                score, idx, ev = review_candidates[0]
                reviews.append({
                    "rakuyaId": rk.get("id"),
                    "groupId": groups[idx].get("groupId"),
                    "score": score,
                    "matchInfo": ev.get("info") or {},
                    "reason": "樂屋與既有房屋群組資料接近，但未達自動整併門檻",
                })
            groups.append(v4.prev.make_group(rk))
            RAKUYA_STATS["standaloneGroupCount"] += 1

    return groups, reviews


def main():
    if not RAKUYA_SNAPSHOT.exists() or not ENRICHED.exists():
        raise RuntimeError("missing Rakuya snapshot or enriched Scheme A snapshot")

    snap = json.loads(RAKUYA_SNAPSHOT.read_text(encoding="utf-8"))
    if snap.get("complete") is not True:
        raise RuntimeError("Rakuya snapshot incomplete")

    v4.build_groups = build_groups_with_rakuya
    v8.main()

    path = v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_state = json.loads(ENRICHED.read_text(encoding="utf-8"))
    meta = (source_state.get("previewSources") or {}).get("樂屋網") or {}

    payload["mode"] = "preview_only_591_sinyi_rakuya_grouping_then_company_v10"
    payload["rakuyaIntegrated"] = True
    payload["rakuyaGrouping"] = dict(RAKUYA_STATS)
    payload["rakuyaSnapshot"] = {
        "updatedAt": meta.get("updatedAt") or snap.get("updatedAt"),
        "status": meta.get("status") or "ok",
        "totalCount": meta.get("totalCount") or snap.get("placementCount"),
        "uniqueListingCount": meta.get("uniqueListingCount") or snap.get("uniqueListingCount"),
        "roadCounts": meta.get("roadCounts") or snap.get("roadCounts"),
        "changes": meta.get("changes") or snap.get("changes"),
        "complete": True,
    }
    payload["note"] = (
        "PREVIEW v10：591先重新分組，信義維持優先主資料；樂屋七路段刊登先依同一套坪數、價格、"
        "標題與樓層證據做站內去重，再與既有591/信義房屋群組整併。最後整個房屋群組再比對永慶官方DOM。"
        "明確樓層衝突或多組近似且無唯一證據時不自動合併。正式監控資料不改寫。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "mode": payload["mode"],
        "propertyGroupCount": payload.get("propertyGroupCount"),
        "rawListingCount": payload.get("rawListingCount"),
        "rakuyaGrouping": payload.get("rakuyaGrouping"),
        "counts": payload.get("counts"),
        "recentOffMarketCount": payload.get("recentOffMarketCount"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
