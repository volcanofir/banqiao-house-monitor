import json
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
}


def area_of(x):
    return prev.area_of(x)


def price_of(x):
    return prev.price_of(x)


def title_floor_tokens(title):
    # Only use explicit "X樓" mentions as a conflict guard. Words such as 三房
    # are intentionally ignored.
    import re
    text = str(title or "")
    nums = set()
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for raw in re.findall(r"([一二三四五六七八九十]|\d{1,2})樓", text):
        if raw.isdigit():
            nums.add(int(raw))
        elif raw in cn:
            nums.add(cn[raw])
    return nums


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

    af = title_floor_tokens(at)
    bf = title_floor_tokens(bt)
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
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    pair_evidence = defaultdict(list)
    for i in range(n):
        for j in range(i + 1, n):
            ok, info = pair_591_info(m591[i], m591[j])
            if not ok:
                continue
            union(i, j)
            pair_evidence[i].append({"otherId": m591[j].get("id"), **info})
            pair_evidence[j].append({"otherId": m591[i].get("id"), **info})

    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    regrouped = []
    merged_cluster_count = 0
    absorbed = 0

    for indices in clusters.values():
        # Prefer the newest/current representative only for display. The raw ads
        # from every member are retained underneath it.
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

    # Multiple independent 591 ads with the same 591 fingerprint are stronger
    # evidence than one marketing title. If the regrouped 591 property and Sinyi
    # are almost identical in area and within 30萬 in asking price, allow the
    # cluster to merge under Sinyi even when titles are very different.
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
    matched_591 = set()

    for m in m591:
        cands = candidates_by_591.get(m.get("id")) or []
        if not cands:
            continue
        cands.sort(key=lambda z: z[0], reverse=True)

        # Do not guess when one 591 property group is equally compatible with
        # multiple Sinyi rows and there is no textual evidence separating them.
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
        matched_591.add(m.get("id"))
        attached[s.get("id")].append(m)
        attached_info[s.get("id")].append({
            "listing591Id": m.get("id"),
            "score": score,
            "preview591TopLevelCount": m.get("preview591TopLevelCount") or 1,
            "preview591TopLevelIds": m.get("preview591TopLevelIds") or [m.get("id")],
            **info,
        })

    groups = []
    for s in sinyi:
        groups.append(prev.make_group(s, attached.get(s.get("id"), []), attached_info.get(s.get("id"), [])))
    for m in m591:
        if m.get("id") not in matched_591:
            groups.append(prev.make_group(m))

    return groups, review_candidates


def main():
    # Monkey-patch only the grouping stage. v3 still handles the final company
    # comparison, Sinyi company priority, conflict protection, and output format.
    prev.build_groups = build_groups
    prev.main()

    path = prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company"
    payload["preview591Regroup"] = dict(REGROUP_STATS)
    payload["note"] = (
        "PREVIEW：先讓591重新互相比對並整併，再與信義房屋比對；同戶一律以信義為主資料、591保留在來源明細；"
        "最後才拿整併後的房屋群組比對永慶公開直營庫存。弱公司候選列未接回；真正公司候選衝突才列待確認。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"preview591Regroup": REGROUP_STATS}, ensure_ascii=False))


if __name__ == "__main__":
    main()
