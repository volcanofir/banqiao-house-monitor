"""Attach a 10-day, property-grouped off-market history to canonical Scheme A output.

The active company comparison remains untouched. We regroup active + recently removed
591/Sinyi records with the same Scheme A grouping rules, then keep only groups that
have no active source/member left. A property is therefore not counted as off-market
when one source disappeared but the same property is still advertised elsewhere.
"""

# Also acts as a canonical Preview rebuild trigger when display-only UI wording changes.

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v7 as v7
import compare_yungching_preview_v8 as v8
import compare_yungching_preview_v11 as v11

SOURCE = Path("docs/preview/scheme-a-external-enriched.json")
GAP = Path("docs/preview/company-gap.json")
RETENTION_DAYS = 10


def parse_dt(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def id_status_map(rows):
    out = {}

    def ingest(x):
        rid = x.get("id") or x.get("houseId") or x.get("url")
        if rid:
            out[str(rid)] = {
                "active": bool(x.get("active", True)),
                "removedAt": x.get("removedAt"),
            }
        for m in x.get("mergedListings") or []:
            ingest(m)

    for row in rows:
        ingest(row)
    return out


def group_member_ids(group):
    ids = []
    for m in group.get("sourceListings") or []:
        rid = m.get("id") or m.get("houseId") or m.get("url")
        if rid:
            ids.append(str(rid))
        for n in m.get("mergedListings") or []:
            nid = n.get("id") or n.get("houseId") or n.get("url")
            if nid:
                ids.append(str(nid))
    return list(dict.fromkeys(ids))


def removal_certainty(states, cutoff):
    """A group cannot be '已下架' if any represented listing lacks evidence.

    Unobserved listings from 591 wareList are *unknown*, not confirmed removed.
    A previous confirmed removal for one ad cannot establish removal of every
    ad belonging to the same property.
    """
    if not states or any(x.get("active") for x in states):
        return "active_or_unknown", None
    verified_times = [parse_dt(x.get("removedAt")) for x in states]
    known_times = [x for x in verified_times if x is not None]
    if not known_times:
        return "unknown", None
    recent = max(known_times)
    if recent <= cutoff:
        return "outside_window", recent
    if len(known_times) != len(states):
        return "unconfirmed", recent
    return "confirmed", recent


def build_offmarket_report(state, payload, now):
    cutoff = now - timedelta(days=RETENTION_DAYS)
    # Use all four sale sources. Previously 5168 was ignored, which could
    # incorrectly declare a property removed while 5168 still advertised it.
    all_external = [
        x for x in state.get("listings", [])
        if x.get("source") in {"591", "信義房屋", "樂屋網", "5168"}
    ]

    # Include missing 591 IDs without a removedAt in the candidate grouping:
    # omitting them would incorrectly turn partly unknown houses into confirmed
    # offmarket houses. They are neither active nor verified removed.
    v4.title_floor_tokens = v7.safe_floor_numbers
    v4.listing_floor_tokens = v8.safe_listing_floor_tokens_with_structured
    v4.prev.compact_listing = v8.compact_listing_with_structured_floor
    groups, _ = v11.build_groups_with_aux_sources(all_external)
    status = id_status_map(all_external)
    offmarket = []
    pending = []

    for group in groups:
        member_ids = group_member_ids(group)
        # Don't silently drop any member lacking source-status information.
        if not member_ids or any(key not in status for key in member_ids):
            continue
        states = [status[key] for key in member_ids]
        decision, removal_at = removal_certainty(states, cutoff)
        if decision not in ("confirmed", "unconfirmed"):
            continue
        row = dict(group)
        row["active"] = False
        row["removedAt"] = removal_at.isoformat(timespec="seconds")
        row["offMarketRetentionDays"] = RETENTION_DAYS
        if decision == "unconfirmed":
            row["offMarket"] = False
            row["offMarketPendingConfirmation"] = True
            row["pendingReason"] = (
                "同屋仍有來源刊登缺乏確認下架時間，不能標示已下架"
            )
            pending.append(row)
        else:
            row["offMarket"] = True
            row["offMarketPendingConfirmation"] = False
            offmarket.append(row)

    offmarket.sort(key=lambda x: x.get("removedAt") or "", reverse=True)
    pending.sort(key=lambda x: x.get("removedAt") or "", reverse=True)
    payload["recentOffMarketRetentionDays"] = RETENTION_DAYS
    payload["recentOffMarketGeneratedAt"] = now.isoformat(timespec="seconds")
    payload["recentOffMarketCount"] = len(offmarket)
    payload["recentOffMarketGroups"] = offmarket
    # Diagnostics only. These are NOT confirmed off-market properties and must
    # never contribute to the UI's '已下架' count or cards.
    payload["pendingOffMarketConfirmationCount"] = len(pending)
    payload["pendingOffMarketConfirmationGroups"] = [
        {"groupId": x.get("groupId"), "title": x.get("title"),
         "road": x.get("road"), "reason": x.get("pendingReason")}
        for x in pending
    ]
    payload["offMarketPolicy"] = (
        "all represented listings must have independently verified removedAt; "
        "unknown 591 source absence is not a delisting; include active 5168 veto"
    )
    return payload


def main():
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = json.loads(GAP.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    out = build_offmarket_report(state, payload, now)
    assert out["recentOffMarketCount"] == len(out["recentOffMarketGroups"])
    for group in out["recentOffMarketGroups"]:
        removed = parse_dt(group.get("removedAt"))
        assert removed is not None and removed > now - timedelta(days=RETENTION_DAYS)
        assert group.get("offMarket") is True and group.get("active") is False
        assert group.get("offMarketPendingConfirmation") is False
    GAP.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "retentionDays": RETENTION_DAYS,
        "confirmedRemovedGroupCount": out["recentOffMarketCount"],
        "unconfirmedRemovedCandidateCount": out["pendingOffMarketConfirmationCount"],
        "includes5168ActiveVeto": True,
        "unknown591IsNotDelisting": True
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
