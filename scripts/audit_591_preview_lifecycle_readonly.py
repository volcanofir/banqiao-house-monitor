"""Read-only, reproducible audit of the ORIGINAL /preview/ sale listings.

This script never scrapes websites and never writes canonical/preview files.
It differentiates observed listing IDs, reposts, property-level candidates,
confirmed source removals, unknown absence, and *displayed* same-home groups.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dedupe_listings_v2 import flatten_591, number

ROOT = Path("docs")
SNAP = ROOT / "591-preview/snapshot.json"
HISTORY = ROOT / "data/listings.json"
STATE = ROOT / "preview/preview-monitor-state.json"
GAP = ROOT / "preview/company-gap.json"
AUDIT = ROOT / "preview/scheme-a-ambiguity-audit.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def all_members(parent):
    rows = parent.get("mergedListings") or []
    return rows if rows else [parent]


def source_members(group):
    ret = []
    for src in group.get("sourceListings") or []:
        ret.extend(all_members(src))
    return ret


def stamp(v):
    if not v:
        return None
    try:
        z = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return z if z.tzinfo else z.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def group_ids(group):
    return set(str(m.get("id")) for m in source_members(group) if m.get("id"))


def main():
    snapshot, history, state, gap, audit = map(
        load, (SNAP, HISTORY, STATE, GAP, AUDIT)
    )
    observed = {str(x["id"]): x for x in snapshot["listings"]}
    assert snapshot.get("complete") is True
    assert len(snapshot["roadCounts"]) == 7
    assert len(observed) == len(snapshot["listings"])
    old = {
        str(x["id"]): x for x in
        flatten_591([x for x in history["listings"] if x.get("source") == "591"])
    }
    current_groups = [x for x in state["listings"] if x.get("source") == "591"]
    current = {
        str(x["id"]): x for x in flatten_591(current_groups)
    }
    actual_seen = {rid for rid, row in current.items() if row.get("active") is not False}
    assert actual_seen == set(observed), {
        "missing_observed": sorted(set(observed) - actual_seen)[:20],
        "false_active": sorted(actual_seen - set(observed))[:20],
    }
    assert set(current) == set(old) | set(observed)
    for rid, previous in old.items():
        after = current[rid]
        assert after.get("firstSeenAt") == previous.get("firstSeenAt"), rid
        if rid not in observed:
            assert after.get("active") is False, rid
            if previous.get("active") is False:
                assert after.get("removedAt") == previous.get("removedAt"), rid
            else:
                assert after.get("removedAt") is None, rid

    novel_id_groups = []
    repost_groups = []
    for group in current_groups:
        if not group.get("active"):
            continue
        observed_in_group = [
            str(m["id"]) for m in all_members(group)
            if str(m.get("id")) in observed
        ]
        new_ids = [x for x in observed_in_group if x not in old]
        if not new_ids:
            continue
        old_ids = [str(m["id"]) for m in all_members(group)
                   if str(m.get("id")) in old]
        entry = {"groupId": group.get("id"), "title": group.get("title"),
                 "newIdCount": len(new_ids), "existingIdCount": len(old_ids)}
        (repost_groups if old_ids else novel_id_groups).append(entry)

    complete_groups = gap.get("propertyGroups") or []
    offmarket = gap.get("recentOffMarketGroups") or []
    group_lookup = {}
    for g in complete_groups:
        for rid in group_ids(g):
            group_lookup[rid] = g.get("groupId")
    expected = set(observed)
    offmarket_current = []
    offmarket_unconfirmed = []
    offmarket_other_active = []
    offmarket_totals = Counter()
    for group in offmarket:
        members = source_members(group)
        bad_current = [str(m.get("id")) for m in members
                       if str(m.get("id")) in expected]
        unconfirmed = [str(m.get("id")) for m in members
                       if m.get("active") is False and not m.get("removedAt")]
        other_active = [str(m.get("id")) for m in members
                        if m.get("active") is not False]
        offmarket_totals.update(m.get("source") for m in members if m.get("source"))
        if bad_current:
            offmarket_current.append({"groupId": group.get("groupId"), "ids": bad_current})
        if unconfirmed:
            offmarket_unconfirmed.append({
                "groupId": group.get("groupId"), "ids": unconfirmed[:12],
                "title": group.get("title")})
        if other_active:
            offmarket_other_active.append({
                "groupId": group.get("groupId"), "ids": other_active[:12],
                "title": group.get("title")})

    active_591 = [g for g in current_groups if g.get("active") is True]
    same_fingerprint_unmerged = []
    for i, a in enumerate(active_591):
        for b in active_591[i+1:]:
            if a.get("road") != b.get("road"):
                continue
            pa, pb = number(a.get("price")), number(b.get("price"))
            aa, ab = number(a.get("size")), number(b.get("size"))
            if None in (pa, pb, aa, ab) or abs(pa-pb)>1 or abs(aa-ab)>.05:
                continue
            ga, gb = group_lookup.get(str(a.get("id"))), group_lookup.get(str(b.get("id")))
            if ga != gb:  # Different in the actual displayed cross-source grouping.
                same_fingerprint_unmerged.append({
                    "aId": a.get("id"), "aTitle": a.get("title"),
                    "bId": b.get("id"), "bTitle": b.get("title"),
                    "road": a.get("road"), "price": a.get("price"),
                    "size": a.get("size"), "displayGroupA": ga, "displayGroupB": gb,
                })

    weak_pairs = audit.get("weakIdentityAlreadyMergedPairs") or []
    risky_display_groups = len({x["groupId"] for x in weak_pairs})
    info = {
        "canonicalHistoryUnchanged": True,
        "snapshotUpdatedAt": snapshot.get("updatedAt"),
        "previewVerifiedAt": gap.get("generatedAt"),
        "observed591Ids": len(observed),
        "historical591Ids": len(old),
        "new591Ids": len(set(observed) - set(old)),
        "oldIdsAbsentWithoutConfirmedRemoval": sum(
            1 for rid in set(old) - set(observed)
            if old[rid].get("removedAt") is None
        ),
        "newIdOnlyCandidateGroups": len(novel_id_groups),
        "repostIntoOldPropertyGroups": len(repost_groups),
        "newIdOnlyCandidateDetails": novel_id_groups,
        "previewActive591Groups": len(active_591),
        "displayedPropertyGroups": len(complete_groups),
        "displayedRecentlyRemovedGroups": len(offmarket),
        "offmarketContainsPresent591": offmarket_current,
        "offmarketContainsUnconfirmedAbsence": offmarket_unconfirmed,
        "offmarketContainsMarkedActiveMembers": offmarket_other_active,
        "offmarketSourceMemberCounts": offmarket_totals,
        "samePriceSizeUnmergedDisplayedPairs": same_fingerprint_unmerged,
        "weakEvidencePairsInDisplayAudit": audit.get("weakIdentityAlreadyMergedPairCount"),
        "weakEvidenceGroupsInStoredSample": risky_display_groups,
        "weakEvidenceSampleSize": len(weak_pairs),
        "companyStrongNearTieCount": audit.get("companyNearTieStrongCount"),
        "companyRecomputeMismatchCount": audit.get("chosenCandidateRecomputeMismatchCount"),
    }
    print("LIFECYCLE_AUDIT " + json.dumps(info, ensure_ascii=False, default=dict))
    assert not offmarket_current, "Current 591 ad must not be marked offmarket"
    assert not offmarket_other_active, "Active source member in offmarket group"


if __name__ == "__main__":
    main()
