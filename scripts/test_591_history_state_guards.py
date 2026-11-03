"""Regression guards for 591 property-group vs source-listing identity.

Uses only synthetic fixtures and previously committed local JSON. Does not
touch live network, production state, preview, or credentials.
"""
import copy
import json
import subprocess

import dedupe_listings_v2 as dedupe
import monitor_pages as core

HISTORY_SHA = "8b793ca7b2fea34eac0683256b522b645456843c"


def fixture():
    parent = {
        "id": "591:10000001",
        "source": "591",
        "houseId": "10000001",
        "road": "板橋區光復街",
        "title": "同一間房屋",
        "address": "板橋區光復街20號",
        "price": "1200萬",
        "size": "25坪",
        "postTime": 1760000000,
        "active": True,  # Property group remains active.
        "firstSeenAt": "2026-10-01T00:00:00+00:00",
        "mergedListings": [
            {
                "id": "591:10000001",
                "source": "591",
                "houseId": "10000001",
                "road": "板橋區光復街",
                "title": "同一間房屋",
                "address": "板橋區光復街20號",
                "price": "1200萬",
                "size": "25坪",
                "postTime": 1760000000,
                "active": False,  # This particular advertisement was delisted.
                "removedAt": "2026-10-30T00:00:00+00:00",
                "firstSeenAt": "2026-10-01T00:00:00+00:00",
            },
            {
                "id": "591:10000002",
                "source": "591",
                "houseId": "10000002",
                "road": "板橋區光復街",
                "title": "同一間房屋",
                "address": "板橋區光復街20號",
                "price": "1200萬",
                "size": "25坪",
                "postTime": 1760000010,
                "active": True,
                "firstSeenAt": "2026-10-02T00:00:00+00:00",
            },
        ],
    }
    parent["mergedListingIds"] = [x["id"] for x in parent["mergedListings"]]
    return parent


def test_group_and_member_status():
    parent = fixture()
    flattened = {x["id"]:x for x in dedupe.flatten_591([parent])}
    assert len(flattened) == 2
    assert flattened["591:10000001"]["active"] is False, (
        "Grouping must not re-activate a delisted source listing."
    )
    assert flattened["591:10000001"]["removedAt"] is not None
    assert flattened["591:10000002"]["active"] is True
    grouped, removed, raw = dedupe.dedupe([parent])
    assert raw == 2 and len(grouped) == 1 and removed == 1
    assert grouped[0]["active"] is True, "Property remains active while any member is listed"
    group_items={x["id"]:x for x in grouped[0]["mergedListings"]}
    assert group_items["591:10000001"]["active"] is False
    assert group_items["591:10000002"]["active"] is True
    print("SYNTHETIC status_guard=pass grouped_active=True parent_member_inactive_preserved=True")


def test_nested_previous_ids_not_new():
    parent = fixture()
    previous = {
        "listings": [parent],
        "runs": {"591":{"mode":"playwright_api","status":"error"}},
    }
    incoming = {
        "id": "591:10000002",
        "source": "591",
        "houseId": "10000002",
        "road": "板橋區光復街",
        "title": "同一間房屋",
        "address": "板橋區光復街20號",
        "price": "1200萬",
        "size": "25坪",
        "postTime": 1760000010,
    }
    # This is a pure comparison test; do not fetch detail pages to assess delistings.
    original = core.definitely_inactive
    core.definitely_inactive = lambda item: False
    try:
        state = copy.deepcopy(previous)
        new_ids, removed_ids = core.merge_source(
            state, "591", [incoming], True, "synthetic test", [],
            "2026-11-03T00:00:00+00:00"
        )
        assert new_ids == [], "An existing nested member cannot be reported as a new listing"
        assert removed_ids == [], "Missing parent IDs must not imply confirmed delistings"
        matched = [x for x in state["listings"] if x["id"] == incoming["id"]]
        assert len(matched) == 1
        assert matched[0]["firstSeenAt"] == "2026-10-02T00:00:00+00:00"
        print("SYNTHETIC previous_nested_member_new_count=0 first_seen_preserved=True")

        new = dict(incoming, id="591:10000003", houseId="10000003")
        state = copy.deepcopy(previous)
        new_ids, _ = core.merge_source(
            state, "591", [new], True, "synthetic test", [],
            "2026-11-03T00:00:00+00:00"
        )
        assert new_ids == ["591:10000003"], "A truly unknown source ID should still be new"
        print("SYNTHETIC genuinely_unknown_member_new_count=1")
    finally:
        core.definitely_inactive = original


def test_2026_10_30_archive():
    raw = subprocess.check_output(
        ["git","show",HISTORY_SHA+":docs/data/listings.json"],
        encoding="utf-8"
    )
    state = json.loads(raw)
    parents = [x for x in state["listings"] if x.get("source")=="591"]
    flattened = dedupe.flatten_591(parents)
    ids = {x["id"] for x in flattened}
    active = sum(x.get("active",True) for x in flattened)
    inconsistent=0
    for parent in parents:
        if not isinstance(parent.get("mergedListings"),list):
            continue
        match=next((m for m in parent["mergedListings"] if m.get("id")==parent.get("id")),None)
        if match and parent.get("active")!=match.get("active"):
            inconsistent+=1
            assert {x["id"]:x for x in flattened}[parent["id"]]["active"]==match["active"]
    assert len(flattened)==len(ids)==513, (len(flattened),len(ids))
    assert inconsistent == 38, inconsistent
    assert active==442, f"Expected 442 active *ad IDs* from archived snapshot, got {active}"
    grouped,_,_=dedupe.dedupe(parents)
    grouped_active=sum(x.get("active",True) for x in grouped if x.get("source")=="591")
    assert grouped_active>=110, "Property groups should remain available"
    print(
        f"ARCHIVE_2026_10_30 source_ids={len(ids)} historical_active_ad_ids={active} "
        f"representative_status_mismatch={inconsistent} "
        f"grouped_active_properties={grouped_active} status_guard=pass"
    )


def main():
    test_group_and_member_status()
    test_nested_previous_ids_not_new()
    test_2026_10_30_archive()
    print("REGRESSION_TESTS_ALL_PASS no production data updated")


if __name__ == "__main__":
    main()
