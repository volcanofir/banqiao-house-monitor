"""Audit current Scheme A output for ambiguity that validators do not catch.

Checks only saved canonical Preview data. It does not mutate matching output.
Focus:
1) a company_match whose top two official company candidates are both strong/near-tied;
2) already-merged external records with exact area/price fingerprints but no floor or
   title corroboration, which may represent distinct same-layout units.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


GAP = Path("docs/preview/company-gap.json")
OUT = Path("docs/preview/scheme-a-ambiguity-audit.json")
STOPWORDS = {
    "板橋", "板橋區", "新北市", "永慶房屋", "公司", "專約", "專任", "推薦", "好宅", "美寓", "美屋", "美宅",
    "公寓", "華廈", "大樓", "住宅", "捷運", "邊間", "採光", "三房", "兩房", "四房", "一樓", "二樓",
    "三樓", "四樓", "五樓", "全新", "裝潢", "首購", "成家", "稀有", "景觀", "低總價", "近捷運", "出價可談",
}


def norm(v):
    t = str(v or "").replace("臺", "台")
    t = t.replace("中山路2段", "中山路二段").replace("三民路1段", "三民路一段").replace("三民路2段", "三民路二段")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", t).lower()


def num(v):
    m = re.search(r"\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else None


def area_of(x):
    return num(x.get("size") if x.get("size") is not None else x.get("area"))


def price_of(x):
    if x.get("effectivePrice") is not None:
        return num(x.get("effectivePrice"))
    return num(x.get("price"))


def tokens(text):
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", str(text or ""))
    out = set()
    for ch in chunks:
        if ch in STOPWORDS:
            continue
        if len(ch) >= 3:
            out.add(ch)
        for n in (3, 4, 5):
            if len(ch) >= n:
                out.update(ch[i:i+n] for i in range(len(ch)-n+1) if ch[i:i+n] not in STOPWORDS)
    return out


def floors(text):
    text = str(text or "").replace("～", "~")
    out = set()
    spans = []
    for m in re.finditer(r"(\d{1,2})(?:\s*[~-]\s*(\d{1,2}))?\s*/\s*(\d{1,2})\s*樓", text):
        lo = int(m.group(1)); hi = int(m.group(2) or m.group(1)); total = int(m.group(3))
        if 1 <= lo <= hi <= total <= 99 and hi - lo <= 10:
            out.update(range(lo, hi + 1))
        elif m.group(2) is None and len(m.group(1)) == 2:
            suffix = int(m.group(1)[-1])
            if 1 <= suffix <= total:
                out.add(suffix)
        spans.append(m.span())
    if spans:
        chars = list(text)
        for a, b in spans:
            for i in range(a, b): chars[i] = " "
        text = "".join(chars)
    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99: out.add(n)
    return out


def listing_floors(x, company=False):
    if not x:
        return set()
    # Current v7 company matching trusts the structured official floor when present.
    if company and x.get("floor") not in (None, ""):
        return floors(x.get("floor"))
    out = floors(x.get("title")) | floors(x.get("address"))
    for m in x.get("mergedListings") or []:
        out |= floors(m.get("title")) | floors(m.get("address"))
    return out


def score_pair(ext, yc):
    ea, ep = area_of(ext), price_of(ext)
    ya, yp = area_of(yc), price_of(yc)
    ad = abs(ea - ya) if ea is not None and ya is not None else None
    pd = abs(ep - yp) if ep is not None and yp is not None else None
    if ad is not None and ad > 1.0:
        return -99, {"areaDelta": round(ad, 2), "priceDelta": pd, "titleRatio": 0, "shared": [], "floorRelation": "n/a"}
    s = 0
    if ad is not None:
        s += 8 if ad <= .12 else 5 if ad <= .30 else 2 if ad <= .60 else 0
    if pd is not None:
        s += 6 if pd <= 1 else 4 if pd <= 30 else 2 if pd <= 80 else 1 if pd <= 150 else -3 if pd > 300 else 0
    et, yt = str(ext.get("title") or ""), str(yc.get("title") or "")
    shared = tokens(et) & tokens(yt)
    longest = max((len(x) for x in shared), default=0)
    if longest >= 5: s += 4
    elif longest >= 4: s += 3
    elif longest >= 3: s += 2
    tr = SequenceMatcher(None, norm(et), norm(yt)).ratio()
    if tr >= .55: s += 4
    elif tr >= .42: s += 3
    elif tr >= .30: s += 1

    ef = listing_floors(ext)
    cf = listing_floors(yc, company=True)
    relation = "unknown"
    if ef and cf:
        if ef & cf:
            relation = "match"; s += 8
        else:
            relation = "conflict"; s = -99
    info = {
        "areaDelta": None if ad is None else round(ad, 2),
        "priceDelta": None if pd is None else round(pd, 1),
        "titleRatio": round(tr, 3),
        "shared": sorted(shared, key=lambda x: (-len(x), x))[:6],
        "externalFloors": sorted(ef),
        "companyFloors": sorted(cf),
        "floorRelation": relation,
    }
    return s, info


def is_strong(score, info):
    ad = info.get("areaDelta"); pd = info.get("priceDelta"); tr = info.get("titleRatio") or 0
    longest = max((len(x) for x in info.get("shared") or []), default=0)
    return bool(
        info.get("floorRelation") != "conflict" and
        ad is not None and ad <= .30 and
        ((pd is not None and pd <= 30) or tr >= .42 or longest >= 4) and
        score >= 10
    )


def raw_members(group):
    rows = []
    for src in group.get("sourceListings") or []:
        merged = src.get("mergedListings") or []
        if merged:
            for m in merged:
                x = dict(m); x.setdefault("source", src.get("source")); x.setdefault("road", group.get("road")); rows.append(x)
        else:
            x = dict(src); x.setdefault("road", group.get("road")); rows.append(x)
    return rows


def weak_identity_pair(a, b):
    aa, ba = area_of(a), area_of(b); ap, bp = price_of(a), price_of(b)
    if None in (aa, ba, ap, bp): return None
    ad, pd = abs(aa-ba), abs(ap-bp)
    if ad > .05 or pd > 1: return None
    af, bf = listing_floors(a), listing_floors(b)
    if af and bf and not af.isdisjoint(bf): floor_rel = "match"
    elif af and bf: floor_rel = "conflict"
    else: floor_rel = "unknown"
    tr = SequenceMatcher(None, norm(a.get("title")), norm(b.get("title"))).ratio()
    shared = tokens(a.get("title")) & tokens(b.get("title"))
    longest = max((len(x) for x in shared), default=0)
    if floor_rel == "unknown" and tr < .18 and longest < 3:
        return {
            "aId": a.get("id") or a.get("houseId"), "aSource": a.get("source"), "aTitle": a.get("title"),
            "bId": b.get("id") or b.get("houseId"), "bSource": b.get("source"), "bTitle": b.get("title"),
            "areaDelta": round(ad,2), "priceDelta": round(pd,1), "titleRatio": round(tr,3),
            "floorRelation": floor_rel, "shared": sorted(shared)[:6],
        }
    return None


def main():
    gap = json.loads(GAP.read_text(encoding="utf-8"))
    groups = gap.get("propertyGroups") or []
    company = gap.get("companyListings") or []
    comparisons = {x.get("groupId"): x for x in (gap.get("comparisons") or [])}
    company_by_road = defaultdict(list)
    for yc in company: company_by_road[yc.get("road")].append(yc)

    company_ambiguous = []
    chosen_not_unique_top = []
    for group in groups:
        cmp = comparisons.get(group.get("groupId")) or {}
        if cmp.get("status") != "company_match":
            continue
        ranked = []
        for yc in company_by_road.get(group.get("road"), []):
            best = None
            for member in group.get("sourceListings") or []:
                sc, info = score_pair(member, yc)
                pri = 1 if member.get("source") == "信義房屋" else 0
                cand = (sc, pri, info, member)
                if best is None or (cand[0], cand[1]) > (best[0], best[1]): best = cand
            if best:
                ranked.append((best[0], best[1], yc, best[2], best[3]))
        ranked.sort(key=lambda z:(z[0], z[1]), reverse=True)
        strong = [r for r in ranked if is_strong(r[0], r[3])]
        chosen_id = str((cmp.get("companyCandidate") or {}).get("id") or "")
        if ranked and str(ranked[0][2].get("id") or "") != chosen_id:
            chosen_not_unique_top.append({
                "groupId": group.get("groupId"), "chosenId": chosen_id,
                "recomputedTopId": ranked[0][2].get("id"), "topScore": ranked[0][0],
            })
        if len(strong) >= 2:
            first, second = strong[0], strong[1]
            if first[0] - second[0] <= 2:
                company_ambiguous.append({
                    "groupId": group.get("groupId"), "road": group.get("road"), "title": group.get("title"),
                    "chosenId": chosen_id,
                    "top": {"id": first[2].get("id"), "officialId": first[2].get("officialId"), "title": first[2].get("title"), "score": first[0], "info": first[3]},
                    "second": {"id": second[2].get("id"), "officialId": second[2].get("officialId"), "title": second[2].get("title"), "score": second[0], "info": second[3]},
                    "risk": "同一外部群組有兩筆不同永慶公司案件同時達 strong 且分差<=2；目前邏輯會直接取第一名",
                })

    weak_merged = []
    for group in groups:
        members = raw_members(group)
        for i in range(len(members)):
            for j in range(i+1, len(members)):
                # Only inspect records that were actually collapsed into the same final group.
                risk = weak_identity_pair(members[i], members[j])
                if risk:
                    weak_merged.append({"groupId": group.get("groupId"), "road": group.get("road"), **risk})

    # Avoid counting the same unordered raw pair twice if duplicated by compact data.
    uniq = {}
    for x in weak_merged:
        key = (x.get("groupId"),) + tuple(sorted([str(x.get("aId")), str(x.get("bId"))]))
        uniq[key] = x
    weak_merged = list(uniq.values())

    out = {
        "auditedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scheme": "A",
        "sourceGeneratedAt": gap.get("generatedAt"),
        "propertyGroupCount": len(groups),
        "companyListingCount": len(company),
        "companyMatchCount": sum(1 for x in comparisons.values() if x.get("status") == "company_match"),
        "companyNearTieStrongCount": len(company_ambiguous),
        "companyNearTieStrong": company_ambiguous,
        "chosenCandidateRecomputeMismatchCount": len(chosen_not_unique_top),
        "chosenCandidateRecomputeMismatch": chosen_not_unique_top,
        "weakIdentityAlreadyMergedPairCount": len(weak_merged),
        "weakIdentityAlreadyMergedPairs": weak_merged[:150],
        "rules": {
            "companyNearTie": "two distinct company candidates both satisfy current strong threshold and score gap <= 2",
            "weakIdentityMerge": "records already in same group have area <=0.05 ping, price <=1 wan, floor unknown, title ratio <0.18, no >=3-char shared token",
        },
        "passedConservative": not company_ambiguous and not weak_merged and not chosen_not_unique_top,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "propertyGroupCount", "companyMatchCount", "companyNearTieStrongCount",
        "chosenCandidateRecomputeMismatchCount", "weakIdentityAlreadyMergedPairCount", "passedConservative"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
