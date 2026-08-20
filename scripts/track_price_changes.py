import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")


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
        ids.add(item["id"])
    for value in item.get("mergedListingIds") or []:
        if value:
            ids.add(value)
    for member in group_members(item):
        if member.get("id"):
            ids.add(member["id"])
    return ids


def effective_price(item):
    prices = []
    for member in group_members(item):
        if member.get("active", True):
            value = number(member.get("price"))
            if value is not None and value > 0:
                prices.append(value)
    if not prices:
        value = number(item.get("price"))
        return value
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


def same_property(current, previous):
    if current.get("source") != previous.get("source"):
        return False
    if current.get("road") != previous.get("road"):
        return False

    if group_ids(current) & group_ids(previous):
        return True

    ca, pa = area(current), area(previous)
    if ca is None or pa is None or abs(ca - pa) > 0.20:
        return False

    current_addresses = normalized_address(current)
    previous_addresses = normalized_address(previous)
    for a in current_addresses:
        for b in previous_addresses:
            if a == b and len(a) >= 6:
                return True
            # Exact lane/number fragments are strong even when one ad appends district text.
            if len(a) >= 10 and len(b) >= 10 and (a in b or b in a):
                return True

    best_title = 0.0
    for a in titles(current):
        for b in titles(previous):
            best_title = max(best_title, similarity(a, b))
    return best_title >= 0.68


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


def main():
    if not DATA_PATH.exists():
        print("No listings data; skip price tracking.")
        return

    current_state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    previous_state = load_previous()
    current_rows = current_state.get("listings") or []
    previous_rows = previous_state.get("listings") or []

    previous_by_source = {}
    for item in previous_rows:
        previous_by_source.setdefault(item.get("source"), []).append(item)

    changed = 0
    for item in current_rows:
        current_price = effective_price(item)
        if current_price is None:
            continue

        candidates = previous_by_source.get(item.get("source"), [])
        old = next((x for x in candidates if same_property(item, x)), None)
        if not old:
            item["effectivePrice"] = compact_price(current_price)
            continue

        previous_price = effective_price(old)
        if previous_price is None:
            item["effectivePrice"] = compact_price(current_price)
            continue

        # Carry prior history and latest change metadata forward.
        history = list(old.get("priceHistory") or [])
        for key in ("previousEffectivePrice", "priceChangeAmount", "priceChangeDirection", "priceChangedAt"):
            if old.get(key) is not None:
                item[key] = old.get(key)

        if not history:
            history.append({
                "price": compact_price(previous_price),
                "at": old.get("lastSeenAt") or previous_state.get("updatedAt"),
            })

        item["effectivePrice"] = compact_price(current_price)
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

        # Keep a compact history to prevent JSON growth forever.
        item["priceHistory"] = history[-12:]

    run = current_state.setdefault("runs", {}).setdefault("priceTracking", {})
    run.update({
        "checkedAt": current_state.get("updatedAt"),
        "changedCount": changed,
        "message": f"本輪偵測到 {changed} 筆案件價格異動。",
    })

    DATA_PATH.write_text(json.dumps(current_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Price tracking completed: {changed} changed properties.")


if __name__ == "__main__":
    main()
