"""Regression checks for the non-publishing 591 source merge guard."""
import copy
import json
from pathlib import Path

from preserve_591_on_failed_refresh import reconcile


def fixture():
    latest={
        "runs":{"591":{"status":"error","checkedAt":"2026-11-03T01:39:00Z"}},
        "listings":[
            {"id":"591:1","source":"591","active":True,"postTime":2,
             "mergedListings":[
                 {"id":"591:1","active":False,"removedAt":"2026-10-30"},
                 {"id":"591:2","active":True}
             ]},
            {"id":"S1","source":"信義房屋","active":True,"price":"1200萬","postTime":5}
        ],
        "updatedAt":"yesterday"
    }
    incoming=copy.deepcopy(latest)
    incoming["runs"]["591"]["status"]="error"
    incoming["listings"][0]["mergedListings"][0]["active"]=True # stale worker artifact
    incoming["listings"][1]["price"]="1100萬" # fresh non-591 data
    incoming["updatedAt"]="today"
    return incoming,latest


def test_failed_591_preserves_latest():
    incoming,latest=fixture()
    result,decision=reconcile(incoming,latest)
    assert decision=="latest_canonical_591_preserved"
    kept=next(x for x in result["listings"] if x["source"]=="591")
    assert kept==latest["listings"][0]
    s=next(x for x in result["listings"] if x["source"]=="信義房屋")
    assert s["price"]=="1100萬"
    assert result["updatedAt"]=="today"
    assert result["runs"]["591"]==latest["runs"]["591"]
    print("FAILURE_GUARD stale_591_overwrite_blocked=True fresh_non591_preserved=True")


def test_success_591_still_usable():
    incoming,latest=fixture()
    incoming["runs"]["591"]["status"]="ok"
    incoming["listings"][0]["mergedListings"][0]["active"]=True
    result,decision=reconcile(incoming,latest)
    assert decision=="candidate_591_success_retained"
    assert result is incoming
    print("SUCCESS_GUARD valid_591_candidate_retained=True")


def test_real_state_no_mutation():
    state=json.loads(Path("docs/data/listings.json").read_text(encoding="utf-8"))
    latest=copy.deepcopy(state)
    incoming=copy.deepcopy(state)
    incoming.setdefault("runs",{}).setdefault("591",{})["status"]="error"
    first=next(x for x in incoming["listings"] if x.get("source")=="591" and x.get("mergedListings"))
    first["mergedListings"][0]["active"]=not first["mergedListings"][0].get("active",True)
    result,decision=reconcile(incoming,latest)
    assert decision=="latest_canonical_591_preserved"
    current_591=[x for x in state["listings"] if x.get("source")=="591"]
    merged_591=[x for x in result["listings"] if x.get("source")=="591"]
    assert current_591==merged_591
    print(f"REAL_DATA_GUARD preserved_591_properties={len(current_591)}")
    print("ALL_PUBLISH_GUARD_TESTS_PASS no data written")


if __name__=="__main__":
    test_failed_591_preserves_latest()
    test_success_591_still_usable()
    test_real_state_no_mutation()
