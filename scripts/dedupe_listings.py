import json
import re
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")


def text_key(value):
    text = str(value or "").lower()
    # Keep Chinese characters and ASCII letters/numbers; remove emoji,
    # punctuation, spaces and decorative symbols used in listing titles.
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


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

    area_diff = abs(area_a - area_b)
    similarity = title_similarity(a.get("title"), b.get("title"))

    # Strong case: essentially the same title and almost the same area.
    # Price may have changed between duplicated/reposted IDs; keep newest.
    if title_a and title_a == title_b and area_diff <= 0.10:
        return True

    # Normal duplicate case: same price, same-sized property and highly
    # similar title. ±0.05坪 covers the 0.01坪 rounding differences seen on 591.
    if (
        price_a is not None
        and price_b is not None
        and abs(price_a - price_b) < 0.001
        and area_diff <= 0.05
        and similarity >= 0.72
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


def dedupe_591(rows):
    non_591 = [item for item in rows if item.get("source") != "591"]
    source_rows = [item for item in rows if item.get("source") == "591"]

    # Newest first makes the retained record naturally point at the newest ID.
    source_rows.sort(
        key=lambda item: (
            int(item.get("postTime") or 0),
            str(item.get("lastSeenAt") or ""),
        ),
        reverse=True,
    )

    kept = []
    for item in source_rows:
        duplicate_index = None
        for index, existing in enumerate(kept):
            if is_same_591_property(item, existing):
                duplicate_index = index
                break

        if duplicate_index is None:
            kept.append(item)
        else:
            kept[duplicate_index] = choose_keeper(kept[duplicate_index], item)

    return non_591 + kept, len(source_rows) - len(kept)


def main():
    if not DATA_PATH.exists():
        print("No listings data found; nothing to dedupe.")
        return

    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    before = state.get("listings") or []
    after, removed = dedupe_591(before)

    # Preserve the site's normal sort order.
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
        run["totalCount"] = visible_count
        run["dedupeRemoved"] = removed
        base_message = str(run.get("message") or "").split("；顯示去重後", 1)[0]
        if removed:
            run["message"] = (
                f"{base_message}；顯示去重後 {visible_count} 筆"
                f"（合併 {removed} 筆重複）。"
            )
        else:
            run["message"] = f"{base_message}；顯示去重後 {visible_count} 筆。"
        logs = run.setdefault("logs", [])
        logs.append(f"591 物件層去重：合併 {removed} 筆重複，顯示 {visible_count} 筆。")
        run["logs"] = logs[-60:]

    DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"591 dedupe removed {removed} duplicate rows.")


if __name__ == "__main__":
    main()
