import json
import re
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")


def norm(value):
    return str(value or "").lower().replace("臺", "台")


def text_key(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", norm(value))


def number(value):
    if value in (None, ""):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group(0)) if m else None


def similarity(a, b):
    aa, bb = text_key(a), text_key(b)
    if not aa or not bb:
        return 0.0
    return 1.0 if aa == bb else SequenceMatcher(None, aa, bb).ratio()


def normalized_feature_text(item):
    text = norm(f"{item.get('title') or ''} {item.get('address') or ''}")
    aliases = {
        "鼎家": "頂加",
        "鼎加": "頂加",
        "頂家": "頂加",
        "頂樓加蓋": "頂加",
        "頂樓增建": "頂加",
        "7+8": "頂加",
        "7＋8": "頂加",
        "七加八": "頂加",
        "美寓": "公寓",
        "大陽台": "陽台",
        "前後大陽台": "前後陽台",
    }
    for src, dst in aliases.items():
        text = text.replace(src, dst)
    return text


def features(item):
    text = normalized_feature_text(item)
    found = set()
    terms = {
        "埔墘": ("埔墘",),
        "家樂福": ("家樂福",),
        "光復學區": ("光復學區", "光復國小"),
        "公寓": ("公寓",),
        "電梯": ("電梯",),
        "頂加": ("頂加",),
        "一樓": ("1樓", "一樓"),
        "二樓": ("2樓", "二樓"),
        "三樓": ("3樓", "三樓"),
        "三房": ("3房", "三房"),
        "四房": ("4房", "四房"),
        "方正": ("方正",),
        "邊間": ("邊間",),
        "三面採光": ("三面採光",),
        "前後陽台": ("前後陽台",),
        "天然瓦斯": ("天然瓦斯",),
        "內外梯": ("內外梯", "內外樓梯"),
        "景觀": ("景觀",),
        "雙車位": ("雙車位", "雙平車", "雙坡平"),
        "地下室": ("地下室",),
        "店面": ("店面",),
        "透天": ("透天",),
        "收租": ("收租",),
    }
    for key, aliases in terms.items():
        if any(alias in text for alias in aliases):
            found.add(key)
    return found


def room_hint(item):
    text = normalized_feature_text(item)
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    m = re.search(r"([1-9一二三四五六七八九])\s*房", text)
    if not m:
        return None
    raw = m.group(1)
    return int(raw) if raw.isdigit() else mapping.get(raw)


def floor_hint(item):
    text = normalized_feature_text(item)
    m = re.search(r"(?<!\d)(\d{1,2})\s*樓", text)
    return int(m.group(1)) if m else None


def conflicts(a, b):
    ra, rb = room_hint(a), room_hint(b)
    if ra is not None and rb is not None and ra != rb:
        return True
    fa, fb = floor_hint(a), floor_hint(b)
    if fa is not None and fb is not None and fa != fb:
        return True
    return False


def numbered_address(item):
    address = norm(item.get("address"))
    if "號" not in address:
        return None
    return re.sub(r"[^0-9\u4e00-\u9fff]+", "", address)


def lane_address(item):
    address = norm(item.get("address"))
    m = re.search(r"([\u4e00-\u9fff]+路(?:一|二|三|四|五|六|七|八|九|十|\d+)?段\d+巷(?:\d+弄)?)", address)
    return re.sub(r"[^0-9\u4e00-\u9fff]+", "", m.group(1)) if m else None


def community(item):
    address = norm(item.get("address"))
    prefix = address.split("板橋區", 1)[0].replace("新北市", "").strip()
    key = re.sub(r"[^0-9\u4e00-\u9fff]+", "", prefix)
    generic = {
        "", "板橋", "中山路二段", "三民路一段", "三民路二段",
        "光復街", "萬安街", "林森街", "翠華街",
    }
    return key if len(key) >= 2 and key not in generic else None


def same_property(a, b):
    if a.get("source") != "591" or b.get("source") != "591":
        return False
    if a.get("road") != b.get("road"):
        return False

    area_a, area_b = number(a.get("size")), number(b.get("size"))
    price_a, price_b = number(a.get("price")), number(b.get("price"))
    if area_a is None or area_b is None:
        return False
    if conflicts(a, b):
        return False

    area_diff = abs(area_a - area_b)
    price_diff = None if price_a is None or price_b is None else abs(price_a - price_b)
    title_sim = similarity(a.get("title"), b.get("title"))

    if text_key(a.get("title")) and text_key(a.get("title")) == text_key(b.get("title")) and area_diff <= 0.15:
        return True

    addr_a, addr_b = numbered_address(a), numbered_address(b)
    if addr_a and addr_b and addr_a == addr_b and area_diff <= 0.20:
        if price_diff is None or price_diff <= max(30.0, min(price_a, price_b) * 0.02):
            return True

    lane_a, lane_b = lane_address(a), lane_address(b)
    if lane_a and lane_b and lane_a == lane_b and area_diff <= 0.15 and price_diff is not None and price_diff <= 1.0:
        return True

    comm_a, comm_b = community(a), community(b)
    if comm_a and comm_b and comm_a == comm_b and area_diff <= 0.15 and price_diff is not None and price_diff <= 1.0:
        return True

    if price_diff is None or price_diff > 1.0 or area_diff > 0.05:
        return False

    fa, fb = features(a), features(b)
    common = fa & fb
    high_signal = {
        "頂加", "三面採光", "內外梯", "雙車位", "地下室",
        "三房", "四房", "方正", "邊間", "前後陽台", "天然瓦斯",
        "一樓", "二樓", "三樓", "店面", "透天",
    }

    # Exact price + exact area on the same road is already a strong signature.
    # Two shared descriptive features are enough even when agents use very
    # different marketing titles (e.g. 埔墘+公寓, 方正+公寓).
    if len(common) >= 2:
        return True

    # One concrete structural feature can bridge differently worded ads; the
    # cluster matching below makes this transitive across all known members.
    if common & high_signal:
        return True

    # Keep a conservative text fallback for ads whose useful features are not
    # in the dictionary yet.
    return title_sim >= 0.36


def published_rank(item):
    value = item.get("sourcePublishedAt") or item.get("postTime")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**18


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


def expand_item(item):
    rows = [review_item(item)]
    if isinstance(item.get("mergedListings"), list):
        rows.extend(item["mergedListings"])
    out, seen = [], set()
    for row in rows:
        row_id = row.get("id")
        if row_id and row_id not in seen:
            seen.add(row_id)
            out.append(row)
    return out


def choose_oldest(members):
    return min(
        members,
        key=lambda item: (
            published_rank(item),
            str(item.get("firstSeenAt") or ""),
            str(item.get("id") or ""),
        ),
    )


def build_record(members, originals):
    detailed = []
    seen = set()
    for member in members:
        for row in expand_item(member):
            row_id = row.get("id")
            if row_id and row_id not in seen:
                seen.add(row_id)
                detailed.append(row)

    oldest = choose_oldest(detailed)
    source = originals.get(oldest.get("id")) or oldest
    merged = dict(source)

    first_seen = [x.get("firstSeenAt") for x in detailed if x.get("firstSeenAt")]
    last_seen = [x.get("lastSeenAt") for x in detailed if x.get("lastSeenAt")]
    if first_seen:
        merged["firstSeenAt"] = min(first_seen)
    if last_seen:
        merged["lastSeenAt"] = max(last_seen)

    any_active = any(x.get("active", True) for x in detailed)
    merged["active"] = any_active
    merged["removedAt"] = None if any_active else merged.get("removedAt")

    for key in ("mergedListingCount", "mergedDuplicateCount", "mergedActiveListingCount", "mergedListingIds", "mergedListings"):
        merged.pop(key, None)

    detailed.sort(key=lambda x: (published_rank(x), str(x.get("firstSeenAt") or ""), str(x.get("id") or "")))
    if len(detailed) > 1:
        merged["mergedListingCount"] = len(detailed)
        merged["mergedDuplicateCount"] = len(detailed) - 1
        merged["mergedActiveListingCount"] = sum(1 for x in detailed if x.get("active", True))
        merged["mergedListingIds"] = [x.get("id") for x in detailed if x.get("id")]
        merged["mergedListings"] = detailed

        # Reposts are not new properties. The group is new only when every
        # top-level member entering this pass was newly discovered.
        member_new = [x.get("newAt") for x in members]
        merged["newAt"] = min(member_new) if member_new and all(member_new) else None

    return merged


def cluster_matches(item, cluster):
    candidates = []
    for member in cluster:
        candidates.extend(expand_item(member))
    return any(same_property(item, candidate) for candidate in candidates)


def dedupe(rows):
    non_591 = [x for x in rows if x.get("source") != "591"]
    source_rows = [x for x in rows if x.get("source") == "591"]

    originals = {}
    for item in source_rows:
        originals[item.get("id")] = item
        for old in expand_item(item):
            originals.setdefault(old.get("id"), old)

    source_rows.sort(key=lambda x: (int(x.get("postTime") or 0), str(x.get("lastSeenAt") or "")), reverse=True)
    clusters = []
    for item in source_rows:
        match = None
        for idx, cluster in enumerate(clusters):
            if cluster_matches(item, cluster):
                match = idx
                break
        if match is None:
            clusters.append([item])
        else:
            clusters[match].append(item)

    kept = [build_record(cluster, originals) for cluster in clusters]
    raw_ids = set()
    for item in source_rows:
        for row in expand_item(item):
            if row.get("id"):
                raw_ids.add(row["id"])
    visible_ids = {x.get("id") for x in kept if x.get("id")}
    removed = max(0, len(raw_ids) - len(visible_ids))
    return non_591 + kept, removed


def main():
    if not DATA_PATH.exists():
        print("No listings data found; nothing to dedupe.")
        return

    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    after, removed = dedupe(state.get("listings") or [])
    after.sort(key=lambda x: (0 if x.get("active", True) else 1, -(x.get("postTime") or 0), x.get("firstSeenAt") or ""))
    state["listings"] = after[:600]

    run = state.setdefault("runs", {}).get("591")
    if isinstance(run, dict):
        visible = [x for x in state["listings"] if x.get("source") == "591" and x.get("active", True)]
        groups = [x for x in visible if int(x.get("mergedListingCount") or 0) > 1]
        checked_at = run.get("checkedAt")
        new_count = sum(1 for x in visible if checked_at and x.get("newAt") == checked_at)
        run["totalCount"] = len(visible)
        run["newCount"] = new_count
        run["dedupeRemoved"] = removed
        run["dedupeGroups"] = len(groups)
        base = str(run.get("message") or "").split("；顯示去重後", 1)[0]
        run["message"] = f"{base}；顯示去重後 {len(visible)} 筆（{len(groups)} 組案件，共合併 {removed} 筆重複刊登）。"
        logs = run.setdefault("logs", [])
        logs.append(f"591 強化物件去重：{len(groups)} 組案件，共合併 {removed} 筆重複刊登，顯示 {len(visible)} 筆；本輪實際新案件 {new_count} 筆。")
        run["logs"] = logs[-60:]

    DATA_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"591 enhanced dedupe grouped {removed} duplicate rows.")


if __name__ == "__main__":
    main()
