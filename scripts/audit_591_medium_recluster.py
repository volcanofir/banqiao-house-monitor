"""Replay medium-risk 591 groups with a stricter identity rule.

Diagnostic only. Does not alter canonical Preview or production monitoring data.
The experiment removes the old 'one generic shared feature is enough' shortcut and
requires stronger evidence when price/area are identical.
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import dedupe_listings_v2 as d

GAP = Path("docs/preview/company-gap.json")
WEAK = Path("docs/preview/scheme-a-weak-group-audit.json")
OUT = Path("docs/preview/591-medium-recluster-audit.json")

DISTINCTIVE = {"頂加", "三面採光", "內外梯", "雙車位", "地下室", "店面", "透天", "收租"}
GENERIC = {"公寓", "電梯", "一樓", "二樓", "三樓", "三房", "四房", "方正", "邊間", "前後陽台", "天然瓦斯"}


def pair_reason(a, b):
    if a.get("source") != "591" or b.get("source") != "591" or a.get("road") != b.get("road"):
        return False, "scope"
    aa, ab = d.number(a.get("size")), d.number(b.get("size"))
    pa, pb = d.number(a.get("price")), d.number(b.get("price"))
    if aa is None or ab is None or d.conflicts(a, b):
        return False, "conflict_or_missing"
    ad = abs(aa-ab)
    pd = None if pa is None or pb is None else abs(pa-pb)
    sim = d.similarity(a.get("title"), b.get("title"))
    if d.text_key(a.get("title")) and d.text_key(a.get("title")) == d.text_key(b.get("title")) and ad <= .15:
        return True, "exact_title"
    xa, xb = d.numbered_address(a), d.numbered_address(b)
    if xa and xb and xa == xb and ad <= .20 and (pd is None or pd <= max(30.0, min(pa,pb)*.02)):
        return True, "same_numbered_address"
    la, lb = d.lane_address(a), d.lane_address(b)
    if la and lb and la == lb and pd is not None and pd <= 1 and ad <= .15:
        return True, "same_lane"
    ca, cb = d.community(a), d.community(b)
    if ca and cb and ca == cb and pd is not None and pd <= 1 and ad <= .15:
        return True, "same_community"
    if ca and cb and ca != cb:
        return False, "different_community"
    if pd is None or pd > 1 or ad > .05:
        return False, "price_area"
    fa, fb = d.features(a), d.features(b)
    common = fa & fb
    if common & DISTINCTIVE:
        return True, "distinctive_feature"
    generic = common & GENERIC
    if len(generic) >= 2:
        return True, "two_generic_features"
    if sim >= .30:
        return True, "title_similarity"
    return False, "weak_single_or_none"


def floor_hint_set(rows):
    return {d.floor_hint(x) for x in rows if d.floor_hint(x) is not None}


def room_hint_set(rows):
    return {d.room_hint(x) for x in rows if d.room_hint(x) is not None}


def cluster_compatible(item, members):
    # Prevent transitive unknown rows from bridging explicit floor/room conflicts.
    if any(d.conflicts(item, x) for x in members):
        return False
    item_floor = d.floor_hint(item)
    floors = floor_hint_set(members)
    if item_floor is not None and floors and item_floor not in floors:
        return False
    item_room = d.room_hint(item)
    rooms = room_hint_set(members)
    if item_room is not None and rooms and item_room not in rooms:
        return False
    return True


def recluster(rows):
    clusters=[]
    edge_reasons=Counter()
    for item in rows:
        chosen=None
        chosen_reason=None
        for idx, members in enumerate(clusters):
            if not cluster_compatible(item, members):
                continue
            reasons=[]
            for other in members:
                ok, reason=pair_reason(item, other)
                if ok: reasons.append(reason)
            if reasons:
                chosen=idx
                chosen_reason=sorted(reasons, key=lambda x:(x not in {"same_numbered_address","same_lane","same_community","exact_title"},x))[0]
                break
        if chosen is None:
            clusters.append([item])
        else:
            clusters[chosen].append(item)
            edge_reasons[chosen_reason]+=1
    return clusters, edge_reasons


def flatten(g):
    out=[]; seen=set()
    for src in g.get("sourceListings") or []:
        if src.get("source") != "591":
            continue
        for x in (src.get("mergedListings") or [src]):
            rid=str(x.get("id") or "")
            if not rid or rid in seen: continue
            seen.add(rid)
            y=dict(x); y.setdefault("source","591"); y.setdefault("road",g.get("road"))
            out.append(y)
    return out


def member_public(x):
    return {"id":x.get("id"),"title":x.get("title"),"price":x.get("price"),"size":x.get("size"),"floorHint":d.floor_hint(x),"roomHint":d.room_hint(x),"features":sorted(d.features(x))}


def main():
    gap=json.loads(GAP.read_text(encoding="utf-8"))
    weak=json.loads(WEAK.read_text(encoding="utf-8"))
    medium={x.get("groupId") for x in weak.get("groups",[]) if x.get("risk")=="medium"}
    rows=[]; split_groups=0; cluster_sizes=[]
    for g in gap.get("propertyGroups") or []:
        if g.get("groupId") not in medium: continue
        members=flatten(g)
        clusters,reasons=recluster(members)
        sizes=sorted([len(c) for c in clusters],reverse=True)
        split=len(clusters)>1
        if split: split_groups+=1
        cluster_sizes.extend(sizes)
        rows.append({
            "groupId":g.get("groupId"),"road":g.get("road"),"title":g.get("title"),
            "oldMemberCount":len(members),"strictClusterCount":len(clusters),"strictClusterSizes":sizes,
            "wouldSplit":split,"edgeReasons":dict(reasons),
            "clusters":[{"size":len(c),"floors":sorted(floor_hint_set(c)),"rooms":sorted(room_hint_set(c)),"members":[member_public(x) for x in c]} for c in clusters],
        })
    rows.sort(key=lambda x:(not x["wouldSplit"],-x["strictClusterCount"],-x["oldMemberCount"]))
    out={
        "auditedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"previewOnly":True,
        "rule":"same price/area needs distinctive feature, >=2 generic features, title similarity >=0.30, or explicit address/community evidence; cluster-level floor/room conflicts blocked",
        "mediumGroupCount":len(rows),"wouldSplitGroupCount":split_groups,"unchangedGroupCount":len(rows)-split_groups,
        "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("mediumGroupCount","wouldSplitGroupCount","unchangedGroupCount")},ensure_ascii=False))

if __name__=="__main__": main()
