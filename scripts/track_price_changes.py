import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")
# v3 tightens property identity matching. Bumping the version intentionally
# rebuilds the baseline once so any false v2 price-change labels/history are cleared.
TRACKING_VERSION = 3


def number(value):
    if value in (None, ""):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group(0)) if m else None


def text_key(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower().replace("臺", "台"))


def similarity(a, b):
    aa, bb = text_key(a), text_key(b)
    if not aa or not bb:
        return 0.0
    return SequenceMatcher(None, aa, bb).ratio()


def group_members(item):
    members = item.get("mergedListings")
    if isinstance(members, list) and members:
        return members
    return [item]


def group_ids(item):
    ids = set()
    if item.get("id"):
        ids.add(str(item["id"]))
    if item.get("houseId"):
        ids.add(f'{item.get("source")}:{item["houseId"]}')
    for value in item.get("mergedListingIds") or []:
        if value:
            ids.add(str(value))
    for member in group_members(item):
        if member.get("id"):
            ids.add(str(member["id"]))
        elif member.get("houseId"):
            ids.add(f'{item.get("source")}:{member["houseId"]}')
    return ids


def effective_price(item):
    prices = []
    for member in group_members(item):
        if member.get("active", True):
            value = number(member.get("price"))
            if value is not None and value > 0:
                prices.append(value)
    if not prices:
        return number(item.get("price"))
    return min(prices)


def area(item):
    value = number(item.get("size"))
    if value is not None:
        return value
    for member in group_members(item):
        value = number(member.get("size"))
        if value is not None:
            return value
    return None


def normalized_address(item):
    values = [item.get("address")] + [x.get("address") for x in group_members(item)]
    return [text_key(v) for v in values if text_key(v)]


def titles(item):
    values = [item.get("title")] + [x.get("title") for x in group_members(item)]
    return [v for v in values if v]


def is_specific_address(value):
    """Reject road-only/generic addresses that are shared by many properties."""
    key = text_key(value)
    if not key:
        return False
    # A street number / lane / alley / floor-like locator is strong evidence.
    if re.search(r"\d", key) or any(marker in key for marker in ("巷", "弄", "號")):
        return True
    # Remove common administrative/road-only wording. Anything substantial left
    # is usually a community/building name and can be used as identity evidence.
    reduced = key
    for marker in (
        "新北市", "板橋區", "中山路二段", "三民路二段", "三民路一段",
        "光復街", "萬安街", "林森街", "翠華街",
    ):
        reduced = reduced.replace(text_key(marker), "")
    return len(reduced) >= 4


def same_property(current, previous):
    if current.get("source") != previous.get("source"):
        return False
    if current.get("road") != previous.get("road"):
        return False

    # Stable listing IDs (including any member of a merged 591 group) are the
    # safest identity key and should always win.
    if group_ids(current) & group_ids(previous):
        return True

    # Sinyi house IDs are stable. Never fuzzy-match one Sinyi listing to another;
    # this was the main cause of huge false price jumps between unrelated homes.
    if current.get("source") == "信義房屋":
        return False

    # For 591, a completely replaced advertising group can occasionally have no
    # overlapping IDs. Only allow a fallback match with very strong evidence.
    ca, pa = area(current), area(previous)
    if ca is None or pa is None or abs(ca - pa) > 0.10:
        return False

    current_addresses = normalized_address(current)
    previous_addresses = normalized_address(previous)
    for a in current_addresses:
        for b in previous_addresses:
            if not (is_specific_address(a) and is_specific_address(b)):
                continue
            if a == b:
                return True
            if len(a) >= 12 and len(b) >= 12 and (a in b or b in a):
                return True

    # Title fallback is deliberately strict. Missing a rare legitimate change is
    # preferable to showing a wrong rise/drop badge on an unrelated property.
    best_title = 0.0
    for a in titles(current):
        for b in titles(previous):
            best_title = max(best_title, similarity(a, b))
    return best_title >= 0.92


def load_previous():
    try:
        raw = subprocess.check_output(
            ["git", "show", "HEAD:docs/data/listings.json"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw)
    except Exception:
        return {"listings": []}


def compact_price(value):
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 1)


def clear_change_fields(item):
    for key in (
        "previousEffectivePrice",
        "priceChangeAmount",
        "priceChangeDirection",
        "priceChangedAt",
    ):
        item.pop(key, None)


def main():
    if not DATA_PATH.exists():
        print("No listings data; skip price tracking.")
        return

    current_state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    previous_state = load_previous()
    current_rows = current_state.get("listings") or []
    previous_rows = previous_state.get("listings") or []
    previous_tracking = (previous_state.get("runs") or {}).get("priceTracking") or {}
    baseline_mode = previous_tracking.get("version") != TRACKING_VERSION

    previous_by_source = {}
    for item in previous_rows:
        previous_by_source.setdefault(item.get("source"), []).append(item)

    changed = 0
    for item in current_rows:
        current_price = effective_price(item)
        if current_price is None:
            clear_change_fields(item)
            item.pop("priceHistory", None)
            continue

        item["effectivePrice"] = compact_price(current_price)
        candidates = previous_by_source.get(item.get("source"), [])
        old = next((x for x in candidates if same_property(item, x)), None)

        if baseline_mode:
            clear_change_fields(item)
            item["priceHistory"] = [{
                "price": compact_price(current_price),
                "at": current_state.get("updatedAt") or item.get("lastSeenAt"),
            }]
            continue

        if not old:
            clear_change_fields(item)
            item["priceHistory"] = [{
                "price": compact_price(current_price),
                "at": current_state.get("updatedAt") or item.get("lastSeenAt"),
            }]
            continue

        previous_price = effective_price(old)
        if previous_price is None:
            clear_change_fields(item)
            item["priceHistory"] = [{
                "price": compact_price(current_price),
                "at": current_state.get("updatedAt") or item.get("lastSeenAt"),
            }]
            continue

        history = list(old.get("priceHistory") or [])
        if not history:
            history.append({
                "price": compact_price(previous_price),
                "at": old.get("lastSeenAt") or previous_state.get("updatedAt"),
            })

        # Keep the most recent known change visible until another change occurs.
        for key in ("previousEffectivePrice", "priceChangeAmount", "priceChangeDirection", "priceChangedAt"):
            if old.get(key) is not None:
                item[key] = old.get(key)

        diff = round(current_price - previous_price, 1)
        if abs(diff) >= 0.1:
            direction = "down" if diff < 0 else "up"
            item["previousEffectivePrice"] = compact_price(previous_price)
            item["priceChangeAmount"] = compact_price(abs(diff))
            item["priceChangeDirection"] = direction
            item["priceChangedAt"] = current_state.get("updatedAt") or item.get("lastSeenAt")
            history.append({
                "price": compact_price(current_price),
                "at": item["priceChangedAt"],
                "direction": direction,
                "change": compact_price(abs(diff)),
            })
            changed += 1

        item["priceHistory"] = history[-12:]

    run = current_state.setdefault("runs", {}).setdefault("priceTracking", {})
    run.update({
        "version": TRACKING_VERSION,
        "checkedAt": current_state.get("updatedAt"),
        "changedCount": changed,
        "baselineInitialized": baseline_mode,
        "message": (
            "價格追蹤基準已重新建立，本輪不標示歷史價格差異。"
            if baseline_mode
            else f"本輪偵測到 {changed} 筆案件價格異動。"
        ),
    })

    DATA_PATH.write_text(json.dumps(current_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "Price tracking baseline initialized."
        if baseline_mode
        else f"Price tracking completed: {changed} changed properties."
    )


if __name__ == "__main__":
    main()
