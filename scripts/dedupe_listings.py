import json
import re
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")


def text_key(value):
    text = str(value or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def chinese_key(value):
    text = str(value or "").lower().replace("臺", "台")
    return re.sub(r"[^0-9\u4e00-\u9fff]+", "", text)


def number_from_text(value):
    if value in (None, ""):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def title_similarity(a, b):
    a = text_key(a)
    b = text_key(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def location_key(item):
    address = str(item.get("address") or "").replace("臺", "台")
    prefix = address.split("板橋區", 1)[0].replace("新北市", "").strip()
    key = chinese_key(prefix)
    return key if len(key) >= 2 else None


def numbered_address_key(item):
    address = str(item.get("address") or "").replace("臺", "台")
    if "號" not in address:
        return None
    return chinese_key(address)


def structured_hint(item, kind):
    text = f"{item.get('title') or ''} {item.get('address') or ''}"
    if kind == "room":
        mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        match = re.search(r"([1-9一二三四五六七八九])\s*房", text)
        if not match:
            return None
        raw = match.group(1)
        return int(raw) if raw.isdigit() else mapping.get(raw)
    if kind == "floor":
        match = re.search(r"(?<!\d)(\d{1,2})\s*樓", text)
        return int(match.group(1)) if match else None
    return None


def has_conflicting_hints(a, b):
    for kind in ("room", "floor"):
        left = structured_hint(a, kind)
        right = structured_hint(b, kind)
        if left is not None and right is not None and left != right:
            return True
    return False


def is_same_591_property(a, b):
    if a.get("source") != "591" or b.get("source") != "591":
        return False
    if a.get("road") != b.get("road"):
        return False

    area_a = number_from_text(a.get("size"))
    area_b = number_from_text(b.get("size"))
    price_a = number_from_text(a.get("price"))
    price_b = number_from_text(b.get("price"))
    title_a = text_key(a.get("title"))
    title_b = text_key(b.get("title"))

    if area_a is None or area_b is None:
        return False
    if has_conflicting_hints(a, b):
        return False

    area_diff = abs(area_a - area_b)
    similarity = title_similarity(a.get("title"), b.get("title"))
    price_diff = None if price_a is None or price_b is None else abs(price_a - price_b)

    if title_a and title_a == title_b and area_diff <= 0.15:
        return True

    addr_a = numbered_address_key(a)
    addr_b = numbered_address_key(b)
    if (
        addr_a
        and addr_b
        and addr_a == addr_b
        and area_diff <= 0.20
        and price_a is not None
        and price_b is not None
        and price_diff <= max(30.0, min(price_a, price_b) * 0.02)
    ):
        return True

    loc_a = location_key(a)
    loc_b = location_key(b)
    if (
        loc_a
        and loc_b
        and loc_a == loc_b
        and price_diff is not None
        and price_diff <= 1.0
        and area_diff <= 0.15
    ):
        return True

    if (
        price_diff is not None
        and price_diff <= 1.0
        and area_diff <= 0.05
        and similarity >= 0.40
    ):
        return True

    if (
        price_diff is not None
        and price_diff <= 1.0
        and area_diff <= 0.15
        and similarity >= 0.62
    ):
        return True

    return False


def choose_keeper(a, b):
    def rank(item):
        return (
            1 if item.get("active", True) else 0,
            int(item.get("postTime") or 0),
            str(item.get("lastSeenAt") or ""),
            str(item.get("id") or ""),
        )

    keeper, other = (a, b) if rank(a) >= rank(b) else (b, a)
    merged = dict(keeper)

    first_seen = [x for x in (a.get("firstSeenAt"), b.get("firstSeenAt")) if x]
    last_seen = [x for x in (a.get("lastSeenAt"), b.get("lastSeenAt")) if x]
    new_at = [x for x in (a.get("newAt"), b.get("newAt")) if x]

    if first_seen:
        merged["firstSeenAt"] = min(first_seen)
    if last_seen:
        merged["lastSeenAt"] = max(last_seen)
    merged["newAt"] = min(new_at) if new_at else None

    if a.get("active", True) or b.get("active", True):
        merged["active"] = True
        merged["removedAt"] = None
    else:
        removed = [x for x in (a.get("removedAt"), b.get("removedAt")) if x]
        merged["active"] = False
        merged["removedAt"] = max(removed) if removed else None

    return merged


def review_item(item):
    return {
        "id": item.get("id"),
        "houseId": item.get("houseId"),
        "title": item.get("title"),
        "url": item.get("url"),
        "price": item.get("price"),
        "size": item.get("size"),
        "address": item.get("address"),
        "postTime": item.get("postTime"),
        "sourcePublishedAt": item.get("sourcePublishedAt"),
        "sourcePublishedAtType": item.get("sourcePublishedAtType"),
        "firstSeenAt": item.get("firstSeenAt"),
        "lastSeenAt": item.get("lastSeenAt"),
        "active": item.get("active", True),
    }


def expand_members(members):
    """Flatten any previously merged record so the audit list stays complete."""
    expanded = []
    seen = set()
    for item in members:
        candidates = [review_item(item)]
        old_members = item.get("mergedListings")
        if isinstance(old_members, list):
            candidates.extend(old_members)
        for candidate in candidates:
            item_id = candidate.get("id")
            if item_id and item_id not in seen:
                seen.add(item_id)
                expanded.append(candidate)
    return expanded


def finalize_cluster(record, members):
    merged = dict(record)
    detailed_members = expand_members(members)
    ids = [item.get("id") for item in detailed_members if item.get("id")]
    active_count = sum(1 for item in detailed_members if item.get("active", True))

    for key in (
        "mergedListingCount",
        "mergedDuplicateCount",
        "mergedActiveListingCount",
        "mergedListingIds",
        "mergedListings",
    ):
        merged.pop(key, None)

    if len(ids) > 1:
        detailed_members.sort(
            key=lambda item: (
                int(item.get("postTime") or 0),
                str(item.get("lastSeenAt") or ""),
            ),
            reverse=True,
        )
        merged["mergedListingCount"] = len(ids)
        merged["mergedDuplicateCount"] = len(ids) - 1
        merged["mergedActiveListingCount"] = active_count
        merged["mergedListingIds"] = ids
        merged["mergedListings"] = detailed_members

        member_new_times = [item.get("newAt") for item in members]
        if not member_new_times or not all(member_new_times):
            merged["newAt"] = None
        else:
            merged["newAt"] = min(member_new_times)

    return merged


def dedupe_591(rows):
    non_591 = [item for item in rows if item.get("source") != "591"]
    source_rows = [item for item in rows if item.get("source") == "591"]

    source_rows.sort(
        key=lambda item: (
            int(item.get("postTime") or 0),
            str(item.get("lastSeenAt") or ""),
        ),
        reverse=True,
    )

    clusters = []
    for item in source_rows:
        duplicate_index = None
        for index, cluster in enumerate(clusters):
            if is_same_591_property(item, cluster["record"]):
                duplicate_index = index
                break

        if duplicate_index is None:
            clusters.append({"record": item, "members": [item]})
        else:
            cluster = clusters[duplicate_index]
            cluster["members"].append(item)
            cluster["record"] = choose_keeper(cluster["record"], item)

    kept = [finalize_cluster(c["record"], c["members"]) for c in clusters]
    return non_591 + kept, len(source_rows) - len(kept)


def main():
    if not DATA_PATH.exists():
        print("No listings data found; nothing to dedupe.")
        return

    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    before = state.get("listings") or []
    after, removed = dedupe_591(before)

    after = sorted(
        after,
        key=lambda item: (
            0 if item.get("active", True) else 1,
            -(item.get("postTime") or 0),
            item.get("firstSeenAt") or "",
        ),
    )[:600]
    state["listings"] = after

    run = (state.setdefault("runs", {})).get("591")
    if isinstance(run, dict):
        visible_count = sum(
            1 for item in after
            if item.get("source") == "591" and item.get("active", True)
        )
        merged_groups = sum(
            1 for item in after
            if item.get("source") == "591" and int(item.get("mergedListingCount") or 0) > 1
        )
        checked_at = run.get("checkedAt")
        distinct_new_count = sum(
            1 for item in after
            if item.get("source") == "591"
            and item.get("active", True)
            and checked_at
            and item.get("newAt") == checked_at
        )
        run["totalCount"] = visible_count
        run["newCount"] = distinct_new_count
        run["dedupeRemoved"] = removed
        run["dedupeGroups"] = merged_groups
        base_message = str(run.get("message") or "").split("；顯示去重後", 1)[0]
        if removed:
            run["message"] = (
                f"{base_message}；顯示去重後 {visible_count} 筆"
                f"（{merged_groups} 組案件，共合併 {removed} 筆重複刊登）。"
            )
        else:
            run["message"] = f"{base_message}；顯示去重後 {visible_count} 筆。"
        logs = run.setdefault("logs", [])
        logs.append(
            f"591 物件層去重：{merged_groups} 組案件，共合併 {removed} 筆重複刊登，顯示 {visible_count} 筆；本輪實際新案件 {distinct_new_count} 筆。"
        )
        run["logs"] = logs[-60:]

    DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"591 dedupe grouped {removed} duplicate rows.")


if __name__ == "__main__":
    main()
