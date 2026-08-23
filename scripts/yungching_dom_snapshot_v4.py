"""PREVIEW-only Yongching DOM snapshot v4.

Uses Yongching's verified `pg=N` pagination and applies an ID-integrity guard after
collection. The guard removes impossible cross-road ID collisions such as the stale
`/house/4308114` href that the first rendered card can inherit even though the card text
belongs to a different property. Production monitor code is untouched.
"""

import json
import re
import sys
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yungching_dom_snapshot_v3 as v3


ORIGINAL_V3_CLICK_NUMERIC_PAGE = v3.click_numeric_page
SNAPSHOT = v3.base.OUT


def pg_url(url: str, target: int) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "pg"]
    query.append(("pg", str(target)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def direct_pg_page(page, target: int):
    before_pages = v3.pager_state(page)
    visible_pages = {
        str(x.get("text") or "").strip()
        for x in before_pages
        if str(x.get("text") or "").strip().isdigit()
    }
    if str(target) not in visible_pages:
        return {
            "clicked": False,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "reason": "target page is not advertised by rendered pager",
            "beforePages": before_pages,
        }

    before_url = page.url
    target_url = pg_url(before_url, target)
    try:
        response = page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        http = response.status if response else None
        page.wait_for_timeout(1800)
        activated = v3.wait_pager_active(page, target, timeout=5000)
        after_pages = v3.pager_state(page)
        ok = bool(http == 200 and activated)
        return {
            "clicked": ok,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "http": http,
            "beforeUrl": before_url,
            "targetUrl": target_url,
            "finalUrl": page.url,
            "beforePages": before_pages,
            "afterPages": after_pages,
            "activeVerified": bool(activated),
            "error": None if ok else "pg navigation did not produce HTTP 200 + active target page",
        }
    except Exception as exc:
        return {
            "clicked": False,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "beforeUrl": before_url,
            "targetUrl": target_url,
            "error": f"{type(exc).__name__}: {str(exc)[:220]}",
        }


def click_numeric_page(page, target: int):
    action = direct_pg_page(page, target)
    if action.get("clicked"):
        return action
    fallback = ORIGINAL_V3_CLICK_NUMERIC_PAGE(page, target)
    fallback.setdefault("previousDirectPg", action)
    return fallback


def norm_title(value):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "")).lower()


def fingerprint(row):
    area = row.get("area")
    price = row.get("price")
    try:
        area = round(float(area), 2)
    except Exception:
        area = None
    try:
        price = round(float(price), 1)
    except Exception:
        price = None
    return (str(row.get("road") or ""), norm_title(row.get("title")), area, price)


def sanitize_snapshot_integrity():
    """Remove impossible cross-road house-ID collisions from an existing snapshot.

    A real Yongching house ID cannot simultaneously belong to multiple exact road
    addresses. Current Yongching markup sometimes gives the first card a stale href
    while its text is correct. When that corrupt ID has a same-road sibling with the
    same title/area/price fingerprint and a non-colliding ID, preserve the sibling and
    drop the corrupt row. If no sibling exists, drop the impossible row rather than let
    a false ID enter company matching.
    """
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    rows = list(payload.get("listings") or [])
    before = len(rows)

    roads_by_id = defaultdict(set)
    for row in rows:
        rid = str(row.get("id") or "").strip()
        road = str(row.get("road") or "").strip()
        if rid and road:
            roads_by_id[rid].add(road)
    collision_ids = {rid for rid, roads in roads_by_id.items() if len(roads) > 1}

    good_by_fp = defaultdict(list)
    for row in rows:
        rid = str(row.get("id") or "").strip()
        if rid not in collision_ids:
            good_by_fp[fingerprint(row)].append(row)

    kept = []
    removed = []
    for row in rows:
        rid = str(row.get("id") or "").strip()
        if rid not in collision_ids:
            kept.append(row)
            continue
        fp = fingerprint(row)
        siblings = good_by_fp.get(fp) or []
        removed.append({
            "id": rid,
            "road": row.get("road"),
            "title": row.get("title"),
            "area": row.get("area"),
            "price": row.get("price"),
            "reason": "同一永慶 house ID 同時出現在不同道路；視為第一卡 stale href 汙染",
            "replacementIds": [str(x.get("id")) for x in siblings[:5]],
            "replacementFound": bool(siblings),
        })

    # One more conservative de-duplication: same road + same non-colliding ID can only
    # occur once even if pages overlap.
    unique = []
    seen = set()
    for row in kept:
        key = (str(row.get("road") or ""), str(row.get("id") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    kept = unique

    remaining_roads_by_id = defaultdict(set)
    for row in kept:
        remaining_roads_by_id[str(row.get("id") or "")].add(str(row.get("road") or ""))
    remaining_collisions = sorted(
        rid for rid, roads in remaining_roads_by_id.items() if rid and len(roads) > 1
    )

    per_road_before = defaultdict(int)
    per_road_after = defaultdict(int)
    for row in rows:
        per_road_before[str(row.get("road") or "")] += 1
    for row in kept:
        per_road_after[str(row.get("road") or "")] += 1

    road_status = payload.get("roadStatus") or {}
    for road, status in road_status.items():
        status["rawCountBeforeIdIntegrity"] = per_road_before.get(road, 0)
        status["idIntegrityRemoved"] = per_road_before.get(road, 0) - per_road_after.get(road, 0)
        status["count"] = per_road_after.get(road, 0)

    payload["listings"] = kept
    payload["listingCount"] = len(kept)
    payload["idIntegrityGuard"] = {
        "enabled": True,
        "beforeCount": before,
        "afterCount": len(kept),
        "removedCount": before - len(kept),
        "collisionIds": sorted(collision_ids),
        "remainingCollisionIds": remaining_collisions,
        "removed": removed,
        "rule": "同一永慶 house ID 不得跨不同精確道路；跨路碰撞視為 stale href 並從 Preview 公司資料排除",
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"idIntegrityGuard": payload["idIntegrityGuard"]}, ensure_ascii=False))
    return payload["idIntegrityGuard"]


def main():
    v3.click_numeric_page = click_numeric_page
    v3.main()
    sanitize_snapshot_integrity()


if __name__ == "__main__":
    if "--sanitize-existing" in sys.argv:
        sanitize_snapshot_integrity()
    else:
        main()
