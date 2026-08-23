"""Summarize isolated v9 replay against the last canonical v8 output."""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(os.environ.get("V8_BASELINE","/tmp/scheme-a-v8-baseline.json"))
BASE_WEAK=Path(os.environ.get("V8_WEAK_BASELINE","/tmp/scheme-a-v8-weak.json"))
NEW=Path("docs/preview/company-gap.json")
NEW_WEAK=Path("docs/preview/scheme-a-weak-group-audit.json")
FLOOR=Path("docs/preview/591-detail-floor-enrichment.json")
OUT=Path("docs/preview/scheme-a-v9-replay.json")


def raw_ids(g):
    out=[]
    for src in g.get("sourceListings") or []:
        members=src.get("mergedListings") or [src]
        for x in members:
            rid=str(x.get("id") or "")
            if rid: out.append(rid)
    return sorted(set(out))


def floors(g):
    out=set()
    for src in g.get("sourceListings") or []:
        members=src.get("mergedListings") or [src]
        for x in members:
            for key in ("structuredFloor","floor"):
                v=str(x.get(key) or "")
                import re
                m=re.match(r"(\d{1,2})\s*/\s*\d{1,2}\s*樓",v)
                if m: out.add(int(m.group(1)))
    return sorted(out)


def main():
    old=json.loads(BASE.read_text(encoding="utf-8"))
    new=json.loads(NEW.read_text(encoding="utf-8"))
    oldw=json.loads(BASE_WEAK.read_text(encoding="utf-8"))
    neww=json.loads(NEW_WEAK.read_text(encoding="utf-8")) if NEW_WEAK.exists() else {}
    fd=json.loads(FLOOR.read_text(encoding="utf-8"))

    old_groups={g.get("groupId"):g for g in old.get("propertyGroups") or []}
    new_groups={g.get("groupId"):g for g in new.get("propertyGroups") or []}
    new_cmp={x.get("groupId"):x for x in new.get("comparisons") or []}
    by_raw=defaultdict(set)
    for gid,g in new_groups.items():
        for rid in raw_ids(g): by_raw[rid].add(gid)

    medium=[x for x in oldw.get("groups") or [] if x.get("risk")=="medium"]
    rows=[]; split=0
    for m in medium:
        gid=m.get("groupId"); og=old_groups.get(gid) or {}
        ids=raw_ids(og)
        targets=sorted(set().union(*(by_raw.get(r,set()) for r in ids))) if ids else []
        was_split=len(targets)>1
        if was_split: split+=1
        rows.append({
            "oldGroupId":gid,"road":og.get("road") or m.get("road"),"title":og.get("title") or m.get("title"),
            "oldMemberCount":len(ids),"oldMemberIds":ids,"newGroupCount":len(targets),"splitByV9":was_split,
            "newGroups":[{
                "groupId":ngid,"title":(new_groups.get(ngid) or {}).get("title"),"memberCount":len(raw_ids(new_groups.get(ngid) or {})),
                "floors":floors(new_groups.get(ngid) or {}),"status":(new_cmp.get(ngid) or {}).get("status"),
                "candidateId":((new_cmp.get(ngid) or {}).get("companyCandidate") or {}).get("id"),
            } for ngid in targets],
        })

    new_medium=int(neww.get("mediumRiskCount") or 0)
    new_high=int(neww.get("highRiskCount") or 0)
    out={
        "generatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"previewOnly":True,"passed":False,
        "mode":new.get("mode"),"baselinePropertyGroupCount":old.get("propertyGroupCount"),"v9PropertyGroupCount":new.get("propertyGroupCount"),
        "baselineCounts":old.get("counts"),"v9Counts":new.get("counts"),
        "baselineMediumGroupCount":len(medium),"mediumGroupsSplitByExplicitV9Regroup":split,"mediumGroupsNotSplit":len(medium)-split,
        "v9WeakAudit":{"highRiskCount":new_high,"mediumRiskCount":new_medium,"riskCounts":neww.get("riskCounts")},
        "detailFloor":{"targetIdCount":fd.get("targetIdCount"),"success":fd.get("detailSuccessCount"),"withFloor":fd.get("withStructuredFloorCount"),"complete":fd.get("complete")},
        "companyNearTieGuard":new.get("companyNearTieGuard"),"companyCandidateReuseGuard":new.get("companyCandidateReuseGuard"),
        "preview591Regroup":new.get("preview591Regroup"),"rows":rows,
    }
    out["passed"]=bool(fd.get("complete") is True and new_high==0 and int((new.get("companyNearTieGuard") or {}).get("remainingAutoNearTieCount") or 0)==0)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("passed","baselinePropertyGroupCount","v9PropertyGroupCount","baselineCounts","v9Counts","baselineMediumGroupCount","mediumGroupsSplitByExplicitV9Regroup","v9WeakAudit","detailFloor")},ensure_ascii=False))

if __name__=="__main__": main()
