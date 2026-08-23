import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

import compare_yungching_preview_v3 as prev

# PREVIEW v4 flow:
# 1) regroup 591 against 591 first
# 2) compare the regrouped 591 property against Sinyi, with Sinyi as primary
# 3) compare the final property group against company inventory
# Production monitor data and production UI are not changed.

REGROUP_STATS = {
    "original591TopLevel": 0,
    "regrouped591TopLevel": 0,
    "regrouped591ClusterCount": 0,
    "regrouped591AbsorbedCount": 0,
    "clusterFloorConflictBlocked": 0,
}
GROUP_INTEGRITY_STATS = {
    "crossSourceMultiAttachFloorConflictBlocked": 0,
}


def area_of(x):
    return prev.area_of(x)


def price_of(x):
    return prev.price_of(x)


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
        return d.get(left, 1) * 10 + d.get(right, 0)
    return d.get(raw)


def title_floor_tokens(text):
    """Extract only subject floors, never the total floor from `3/14樓`."""
    text = str(text or "")
    nums = set()

    spans = []
    for m in re.finditer(r"(\d{1,2})(?:\s*[~～-]\s*(\d{1,2}))?\s*/\s*\d{1,2}\s*樓", text):
        lo = int(m.group(1)); hi = int(m.group(2) or m.group(1))
        if 1 <= lo <= hi <= 99 and hi - lo <= 10:
            nums.update(range(lo, hi + 1))
        spans.append(m.span())
    if spans:
        chars = list(text)
        for start, end in spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[~～-]\s*(\d{1,2})\s*樓", text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 99 and hi - lo <= 10:
            nums.update(range(lo, hi + 1))

    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            nums.add(n)
    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        n = chinese_floor_number(raw)
        if n:
            nums.add(n)
    return nums


def listing_floor_tokens(x):
    floors = set()
    if not x:
        return floors
    floors |= title_floor_tokens(x.get("title"))
    floors |= title_floor_tokens(x.get("address"))
    for m in (x.get("mergedListings") or []):
        floors |= title_floor_tokens(m.get("title"))
        floors |= title_floor_tokens(m.get("address"))
    return floors


def pair_591_info(a, b):
    if a.get("road") != b.get("road"):
        return False, {}

    aa, ba = area_of(a), area_of(b)
    ap, bp = price_of(a), price_of(b)
    ad = abs(aa - ba) if aa is not None and ba is not None else None
    pd = abs(ap - bp) if ap is not None and bp is not None else None

    at = str(a.get("title") or "")
    bt = str(b.get("title") or "")
    shared = prev.base.tokens(at) & prev.base.tokens(bt)
    longest = max((len(x) for x in shared), default=0)
    ratio = SequenceMatcher(None, prev.base.norm(at), prev.base.norm(bt)).ratio()

    af = listing_floor_tokens(a)
    bf = listing_floor_tokens(b)
    floor_conflict = bool(af and bf and af.isdisjoint(bf))

    exact_fingerprint = bool(
        ad is not None and ad <= 0.05 and
        pd is not None and pd <= 1 and
        not floor_conflict
    )

    strong = exact_fingerprint
    if not strong and not floor_conflict and ad is not None and pd is not None:
        strong = (
            (ad <= 0.12 and pd <= 30 and (ratio >= 0.30 or longest >= 3)) or
            (ad <= 0.30 and pd <= 10 and (ratio >= 0.42 or longest >= 4))
        )

    return strong, {
        "areaDelta": None if ad is None else round(ad, 2),
        "priceDelta": None if pd is None else round(pd, 1),
        "titleRatio": round(ratio, 3),
        "shared": sorted(shared, key=lambda x: (-len(x), x))[:6],
        "floorConflict": floor_conflict,
        "floorsA": sorted(af),
        "floorsB": sorted(bf),
        "exactFingerprint": exact_fingerprint,
    }


def flatten_raw_591(x):
    rows = []
    seen = set()

    def add(src):
        row = dict(src or {})
        rid = row.get("id") or row.get("houseId") or row.get("url")
        if not rid or rid in seen:
            return
        seen.add(rid)
        row.setdefault("source", "591")
        row.setdefault("road", x.get("road"))
        rows.append(row)

    merged = x.get("mergedListings") or []
    if merged:
        for m in merged:
            add(m)
    else:
        add(x)
    return rows


def regroup_591(m591):
    n = len(m591)
    REGROUP_STATS["original591TopLevel"] = n
    REGROUP_STATS["clusterFloorConflictBlocked"] = 0
    parent = list(range(n))
    cluster_floors = {i: set(listing_floor_tokens(m591[i])) for i in range(n)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union_if_floor_safe(i, j):
        ri, rj = find(i), find(j)
        if ri == rj:
            return True
        fi = cluster_floors.get(ri, set())
        fj = cluster_floors.get(rj, set())
        # Critical transitive guard: unknown-floor rows may connect compatible data,
        # but they may never bridge two clusters that already state disjoint floors.
        if fi and fj and fi.isdisjoint(fj):
            REGROUP_STATS["clusterFloorConflictBlocked"] += 1
            return False
        parent[rj] = ri
        cluster_floors[ri] = set(fi) | set(fj)
        cluster_floors.pop(rj, None)
        return True

    pair_evidence = defaultdict(list)
    for i in range(n):
        for j in range(i + 1, n):
            ok, info = pair_591_info(m591[i], m591[j])
            if not ok:
                continue
            if not union_if_floor_safe(i, j):
                continue
            pair_evidence[i].append({"otherId": m591[j].get("id"), **info})
            pair_evidence[j].append({"otherId": m591[i].get("id"), **info})

    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    regrouped = []
    merged_cluster_count = 0
    absorbed = 0

    for indices in clusters.values():
        indices.sort(
            key=lambda i: (
                m591[i].get("sourcePublishedAt")
                if m591[i].get("sourcePublishedAt") is not None
                else m591[i].get("postTime") or 0
            ),
            reverse=True,
        )
        rep = dict(m591[indices[0]])

        raw = []
        seen = set()
        top_ids = []
        evidence = []
        for i in indices:
            src = m591[i]
            top_ids.append(src.get("id"))
            evidence.extend(pair_evidence.get(i) or [])
            for row in flatten_raw_591(src):
                rid = row.get("id") or row.get("houseId") or row.get("url")
                if rid in seen:
                    continue
                seen.add(rid)
                raw.append(row)

        rep["mergedListings"] = raw
        rep["mergedListingCount"] = len(raw)
        rep["mergedActiveListingCount"] = sum(1 for r in raw if r.get("active", True))
        rep["preview591Regrouped"] = len(indices) > 1
        rep["preview591TopLevelCount"] = len(indices)
        rep["preview591TopLevelIds"] = [x for x in top_ids if x]
        rep["preview591RegroupEvidence"] = evidence[:20]
        rep["preview591ClusterFloors"] = sorted(set().union(*(listing_floor_tokens(m591[i]) for i in indices)))

        if len(indices) > 1:
            merged_cluster_count += 1
            absorbed += len(indices) - 1
        regrouped.append(rep)

    REGROUP_STATS["regrouped591TopLevel"] = len(regrouped)
    REGROUP_STATS["regrouped591ClusterCount"] = merged_cluster_count
    REGROUP_STATS["regrouped591AbsorbedCount"] = absorbed
    return regrouped


def cross_source_cluster_info(sinyi, m591_group):
    level, score, info = prev.cross_source_info(sinyi, m591_group)
    info = dict(info or {})

    top_count = int(m591_group.get("preview591TopLevelCount") or 1)
    ad = info.get("areaDelta")
    pd = info.get("priceDelta")
    corroborated = bool(
        top_count >= 2 and
        ad is not None and ad <= 0.12 and
        pd is not None and pd <= 30
    )
    if level != "strong" and corroborated:
        level = "strong"
        score = max(score, 20)
        info["multi591Corroborated"] = True
        info["reason"] = "多筆591先互相整併後，坪數與信義幾乎一致且價格差在30萬內，改以信義為主合併"
    return level, score, info


def build_groups(external):
    sinyi = [x for x in external if x.get("source") == "信義房屋"]
    raw_591 = [x for x in external if x.get("source") == "591"]
    m591 = regroup_591(raw_591)

    GROUP_INTEGRITY_STATS["crossSourceMultiAttachFloorConflictBlocked"] = 0
    candidates_by_591 = defaultdict(list)
    review_candidates = []

    for s in sinyi:
        for m in m591:
            if s.get("road") != m.get("road"):
                continue
            level, score, info = cross_source_cluster_info(s, m)
            if level == "strong":
                candidates_by_591[m.get("id")].append((score, s, info))
            elif level == "review":
                review_candidates.append({
                    "sinyiId": s.get("id"),
                    "listing591Id": m.get("id"),
                    "score": score,
                    "matchInfo": info,
                    "reason": "信義與591整併群組資料接近，但未達自動整併門檻",
                })

    attached = defaultdict(list)
    attached_info = defaultdict(list)
    attached_floors = defaultdict(set)
    matched_591 = set()

    for m in m591:
        cands = candidates_by_591.get(m.get("id")) or []
        if not cands:
            continue
        cands.sort(key=lambda z: z[0], reverse=True)

        if len(cands) > 1:
            top_score, top_s, top_info = cands[0]
            second_score, second_s, second_info = cands[1]
            top_text = max(top_info.get("titleRatio") or 0, 0)
            second_text = max(second_info.get("titleRatio") or 0, 0)
            ambiguous = (
                abs(top_score - second_score) <= 1 and
                max(top_text, second_text) < 0.25 and
                not top_info.get("shared") and
                not second_info.get("shared")
            )
            if ambiguous:
                review_candidates.append({
                    "sinyiId": top_s.get("id"),
                    "listing591Id": m.get("id"),
                    "score": top_score,
                    "matchInfo": top_info,
                    "reason": f"591整併群組同時符合多筆信義案件（另含 {second_s.get('id')}），暫不自動整併",
                })
                continue

        score, s, info = cands[0]
        sid = s.get("id")
        m_floors = set(info.get("listing591Floors") or m.get("preview591ClusterFloors") or [])
        s_floors = set(info.get("sinyiFloors") or listing_floor_tokens(s))
        already = attached_floors[sid]
        # If Sinyi itself does not state a floor, do not let it become a bridge that
        # absorbs multiple explicit, mutually exclusive 591 floors.
        if not s_floors and already and m_floors and already.isdisjoint(m_floors):
            GROUP_INTEGRITY_STATS["crossSourceMultiAttachFloorConflictBlocked"] += 1
            review_candidates.append({
                "sinyiId": sid,
                "listing591Id": m.get("id"),
                "score": score,
                "matchInfo": info,
                "reason": "同一筆樓層未知的信義案件已連結其他明確樓層591；本筆樓層不同，暫不自動整併",
            })
            continue

        matched_591.add(m.get("id"))
        attached[sid].append(m)
        attached_info[sid].append({
            "listing591Id": m.get("id"),
            "score": score,
            "preview591TopLevelCount": m.get("preview591TopLevelCount") or 1,
            "preview591TopLevelIds": m.get("preview591TopLevelIds") or [m.get("id")],
            **info,
        })
        if m_floors:
            attached_floors[sid].update(m_floors)

    groups = []
    for s in sinyi:
        groups.append(prev.make_group(s, attached.get(s.get("id"), []), attached_info.get(s.get("id"), [])))
    for m in m591:
        if m.get("id") not in matched_591:
            groups.append(prev.make_group(m))

    return groups, review_candidates


def main():
    prev.build_groups = build_groups
    prev.main()

    path = prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company"
    payload["preview591Regroup"] = dict(REGROUP_STATS)
    payload["schemeAGroupIntegrity"] = dict(GROUP_INTEGRITY_STATS)
    payload["note"] = (
        "PREVIEW：先讓591重新互相比對並整併，再與信義房屋比對；同戶一律以信義為主資料、591保留在來源明細；"
        "最後才拿整併後的房屋群組比對永慶公開直營庫存。群組層級禁止透過樓層未知資料橋接兩個明確不同樓層。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "preview591Regroup": REGROUP_STATS,
        "schemeAGroupIntegrity": GROUP_INTEGRITY_STATS,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
