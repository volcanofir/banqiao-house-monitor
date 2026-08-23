"""Scheme A v4 release gate for Preview v9 structured 591 detail floors."""

import json
from pathlib import Path

import validate_scheme_a_preview_v2 as v2

GAP=Path("docs/preview/company-gap.json")
SINYI=Path("docs/preview/sinyi-floor-enrichment.json")
F591=Path("docs/preview/591-detail-floor-enrichment.json")


def main():
    v2.main()
    p=json.loads(GAP.read_text(encoding="utf-8"))
    s=json.loads(SINYI.read_text(encoding="utf-8"))
    f=json.loads(F591.read_text(encoding="utf-8"))

    assert p.get("mode")=="preview_only_raw591_detail_floor_regroup_then_sinyi_then_company_v9", p.get("mode")
    assert p.get("sinyiStructuredFloorMatching") is True
    assert p.get("structured591DetailFloorMatching") is True
    assert s.get("complete") is True, s
    assert int(s.get("activeSinyiCount") or 0)==int(s.get("matchedOfficialCount") or -1)==int(s.get("appliedCount") or -2), s
    assert not (s.get("missingActiveIds") or []), s.get("missingActiveIds")

    assert f.get("complete") is True, f
    assert int(f.get("targetIdCount") or 0)>0, f
    assert int(f.get("detailSuccessCount") or 0)==int(f.get("targetIdCount") or -1), f
    assert int(f.get("detailErrorCount") or 0)==0, f
    assert int(f.get("withStructuredFloorCount") or 0)>0, f
    embedded=p.get("listing591DetailFloorEnrichment") or {}
    assert embedded.get("complete") is True, embedded
    assert int(embedded.get("detailSuccessCount") or 0)==int(f.get("detailSuccessCount") or -1), (embedded,f)

    guard=p.get("companyNearTieGuard") or {}
    assert guard.get("enabled") is True, guard
    assert int(guard.get("remainingAutoNearTieCount") or 0)==0, guard
    for row in p.get("comparisons") or []:
        assert not (row.get("status")=="company_match" and row.get("companyNearTieStrong") is True), row

    integrity=p.get("schemeAGroupIntegrity") or {}
    regroup=p.get("preview591Regroup") or {}
    assert int(regroup.get("original591TopLevel") or 0)>0, regroup
    assert int(regroup.get("regrouped591TopLevel") or 0)>0, regroup

    print(json.dumps({
        "scheme":"A","validator":"v4-591-detail-floor-v9","valid":True,
        "propertyGroupCount":p.get("propertyGroupCount"),"counts":p.get("counts"),
        "sinyiMatched":s.get("matchedOfficialCount"),"detail591Target":f.get("targetIdCount"),
        "detail591Success":f.get("detailSuccessCount"),"detail591WithFloor":f.get("withStructuredFloorCount"),
        "clusterFloorConflictBlocked":regroup.get("clusterFloorConflictBlocked"),
        "crossSourceFloorConflictBlocked":integrity.get("crossSourceMultiAttachFloorConflictBlocked"),
        "remainingAutoNearTie":guard.get("remainingAutoNearTieCount"),
    },ensure_ascii=False))

if __name__=="__main__": main()
