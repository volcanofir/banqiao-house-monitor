"""Deterministic regression tests for scheme A integrity-critical matching rules."""

import json

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v5 as v5
import compare_yungching_preview_v6 as v6
import compare_yungching_preview_v7 as v7
import compare_yungching_preview_v8 as v8

ROAD = "板橋區中山路二段"


def row(source, rid, title, floor=None):
    x = {
        "id": rid, "houseId": rid.split(":")[-1], "source": source, "road": ROAD,
        "title": title, "address": "新北市板橋區中山路二段",
        "price": "1000萬", "effectivePrice": 1000, "size": "30坪",
        "active": True, "url": f"https://example.invalid/{rid}",
    }
    if floor:
        x["floor"] = floor
    return x


def install_safe_floor_parser():
    v5.floors_from_text = v7.safe_floor_numbers
    v5.listing_floors = v6.structured_listing_floors
    v4.title_floor_tokens = v7.safe_floor_numbers
    v4.listing_floor_tokens = v8.safe_listing_floor_tokens_with_structured


def test_transitive_591_floor_bridge():
    install_safe_floor_parser()
    rows = [row("591", "591:A", "同社區二樓"), row("591", "591:B", "同社區美寓"), row("591", "591:C", "同社區三樓")]
    v4.pair_591_info = v5.pair_591_info
    groups = v4.regroup_591(rows)
    assert len(groups) == 2, [(g.get("id"), g.get("preview591ClusterFloors")) for g in groups]
    assert v4.REGROUP_STATS.get("clusterFloorConflictBlocked", 0) >= 1, v4.REGROUP_STATS
    for g in groups:
        floors = set(g.get("preview591ClusterFloors") or [])
        assert not ({2, 3} <= floors), g
    return {"groupCount": len(groups), "blocked": v4.REGROUP_STATS.get("clusterFloorConflictBlocked"), "clusterFloors": [g.get("preview591ClusterFloors") for g in groups]}


def test_sinyi_unknown_floor_multi_attach_guard():
    install_safe_floor_parser()
    external = [row("信義房屋", "信義房屋:S1", "同社區方正美寓"), row("591", "591:D", "同社區方正二樓"), row("591", "591:E", "同社區方正三樓")]
    v4.pair_591_info = v5.pair_591_info
    v4.cross_source_cluster_info = v5.cross_source_cluster_info
    groups, reviews = v4.build_groups(external)
    sinyi_group = next(g for g in groups if g.get("primaryId") == "信義房屋:S1")
    attached_591 = [x for x in (sinyi_group.get("sourceListings") or []) if x.get("source") == "591"]
    assert len(attached_591) == 1, sinyi_group
    assert any("樓層" in str(x.get("reason") or "") for x in reviews), reviews
    assert v4.GROUP_INTEGRITY_STATS.get("crossSourceMultiAttachFloorConflictBlocked", 0) >= 1, v4.GROUP_INTEGRITY_STATS
    return {"groupCount": len(groups), "sinyiAttached591": len(attached_591), "blocked": v4.GROUP_INTEGRITY_STATS.get("crossSourceMultiAttachFloorConflictBlocked"), "reviewCount": len(reviews)}


def test_structured_company_floor_wins():
    install_safe_floor_parser()
    company = {"id": "YC:TEST", "title": "測試三樓", "address": "新北市板橋區中山路二段", "text": "測試物件 建坪32.33 主32.333/3樓 3房2廳", "floor": "3/3樓"}
    parsed = v6.structured_listing_floors(company, company=True)
    assert parsed == {3}, parsed
    assert 33 not in parsed, parsed
    raw_helper = v7.safe_floor_numbers("主32.333/3樓")
    assert raw_helper == {3}, raw_helper
    range_helper = v7.safe_floor_numbers("主36.12 1~2/5樓")
    assert range_helper == {1, 2}, range_helper
    return {"structuredFloors": sorted(parsed), "gluedDomFloors": sorted(raw_helper), "rangeFloors": sorted(range_helper)}


def test_structured_sinyi_floor_blocks_wrong_591_floor():
    install_safe_floor_parser()
    v4.pair_591_info = v5.pair_591_info
    v4.cross_source_cluster_info = v5.cross_source_cluster_info
    sinyi = row("信義房屋", "信義房屋:S3", "同社區便利公寓", floor="3/5樓")
    listing591 = row("591", "591:F5", "同社區頂加五樓")
    groups, reviews = v4.build_groups([sinyi, listing591])
    sinyi_group = next(g for g in groups if g.get("primaryId") == "信義房屋:S3")
    attached_591 = [x for x in (sinyi_group.get("sourceListings") or []) if x.get("source") == "591"]
    assert v8.safe_listing_floor_tokens_with_structured(sinyi) == {3}, sinyi
    assert len(groups) == 2, groups
    assert not attached_591, sinyi_group
    return {"groupCount": len(groups), "sinyiFloor": [3], "wrongFloorAttached": len(attached_591), "reviewCount": len(reviews)}


def test_company_near_tie_guard_downgrades():
    original = v8.best_candidate_evidence
    try:
        def fake_evidence(group, candidate):
            score = 20 if candidate.get("id") == "YC:A" else 19
            return {
                "score": score,
                "info": {
                    "areaDelta": 0.0, "priceDelta": 0.0, "titleRatio": 0.5,
                    "shared": ["測試案"], "floorRelation": "match",
                    "externalFloors": [3], "companyFloors": [3],
                },
                "evidenceSource": "信義房屋", "evidenceListingId": "信義房屋:S3",
            }
        v8.best_candidate_evidence = fake_evidence
        payload = {
            "propertyGroups": [{"groupId": "GROUP:S3", "road": ROAD, "title": "測試案", "sourceListings": [row("信義房屋", "信義房屋:S3", "測試案", floor="3/5樓")]}],
            "companyListings": [
                {"id": "YC:A", "road": ROAD, "title": "測試案A", "floor": "3/5樓"},
                {"id": "YC:B", "road": ROAD, "title": "測試案B", "floor": "3/5樓"},
            ],
            "comparisons": [{"groupId": "GROUP:S3", "status": "company_match", "statusLabel": "庫存", "companyCandidate": {"id": "YC:A"}}],
        }
        v8.apply_company_near_tie_guard(payload)
        cmp = payload["comparisons"][0]
        assert cmp.get("status") == "review", cmp
        assert cmp.get("companyNearTieGuardReview") is True, cmp
        assert payload["companyNearTieGuard"].get("downgradedCount") == 1, payload["companyNearTieGuard"]
        assert payload["companyNearTieGuard"].get("remainingAutoNearTieCount") == 0, payload["companyNearTieGuard"]
        return {"status": cmp.get("status"), "downgraded": 1, "remainingAutoNearTie": 0}
    finally:
        v8.best_candidate_evidence = original


def main():
    result = {
        "transitive591FloorBridge": test_transitive_591_floor_bridge(),
        "sinyiUnknownFloorMultiAttach": test_sinyi_unknown_floor_multi_attach_guard(),
        "structuredCompanyFloor": test_structured_company_floor_wins(),
        "structuredSinyiFloorConflict": test_structured_sinyi_floor_blocks_wrong_591_floor(),
        "companyNearTieGuard": test_company_near_tie_guard_downgrades(),
        "passed": True,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
