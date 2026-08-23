"""Summarize weak-identity pair noise into actual suspicious scheme A groups.

Diagnostic only. Run after v8 comparison. It does not mutate company-gap.json.
The earlier pair-level audit can report hundreds of pair combinations inside one
heavily duplicated property, so this produces group-level risk signals instead.
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

GAP = Path("docs/preview/company-gap.json")
OUT = Path("docs/preview/scheme-a-weak-group-audit.json")


def num(v):
    m = re.search(r"\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else None


def norm(v):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(v or "").replace("臺", "台")).lower()


def floor_set(row):
    raw = str(row.get("floor") or "").replace("～", "~")
    out = set()
    for m in re.finditer(r"(\d{1,2})(?:\s*[~-]\s*(\d{1,2}))?\s*/\s*(\d{1,2})\s*樓", raw):
        lo, hi, total = int(m.group(1)), int(m.group(2) or m.group(1)), int(m.group(3))
        if 1 <= lo <= hi <= total <= 99 and hi-lo <= 10:
            out.update(range(lo, hi+1))
    if not out:
        for raw_n in re.findall(r"(?<!\d)(\d{1,2})\s*樓", str(row.get("title") or "")):
            n=int(raw_n)
            if 1 <= n <= 99: out.add(n)
    return out


def flatten(group):
    rows=[]
    seen=set()
    for src in group.get("sourceListings") or []:
        merged=src.get("mergedListings") or []
        candidates=merged if merged else [src]
        for item in candidates:
            x=dict(item)
            x.setdefault("source", src.get("source"))
            x.setdefault("floor", src.get("floor"))
            rid=str(x.get("id") or x.get("houseId") or x.get("url") or "")
            if not rid or rid in seen: continue
            seen.add(rid); rows.append(x)
    return rows


def pair_info(a,b):
    aa=num(a.get("size") if a.get("size") is not None else a.get("area"))
    ba=num(b.get("size") if b.get("size") is not None else b.get("area"))
    ap=num(a.get("effectivePrice") if a.get("effectivePrice") is not None else a.get("price"))
    bp=num(b.get("effectivePrice") if b.get("effectivePrice") is not None else b.get("price"))
    if None in (aa,ba,ap,bp): return None
    ad=abs(aa-ba); pd=abs(ap-bp)
    if ad>.05 or pd>1: return None
    af,bf=floor_set(a),floor_set(b)
    relation="unknown"
    if af and bf: relation="match" if af & bf else "conflict"
    ratio=SequenceMatcher(None,norm(a.get("title")),norm(b.get("title"))).ratio()
    return {"areaDelta":round(ad,2),"priceDelta":round(pd,1),"floorRelation":relation,"titleRatio":round(ratio,3)}


def main():
    p=json.loads(GAP.read_text(encoding="utf-8"))
    suspicious=[]
    exact_groups=0
    for g in p.get("propertyGroups") or []:
        rows=flatten(g)
        weak=[]; conflicts=[]; exact_pairs=0
        for i in range(len(rows)):
            for j in range(i+1,len(rows)):
                info=pair_info(rows[i],rows[j])
                if not info: continue
                exact_pairs+=1
                rec={
                    "aId":rows[i].get("id"),"aSource":rows[i].get("source"),"aTitle":rows[i].get("title"),"aFloors":sorted(floor_set(rows[i])),
                    "bId":rows[j].get("id"),"bSource":rows[j].get("source"),"bTitle":rows[j].get("title"),"bFloors":sorted(floor_set(rows[j])),
                    **info,
                }
                if info["floorRelation"]=="conflict": conflicts.append(rec)
                elif info["floorRelation"]=="unknown" and info["titleRatio"]<.18: weak.append(rec)
        if exact_pairs: exact_groups+=1
        if not weak and not conflicts: continue

        raw_floor_sets=sorted({tuple(sorted(floor_set(x))) for x in rows if floor_set(x)})
        sinyi=next((x for x in g.get("sourceListings") or [] if x.get("source")=="信義房屋"),None)
        sinyi_floors=sorted(floor_set(sinyi or {}))
        # Explicit conflicting floors inside one group are always high risk.
        # Unknown-floor low-title pairs are medium risk only when no structured
        # Sinyi floor anchors the group and there are multiple raw records.
        risk="high" if conflicts else "medium" if weak and not sinyi_floors else "anchored"
        suspicious.append({
            "groupId":g.get("groupId"),"road":g.get("road"),"title":g.get("title"),"primarySource":g.get("primarySource"),
            "rawMemberCount":len(rows),"exactFingerprintPairCount":exact_pairs,
            "weakUnknownPairCount":len(weak),"explicitFloorConflictPairCount":len(conflicts),
            "sinyiStructuredFloors":sinyi_floors,"observedFloorSets":[list(x) for x in raw_floor_sets],
            "risk":risk,"weakExamples":weak[:5],"conflictExamples":conflicts[:5],
        })

    risk_counts=Counter(x["risk"] for x in suspicious)
    suspicious.sort(key=lambda x: ({"high":0,"medium":1,"anchored":2}.get(x["risk"],9),-x["explicitFloorConflictPairCount"],-x["weakUnknownPairCount"]))
    out={
        "auditedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly":True,"mode":p.get("mode"),"propertyGroupCount":p.get("propertyGroupCount"),
        "groupsWithAnyExactFingerprintPair":exact_groups,
        "groupsFlagged":len(suspicious),"riskCounts":dict(risk_counts),
        "highRiskCount":risk_counts.get("high",0),"mediumRiskCount":risk_counts.get("medium",0),
        "groups":suspicious,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("propertyGroupCount","groupsWithAnyExactFingerprintPair","groupsFlagged","riskCounts","highRiskCount","mediumRiskCount")},ensure_ascii=False))

if __name__=="__main__": main()
