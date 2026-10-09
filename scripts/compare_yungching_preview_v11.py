"""Scheme A Preview v11: integrate Rakuya + 5168 into the same property grouping.

Base 591/Sinyi grouping stays unchanged. Each auxiliary source is first de-duplicated
inside its own source using the existing area/price/title/floor evidence (5168 also
uses its own groupSid when available), then attached to the best existing property
group only when evidence is strong and unambiguous.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v8 as v8

ORIGINAL_BUILD_GROUPS = v4.build_groups
ENRICHED = Path("docs/preview/scheme-a-external-enriched.json")
RAKUYA_SNAPSHOT = Path("docs/preview/rakuya-seven-roads.json")
HOUSEPRICE_SNAPSHOT = Path("docs/preview/houseprice-seven-roads.json")

SALE_NEW_WINDOW_DAYS = 7


def _time_value(value):
    if value in (None, ""):
        return None
    try:
        n=float(value)
        if n > 0:
            return n if n >= 1_000_000_000_000 else n * 1000
    except (TypeError, ValueError):
        pass
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except Exception:
        return None


def _walk_listing_times(row, source_hint=None):
    """Yield source-original times first; monitoring first-seen is fallback only."""
    source=row.get("source") or source_hint
    original=_time_value(row.get("sourcePublishedAt"))
    if original:
        yield ("original", original, source)
    for member in row.get("mergedListings") or []:
        member_source=member.get("source") or source
        original=_time_value(member.get("sourcePublishedAt"))
        if original:
            yield ("original", original, member_source)


def annotate_property_first_publish(group):
    originals=[]
    for item in [group] + list(group.get("sourceListings") or []):
        originals.extend(_walk_listing_times(item, group.get("primarySource")))

    if originals:
        _, ms, source=min(originals, key=lambda x:x[1])
        basis="earliest_source_original"
    else:
        fallbacks=[]
        def add_fallback(row, source_hint=None):
            source=row.get("source") or source_hint
            for key in ("monitorFirstSeenAt","firstSeenAt","newAt"):
                ms=_time_value(row.get(key))
                if ms:
                    fallbacks.append((key,ms,source))
            for member in row.get("mergedListings") or []:
                add_fallback(member, source)
        for item in [group] + list(group.get("sourceListings") or []):
            add_fallback(item, group.get("primarySource"))
        if not fallbacks:
            group["propertyFirstPublishedAt"]=None
            group["propertyFirstPublishedSource"]=None
            group["propertyFirstPublishedBasis"]="unavailable"
            return group
        _, ms, source=min(fallbacks, key=lambda x:x[1])
        basis="earliest_monitor_seen_fallback"

    group["propertyFirstPublishedAt"]=datetime.fromtimestamp(ms/1000, timezone.utc).isoformat(timespec="seconds")
    group["propertyFirstPublishedSource"]=source
    group["propertyFirstPublishedBasis"]=basis
    return group



def blank_stats():
    return {
        "inputCount": 0,
        "regroupedCount": 0,
        "mergedClusterCount": 0,
        "absorbedCount": 0,
        "attachedToExistingGroupCount": 0,
        "standaloneGroupCount": 0,
        "ambiguousReviewCount": 0,
        "floorConflictBlocked": 0,
        "directGroupIdMergeCount": 0,
    }


RAKUYA_STATS = blank_stats()
HOUSEPRICE_STATS = blank_stats()


def raw_id(x):
    return x.get("id") or x.get("houseId") or x.get("url")


def flatten_source(x, source):
    merged=x.get("mergedListings") or []
    rows=[dict(m) for m in merged] if merged else [dict(x)]
    for row in rows:
        row["source"]=source
    return rows


def direct_same_source_identity(a,b,source):
    if source!="5168":
        return False
    ga=a.get("housepriceGroupSid")
    gb=b.get("housepriceGroupSid")
    return bool(ga not in (None,"") and gb not in (None,"") and str(ga)==str(gb))


def regroup_source(rows, source, stats):
    n=len(rows)
    stats.update(blank_stats())
    stats["inputCount"]=n
    parent=list(range(n))
    cluster_floors={i:set(v4.listing_floor_tokens(rows[i])) for i in range(n)}

    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i

    def union(i,j,direct=False):
        ri,rj=find(i),find(j)
        if ri==rj:
            return True
        fi,fj=cluster_floors.get(ri,set()),cluster_floors.get(rj,set())
        if fi and fj and fi.isdisjoint(fj):
            stats["floorConflictBlocked"]+=1
            return False
        parent[rj]=ri
        cluster_floors[ri]=set(fi)|set(fj)
        cluster_floors.pop(rj,None)
        if direct:
            stats["directGroupIdMergeCount"]+=1
        return True

    for i in range(n):
        for j in range(i+1,n):
            direct=direct_same_source_identity(rows[i],rows[j],source)
            ok,_=v4.pair_591_info(rows[i],rows[j])
            if direct or ok:
                union(i,j,direct=direct)

    clusters=defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    out=[]
    for indices in clusters.values():
        indices.sort(
            key=lambda i: str(
                rows[i].get("sourcePublishedAt")
                or rows[i].get("newAt")
                or rows[i].get("monitorFirstSeenAt")
                or rows[i].get("firstSeenAt")
                or ""
            ),
            reverse=True,
        )
        rep=dict(rows[indices[0]])
        raw=[]
        seen=set()
        for i in indices:
            for member in flatten_source(rows[i],source):
                rid=raw_id(member)
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                raw.append(member)
        rep["source"]=source
        rep["mergedListings"]=raw
        rep["mergedListingCount"]=len(raw)
        rep["mergedActiveListingCount"]=sum(1 for x in raw if x.get("active",True))
        rep["auxiliaryRegrouped"]=len(indices)>1
        rep["auxiliaryClusterFloors"]=sorted(set().union(*(v4.listing_floor_tokens(rows[i]) for i in indices)))
        if len(indices)>1:
            stats["mergedClusterCount"]+=1
            stats["absorbedCount"]+=len(indices)-1
        out.append(rep)

    stats["regroupedCount"]=len(out)
    return out


def candidate_for_group(group,row):
    best=None
    for member in group.get("sourceListings") or []:
        level,score,info=v4.cross_source_cluster_info(member,row)
        rec={"level":level,"score":score,"info":dict(info or {}),"member":member}
        if best is None or score>best["score"]:
            best=rec
    return best


def attach_source(group,row,source,evidence):
    compact=v4.prev.compact_listing(row)
    group.setdefault("sourceListings",[]).append(compact)
    sources=list(group.get("sources") or [])
    if source not in sources:
        sources.append(source)
    group["sources"]=sources
    group["crossPlatformMerged"]=len(sources)>1
    group["rawListingCount"]=int(group.get("rawListingCount") or 1)+v4.prev.raw_count(row)
    group.setdefault("crossPlatformMatchInfo",[]).append({
        "source":source,
        "sourceId":row.get("id"),
        "score":evidence.get("score"),
        "evidenceSource":(evidence.get("member") or {}).get("source"),
        **(evidence.get("info") or {}),
    })


def integrate_source(groups,reviews,rows,source,stats):
    grouped=regroup_source(rows,source,stats)
    for row in grouped:
        strong=[]
        review=[]
        for idx,group in enumerate(groups):
            if group.get("road")!=row.get("road"):
                continue
            ev=candidate_for_group(group,row)
            if not ev:
                continue
            if ev["level"]=="strong":
                strong.append((ev["score"],idx,ev))
            elif ev["level"]=="review":
                review.append((ev["score"],idx,ev))
        strong.sort(key=lambda x:x[0],reverse=True)
        attached=False
        if strong:
            top_score,top_idx,top=strong[0]
            ambiguous=False
            if len(strong)>1:
                second_score,second_idx,second=strong[1]
                ti,si=top.get("info") or {},second.get("info") or {}
                ambiguous=bool(
                    top_score-second_score<=1
                    and ti.get("floorRelation")!="match"
                    and si.get("floorRelation")!="match"
                    and max(ti.get("titleRatio") or 0,si.get("titleRatio") or 0)<0.30
                    and not ti.get("shared")
                    and not si.get("shared")
                )
                if ambiguous:
                    reviews.append({
                        "source":source,
                        "sourceId":row.get("id"),
                        "groupId":groups[top_idx].get("groupId"),
                        "otherGroupId":groups[second_idx].get("groupId"),
                        "score":top_score,
                        "matchInfo":ti,
                        "reason":f"{source}刊登同時高分命中兩個既有房屋群組，證據不足以唯一辨識，暫不自動整併",
                    })
                    stats["ambiguousReviewCount"]+=1
            if not ambiguous:
                attach_source(groups[top_idx],row,source,top)
                stats["attachedToExistingGroupCount"]+=1
                attached=True

        if not attached:
            if review and not strong:
                review.sort(key=lambda x:x[0],reverse=True)
                score,idx,ev=review[0]
                reviews.append({
                    "source":source,
                    "sourceId":row.get("id"),
                    "groupId":groups[idx].get("groupId"),
                    "score":score,
                    "matchInfo":ev.get("info") or {},
                    "reason":f"{source}與既有房屋群組資料接近，但未達自動整併門檻",
                })
            groups.append(v4.prev.make_group(row))
            stats["standaloneGroupCount"]+=1
    return groups,reviews


def build_groups_with_aux_sources(external):
    base=[x for x in external if x.get("source") in {"591","信義房屋"}]
    rakuya=[x for x in external if x.get("source")=="樂屋網"]
    houseprice=[x for x in external if x.get("source")=="5168"]

    groups,reviews=ORIGINAL_BUILD_GROUPS(base)
    groups,reviews=integrate_source(groups,reviews,rakuya,"樂屋網",RAKUYA_STATS)
    groups,reviews=integrate_source(groups,reviews,houseprice,"5168",HOUSEPRICE_STATS)
    return groups,reviews


def snapshot_meta(source_state,source,snap):
    meta=(source_state.get("previewSources") or {}).get(source) or {}
    return {
        "updatedAt":meta.get("updatedAt") or snap.get("updatedAt"),
        "status":meta.get("status") or "ok",
        "totalCount":meta.get("totalCount") or snap.get("placementCount"),
        "uniqueListingCount":meta.get("uniqueListingCount") or snap.get("uniqueListingCount"),
        "roadCounts":meta.get("roadCounts") or snap.get("roadCounts"),
        "changes":meta.get("changes") or snap.get("changes"),
        "complete":True,
    }


def main():
    for path,label in ((RAKUYA_SNAPSHOT,"Rakuya"),(HOUSEPRICE_SNAPSHOT,"5168"),(ENRICHED,"enriched Scheme A")):
        if not path.exists():
            raise RuntimeError(f"missing {label}: {path}")
    rakuya=json.loads(RAKUYA_SNAPSHOT.read_text(encoding="utf-8"))
    houseprice=json.loads(HOUSEPRICE_SNAPSHOT.read_text(encoding="utf-8"))
    if rakuya.get("complete") is not True:
        raise RuntimeError("Rakuya snapshot incomplete")
    if houseprice.get("complete") is not True:
        raise RuntimeError("5168 snapshot incomplete")

    v4.build_groups=build_groups_with_aux_sources
    v8.main()

    path=v4.prev.OUT_PATH
    payload=json.loads(path.read_text(encoding="utf-8"))
    source_state=json.loads(ENRICHED.read_text(encoding="utf-8"))

    # "New property" is property-level, not platform-level. A later repost on
    # Rakuya/591/Sinyi/5168 must never reset an older property's age.
    for group in payload.get("propertyGroups") or []:
        annotate_property_first_publish(group)
    payload["newListingWindowDays"]=SALE_NEW_WINDOW_DAYS
    payload["newListingTimePolicy"]="earliest_source_original_across_merged_property_with_monitor_seen_fallback"

    payload["mode"]="preview_only_591_sinyi_rakuya_5168_grouping_then_company_v11"
    payload["rakuyaIntegrated"]=True
    payload["housepriceIntegrated"]=True
    payload["rakuyaGrouping"]=dict(RAKUYA_STATS)
    payload["housepriceGrouping"]=dict(HOUSEPRICE_STATS)
    payload["rakuyaSnapshot"]=snapshot_meta(source_state,"樂屋網",rakuya)
    payload["housepriceSnapshot"]=snapshot_meta(source_state,"5168",houseprice)
    payload["housepriceSnapshot"]["detailSummary"]=houseprice.get("detailSummary") or {}
    payload["housepriceSnapshot"]["sourceTimePolicy"]=houseprice.get("sourceTimePolicy") or {}
    payload["note"]=(
        "PREVIEW v11：591先重新分組，信義維持優先主資料；樂屋與5168七路段各自先站內去重，"
        "再依坪數、價格、案名與樓層證據依序併入既有房屋群組，最後整組比對永慶官方資料（API主抓、DOM fallback）。"
        "5168另使用其APP API groupSid作站內直接同群證據；任何樓層衝突或多組近似且無唯一證據都不硬合併。"
    )
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "mode":payload["mode"],
        "propertyGroupCount":payload.get("propertyGroupCount"),
        "rawListingCount":payload.get("rawListingCount"),
        "rakuyaGrouping":payload.get("rakuyaGrouping"),
        "housepriceGrouping":payload.get("housepriceGrouping"),
        "counts":payload.get("counts"),
    },ensure_ascii=False))


if __name__=="__main__":
    main()
