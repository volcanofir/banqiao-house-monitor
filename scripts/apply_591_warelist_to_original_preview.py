"""Overlay verified 591 wareList into the EXISTING Scheme A Preview (not production).

Run after sinyi_preview_floor_enrich.py and before Rakuya/5168 append.
This replaces only 591 rows in the existing Preview comparator input and writes
the same Preview UI's monitor state. Existing scheme-A property grouping and
cross-platform comparisons are unchanged.

Important semantics:
* A current wareList ID is observed advertising, including previously archived IDs.
* Historical IDs not seen in a complete search are NOT confirmed delisted.
  Keep their archive/price history, but do not call them currently observed.
  In the Preview-only copy, such rows are marked inactive with NO removedAt
  unless there already was an authoritative removedAt.
* A first-time-seen 591 ID is not automatically a new property.
* Never touch docs/data/listings.json, production UI, or original historical state.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import dedupe_listings_v2 as dedupe
import track_price_changes as prices
from diagnose_591_warelist_integrity import ROADS
from unittest.mock import patch
from warelist_structured_fields import carried_fields, source_floor_tokens

# Restrict floor-aware clustering to Preview. This never patches the canonical
# crawler's deduplication code or its persisted historical records.
_BASE_RAW_ROW = dedupe.raw_row
_BASE_SAME_PROPERTY = dedupe.same_property


def _preview_raw_row(item, parent=None):
    row = _BASE_RAW_ROW(item, parent)
    # Never inherit a parent's floor into a distinct nested advertisement ID.
    row.update(carried_fields(item))
    return row


def _preview_same_property(a, b):
    af, bf = source_floor_tokens(a), source_floor_tokens(b)
    if af and bf and af.isdisjoint(bf):
        return False
    return _BASE_SAME_PROPERTY(a, b)


def _preview_cluster_matches(item, members):
    # Prevent transitive unknown-floor advertisements from bridging two
    # explicitly different floors in the same building.
    known = set().union(*(source_floor_tokens(x) for x in members))
    incoming = source_floor_tokens(item)
    if known and incoming and known.isdisjoint(incoming):
        return False
    return any(_preview_same_property(item, old) for old in members)


def _preview_dedupe(rows):
    with patch.object(dedupe, "raw_row", _preview_raw_row), \
         patch.object(dedupe, "same_property", _preview_same_property), \
         patch.object(dedupe, "cluster_matches", _preview_cluster_matches):
        return dedupe.dedupe(rows)


def _assert_floor_integrity(groups):
    for group in groups:
        members = group.get("mergedListings") or [group]
        floors = [source_floor_tokens(x) for x in members]
        floors = [x for x in floors if x]
        if floors and not set.intersection(*floors):
            raise ValueError("591 Preview floor conflict in grouped advertisements")


SOURCE = Path("docs/591-preview/snapshot.json")
CANONICAL = Path("docs/data/listings.json")
ENRICHED = Path("docs/preview/scheme-a-external-enriched.json")
UI_SOURCE = Path("docs/preview/preview-monitor-state.json")
MAX_AGE_HOURS = 9


def date_time(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def merge_for_preview(enriched_state, snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    if snapshot.get("schemaVersion") != 1 or snapshot.get("complete") is not True:
        raise ValueError("591 wareList snapshot not complete")
    if snapshot.get("mode") != "preview_only" or snapshot.get("noOffmarketDecision") is not True:
        raise ValueError("591 snapshot has not guaranteed no offmarket decisions")
    if snapshot.get("noAutomaticNewPropertyDecision") is not True:
        raise ValueError("591 snapshot has not guaranteed no new property decisions")
    if snapshot.get("source") != "591_public_warelist_initial_state":
        raise ValueError("Unexpected 591 data source")
    road_counts = snapshot.get("roadCounts") or []
    expected = set(road.replace("板橋區", "") for road in ROADS)
    if len(road_counts) != len(ROADS) or {r.get("road") for r in road_counts} != expected:
        raise ValueError("Seven-road 591 snapshot is incomplete")
    listing_rows = snapshot.get("listings") or []
    if not listing_rows or len(listing_rows) != int((snapshot.get("counts") or {}).get("totalListings") or -1):
        raise ValueError("591 snapshot count mismatch")
    if len(listing_rows) != sum(int(r.get("count") or 0) for r in road_counts):
        raise ValueError("591 snapshot road totals mismatch")

    snap_time = date_time(snapshot.get("updatedAt"))
    age = (now - snap_time).total_seconds() / 3600
    if age < -0.25 or age > MAX_AGE_HOURS:
        raise ValueError(f"591 wareList snapshot stale/future: {age:.2f}h")

    original = enriched_state.get("listings")
    if not isinstance(original, list):
        raise ValueError("Missing existing Scheme A source records")
    previous_591 = [x for x in original if x.get("source") == "591"]
    non_591 = [x for x in original if x.get("source") != "591"]
    if not previous_591:
        raise ValueError("No canonical 591 history; refuse to start an empty history")

    historical = {str(x["id"]): x for x in dedupe.flatten_591(previous_591) if x.get("id")}
    observed = set()
    cur = []
    seen_by_road = {}
    old_matched = 0
    known_reappeared = 0
    for raw in listing_rows:
        key = str(raw.get("id") or "")
        road = "板橋區" + str(raw.get("road") or "")
        hid = str(raw.get("houseId") or "")
        if not key.startswith("591:") or not hid.isdigit() or key != "591:" + hid:
            raise ValueError("591 listing ID mismatch")
        if key in observed:
            raise ValueError("Duplicate 591 current ID")
        observed.add(key)
        if road not in ROADS or not str(raw.get("address") or "").strip() or not str(raw.get("title") or "").strip():
            raise ValueError("591 road or required text missing")
        if raw.get("price") is None or raw.get("size") is None or not raw.get("postTime"):
            raise ValueError("591 required price/area/publish timestamp missing")
        if raw.get("url") != "https://m.591.com.tw/v2/sale/" + hid:
            raise ValueError("591 listing URL mismatch")
        seen_by_road[road] = seen_by_road.get(road, 0) + 1
        old = historical.get(key)
        if old:
            old_matched += 1
            if old.get("active") is False:
                known_reappeared += 1
        row = copy.deepcopy(old) if old else {}
        # New data refreshes current observable fields but preserves historical
        # firstSeenAt, sourcePublishedAt (when better), and priceHistory.
        row.update({
            "id": key, "houseId": hid, "source": "591", "road": road,
            "title": raw["title"], "address": raw["address"],
            "price": raw["price"], "size": raw["size"], "postTime": raw["postTime"],
            "url": raw["url"], "active": True, "removedAt": None,
            "lastSeenAt": snapshot["updatedAt"],
            "preview591Observation": "warelist_observed",
            **carried_fields(raw),
        })
        if not row.get("firstSeenAt"):
            # Identity observation is not a verified new property event.
            row["firstSeenAt"] = snapshot["updatedAt"]
        row["newAt"] = old.get("newAt") if old else None
        if not old or not old.get("sourcePublishedAt"):
            row["sourcePublishedAt"] = raw["postTime"]
            row["sourcePublishedAtType"] = "591_warelist_posttime"
        cur.append(row)
    for road in ROADS:
        if seen_by_road.get(road, 0) != next(int(r.get("count")) for r in road_counts if r.get("road") == road.replace("板橋區", "")):
            raise ValueError("591 road count does not reconcile")

    # Protect all other historical ads, never mark missing ID as delisted.
    unseen_history = []
    for key, old in historical.items():
        if key in observed:
            continue
        archival = copy.deepcopy(old)
        archival["active"] = False
        if old.get("active", True):
            archival["removedAt"] = None
            archival["preview591Observation"] = "unconfirmed_not_in_current_result"
        else:
            # Already confirmed removed; original removedAt must survive.
            archival["preview591Observation"] = "historical_inactive"
        unseen_history.append(archival)
    rebuilt, _, raw_count = _preview_dedupe(cur + unseen_history)
    groups_591 = [x for x in rebuilt if x.get("source") == "591"]
    _assert_floor_integrity(groups_591)
    # Restore property-level price histories by exact historic advertisement IDs,
    # never by fuzzy title/price guesses. Preserve the existing rule of tracking
    # only real effective-price changes on the same property.
    previous_groups = [
        (x, {m.get("id") for m in dedupe.flatten_591([x]) if m.get("id")})
        for x in previous_591
    ]
    for group in groups_591:
        member_ids = {m.get("id") for m in dedupe.flatten_591([group]) if m.get("id")}
        matched = [old for old, ids in previous_groups if member_ids & ids]
        if len(matched) != 1:
            continue
        old = matched[0]
        for key in ("priceHistory", "previousEffectivePrice", "priceChangeAmount",
                    "priceChangeDirection", "priceChangedAt"):
            if old.get(key) is not None:
                group[key] = copy.deepcopy(old[key])
        prior_price = prices.effective_price(old)
        current_price = prices.effective_price(group)
        if prior_price is None or current_price is None:
            continue
        group["effectivePrice"] = current_price
        diff = round(current_price - prior_price, 1)
        if abs(diff) >= 0.1:
            group["previousEffectivePrice"] = prior_price
            group["priceChangeAmount"] = abs(diff)
            group["priceChangeDirection"] = "down" if diff < 0 else "up"
            group["priceChangedAt"] = snapshot["updatedAt"]
            history = list(old.get("priceHistory") or [])
            if not history:
                history.append({"price": prior_price, "at": old.get("lastSeenAt")})
            history.append({
                "price": current_price, "at": snapshot["updatedAt"],
                "direction": group["priceChangeDirection"], "change": abs(diff)})
            group["priceHistory"] = history[-12:]
    new_flat = {x["id"]: x for x in dedupe.flatten_591(groups_591)}
    if set(new_flat) != set(historical) | observed:
        raise ValueError("591 identity loss during original property grouping")
    for key, old in historical.items():
        current = new_flat[key]
        if old.get("firstSeenAt"):
            assert current.get("firstSeenAt") == old.get("firstSeenAt"), key
        if key not in observed:
            assert current.get("active") is False, key
            if old.get("active") is False:
                assert current.get("removedAt") == old.get("removedAt"), key
            else:
                assert current.get("removedAt") is None, key
    result = copy.deepcopy(enriched_state)
    result["listings"] = non_591 + groups_591
    # Only the Preview UI receives this successful 591 source status.
    # The authoritative docs/data/listings.json still retains its real crawl
    # status (including 403/error) and unchanged historical source timestamps.
    result.setdefault("runs", {})["591"] = {
        "checkedAt": snapshot["updatedAt"],
        "status": "ok",
        "mode": "warelist_preview",
        "totalCount": sum(bool(g.get("active")) for g in groups_591),
        "observedListingIdCount": len(cur),
        "newCount": 0,
        "removedCount": 0,
        "message": "591 公開 wareList 七路段已驗證；新刊登及下架仍以原有房屋層級規則判定。",
        "logs": [],
    }
    result.setdefault("previewSources", {})["591"] = {
        "mode": "warelist_preview",
        "status": "ok", "complete": True,
        "updatedAt": snapshot["updatedAt"],
        "totalCount": len(cur),
        "uniqueListingCount": len(cur),
        "groupCount": sum(bool(x.get("active")) for x in groups_591),
        "roadCounts": road_counts,
        "sourceFieldCoverage": snapshot.get("sourceFieldCoverage") or {},
        "floorAwarePreviewGrouping": True,
        "historyMatchedIdCount": old_matched,
        "historyNotPresentUnconfirmed": len(unseen_history),
        "historyReappearedCount": known_reappeared,
        "missingIdIsNotDelisting": True,
        "newIdIsNotNewProperty": True,
    }
    # Keep canonical source version for existing signed verification contract;
    # this preview-specific source timestamp lives in previewSources['591'].
    # The canonical 591 status/history and its updatedAt never change.
    assert result["updatedAt"] == enriched_state["updatedAt"]
    return result


def main():
    snapshot = json.loads(SOURCE.read_text(encoding="utf-8"))
    source = json.loads(ENRICHED.read_text(encoding="utf-8"))
    base = json.loads(CANONICAL.read_text(encoding="utf-8"))
    if source.get("updatedAt") != base.get("updatedAt"):
        raise RuntimeError("Enriched state not aligned with canonical state")
    result = merge_for_preview(source, snapshot)
    # Write only after full validation of all seven roads and member history.
    ENRICHED.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    UI_SOURCE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "preview591": result["previewSources"]["591"],
        "sourceDataUpdatedAt": result["updatedAt"],
        "productionListingsUnaffected": True
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
