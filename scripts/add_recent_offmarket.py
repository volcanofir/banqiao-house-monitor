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


def main():
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = json.loads(GAP.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)

    all_external = [
        x for x in state.get("listings", [])
        if x.get("source") in {"591", "信義房屋"}
    ]
    relevant = []
    for x in all_external:
        if x.get("active", True):
            relevant.append(x)
            continue
        removed = parse_dt(x.get("removedAt"))
        if removed is not None and removed > cutoff:
            relevant.append(x)

    # Reuse the safe floor parser/structured Sinyi fields used by canonical v8.
    v4.title_floor_tokens = v7.safe_floor_numbers
    v4.listing_floor_tokens = v8.safe_listing_floor_tokens_with_structured
    v4.prev.compact_listing = v8.compact_listing_with_structured_floor

    groups, _ = v4.build_groups(relevant)
    status = id_status_map(relevant)
    offmarket = []

    for group in groups:
        member_ids = group_member_ids(group)
        states = [status.get(x) for x in member_ids if status.get(x) is not None]
        if not states:
            continue
        if any(x.get("active") for x in states):
            continue
        removed_times = [parse_dt(x.get("removedAt")) for x in states]
        removed_times = [x for x in removed_times if x is not None]
        if not removed_times:
            continue
        fully_removed_at = max(removed_times)
        if fully_removed_at <= cutoff:
            continue
        row = dict(group)
        row["active"] = False
        row["offMarket"] = True
        row["removedAt"] = fully_removed_at.isoformat(timespec="seconds")
        row["offMarketRetentionDays"] = RETENTION_DAYS
        offmarket.append(row)

    offmarket.sort(key=lambda x: x.get("removedAt") or "", reverse=True)
    payload["recentOffMarketRetentionDays"] = RETENTION_DAYS
    payload["recentOffMarketGeneratedAt"] = now.isoformat(timespec="seconds")
    payload["recentOffMarketCount"] = len(offmarket)
    payload["recentOffMarketGroups"] = offmarket

    assert payload["recentOffMarketCount"] == len(payload["recentOffMarketGroups"])
    for g in offmarket:
        d = parse_dt(g.get("removedAt"))
        assert d is not None and d > cutoff
        assert g.get("offMarket") is True and g.get("active") is False

    GAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "retentionDays": RETENTION_DAYS,
        "recentOffMarketCount": len(offmarket),
        "removedAt": [x.get("removedAt") for x in offmarket[:10]],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
