"""Scheme A v3 release gate: v2 integrity + Sinyi floor coverage + near-tie safety."""

import json
from pathlib import Path

import validate_scheme_a_preview_v2 as v2

GAP = Path("docs/preview/company-gap.json")
SINYI_STATS = Path("docs/preview/sinyi-floor-enrichment.json")


def main():
    v2.main()
    p = json.loads(GAP.read_text(encoding="utf-8"))
    stats = json.loads(SINYI_STATS.read_text(encoding="utf-8"))

    assert p.get("mode") == "preview_only_591_then_sinyi_structured_floor_then_company_neartie_guard_v8", p.get("mode")
    assert p.get("sinyiStructuredFloorMatching") is True, p.get("sinyiStructuredFloorMatching")

    embedded = p.get("sinyiFloorEnrichment") or {}
    assert stats.get("complete") is True, stats
    assert embedded.get("complete") is True, embedded
    for key in ("activeSinyiCount", "matchedOfficialCount", "appliedCount"):
        assert int(stats.get(key) or 0) == int(embedded.get(key) or 0), (key, stats.get(key), embedded.get(key))
    active = int(stats.get("activeSinyiCount") or 0)
    matched = int(stats.get("matchedOfficialCount") or 0)
    applied = int(stats.get("appliedCount") or 0)
    assert active > 0, stats
    assert active == matched == applied, stats
    assert not (stats.get("missingActiveIds") or []), stats.get("missingActiveIds")
    assert all((x or {}).get("allHttp200") is True for x in (stats.get("roadStatus") or {}).values()), stats.get("roadStatus")

    guard = p.get("companyNearTieGuard") or {}
    assert guard.get("enabled") is True, guard
    assert int(guard.get("remainingAutoNearTieCount") or 0) == 0, guard

    review_guard_rows = 0
    for row in p.get("comparisons") or []:
        if row.get("companyNearTieStrong") is True:
            assert row.get("status") == "review", row
            assert row.get("companyNearTieGuardReview") is True, row
            candidates = row.get("companyNearTieCandidates") or []
            assert len(candidates) >= 2, row
            assert str(candidates[0].get("id")) != str(candidates[1].get("id")), row
            review_guard_rows += 1
        assert not (row.get("status") == "company_match" and row.get("companyNearTieStrong") is True), row

    assert review_guard_rows == int(guard.get("downgradedCount") or 0), (review_guard_rows, guard)

    print(json.dumps({
        "scheme": "A",
        "validator": "v3-sinyi-floor-neartie",
        "sinyiActive": active,
        "sinyiOfficialMatched": matched,
        "sinyiWithStructuredFloor": stats.get("withStructuredFloorValueCount"),
        "nearTieDowngraded": guard.get("downgradedCount"),
        "remainingAutoNearTie": guard.get("remainingAutoNearTieCount"),
        "valid": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
