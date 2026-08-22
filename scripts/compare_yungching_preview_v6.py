import json
import re
from datetime import datetime, timezone
from pathlib import Path

import compare_yungching_preview_v5 as v5


BROWSER_SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
ORIGINAL_LISTING_FLOORS = v5.listing_floors

OFFICIAL_STATS = {
    "enabled": True,
    "capturedAt": None,
    "snapshotAgeMinutes": None,
    "acceptedRoadCount": 0,
    "unavailableRoadCount": 0,
    "roads": {},
}


def snapshot_age_minutes(captured_at):
    if not captured_at:
        return None
    try:
        t = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds() / 60
    except Exception:
        return None


def browser_row(src, road):
    x = dict(src)
    raw_id = str(x.get("id") or "").strip()
    x["id"] = f"YC:{raw_id}" if raw_id else f"YC:{road}:{x.get('title') or ''}"
    x["officialId"] = raw_id or None
    x["road"] = road
    x.setdefault("address", f"新北市{road}")
    x.setdefault("area", None)
    x.setdefault("price", None)
    x["text"] = x.get("text") or x.get("rawText") or x.get("title") or ""
    x["sourceMode"] = "yungching_official_browser"
    return x


def official_rendered_fetch_company():
    """Use only the fresh rendered Yongching Chromium snapshot for Preview company matching.

    A road is accepted when the official page itself returned HTTP 200 and rendered at
    least one valid listing card. We intentionally do NOT compare official counts to
    Housefun/proxy counts anymore: the rendered Yongching page is the source of truth.
    If a road cannot be rendered reliably in this run, mark that road unavailable so
    Preview shows '尚未比對' instead of silently substituting proxy inventory.
    """
    logs = []
    selected_company = []
    selected_status = {}

    if not BROWSER_SNAPSHOT.exists():
        for road in v5.v4.prev.base.ROADS:
            selected_status[road] = {
                "count": 0,
                "http": None,
                "available": False,
                "mode": "yungching_official_browser_unavailable",
                "error": "永慶官方 Chromium 快照不存在",
            }
            OFFICIAL_STATS["unavailableRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {"mode": "unavailable", "officialCount": 0, "reason": "快照不存在"}
        logs.append("永慶官方瀏覽器資料：快照不存在；Preview 公司比對全部標示尚未比對。")
        return selected_company, logs, selected_status

    try:
        snap = json.loads(BROWSER_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        for road in v5.v4.prev.base.ROADS:
            selected_status[road] = {
                "count": 0,
                "http": None,
                "available": False,
                "mode": "yungching_official_browser_unavailable",
                "error": f"快照讀取失敗：{type(exc).__name__}",
            }
            OFFICIAL_STATS["unavailableRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {"mode": "unavailable", "officialCount": 0, "reason": "快照讀取失敗"}
        logs.append(f"永慶官方瀏覽器資料：快照讀取失敗（{type(exc).__name__}）；不使用代理資料。")
        return selected_company, logs, selected_status

    captured_at = snap.get("capturedAt")
    age = snapshot_age_minutes(captured_at)
    OFFICIAL_STATS["capturedAt"] = captured_at
    OFFICIAL_STATS["snapshotAgeMinutes"] = None if age is None else round(age, 1)

    # The snapshot should be generated earlier in the same workflow run. Refuse stale
    # output so a failed browser run can never reuse yesterday's company inventory.
    fresh_snapshot = age is not None and -10 <= age <= 90
    browser_status = snap.get("roadStatus") or {}
    browser_rows = snap.get("listings") or []

    for road in v5.v4.prev.base.ROADS:
        ost = dict(browser_status.get(road) or {})
        official_rows = [browser_row(x, road) for x in browser_rows if x.get("road") == road]
        official_count = len(official_rows)
        road_http = ost.get("mainHttp")
        road_ok = bool(fresh_snapshot and road_http == 200 and ost.get("available") and official_count > 0)

        if road_ok:
            selected_company.extend(official_rows)
            selected_status[road] = {
                "count": official_count,
                "http": 200,
                "available": True,
                "mode": "yungching_official_browser",
                "officialCount": official_count,
                "browserCapturedAt": captured_at,
                "source": "永慶房仲網官方公開搜尋頁實際渲染 DOM",
            }
            OFFICIAL_STATS["acceptedRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "official",
                "officialCount": official_count,
                "http": road_http,
            }
            logs.append(f"永慶官方瀏覽器資料：{road} 採用官方渲染 DOM {official_count} 筆。")
        else:
            reason = "官方快照過期或時間異常" if not fresh_snapshot else f"官方頁不可用（HTTP {road_http} / {official_count} 筆）"
            selected_status[road] = {
                "count": 0,
                "http": road_http,
                "available": False,
                "mode": "yungching_official_browser_unavailable",
                "officialCount": official_count,
                "browserCapturedAt": captured_at,
                "error": reason,
            }
            OFFICIAL_STATS["unavailableRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "unavailable",
                "officialCount": official_count,
                "http": road_http,
                "reason": reason,
            }
            logs.append(f"永慶官方瀏覽器資料：{road} 本輪不採用；{reason}。不回退代理資料。")

    return selected_company, logs, selected_status


def structured_listing_floors(x, company=False):
    floors = set(ORIGINAL_LISTING_FLOORS(x, company=company))
    if not x:
        return floors

    # Rendered DOM extraction provides a dedicated subject-floor field such as
    # "9/11樓" or "14~15/16樓". Include it in the existing floor-aware matcher.
    raw = x.get("floor")
    if raw not in (None, ""):
        floor_text = str(raw)
        floors |= v5.floors_from_text(floor_text, company_text=company)

        # A split-level unit can occupy more than one subject floor. The v5 parser
        # correctly reads the last subject floor before '/', but add the whole range
        # here so 14~15/16樓 means subject floors {14, 15}, never total-floor 16.
        for m in re.finditer(r"(\d{1,2})\s*[~～-]\s*(\d{1,2})\s*/\s*\d{1,2}\s*樓", floor_text):
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= hi <= 99 and hi - lo <= 5:
                floors.update(range(lo, hi + 1))
    return floors


def main():
    # PREVIEW only. Production crawler and production UI remain untouched.
    v5.ORIGINAL_FETCH_COMPANY = official_rendered_fetch_company
    v5.listing_floors = structured_listing_floors
    v5.main()

    path = v5.v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware_official_rendered_v6"
    payload["fetchMode"] = "yungching_official_rendered_dom_only"
    payload["companyDataSource"] = "永慶房仲網官方公開搜尋頁：Surfshark → Chromium → 實際渲染 DOM"
    payload["companySnapshotCapturedAt"] = OFFICIAL_STATS.get("capturedAt")
    payload["officialBrowserCompany"] = dict(OFFICIAL_STATS)
    payload["structuredFloorMatching"] = True
    payload["note"] = (
        "PREVIEW v6：591先重新互相比對，再與信義整併且信義為主，最後比公司庫存。"
        "公司庫存只採用本輪 Surfshark + Chromium 成功載入的永慶官方公開搜尋頁渲染結果；"
        "直接從 DOM 擷取案件 ID、案名、價格、坪數、樓層後進入 Preview 比對。"
        "官方路段抓取失敗時標示尚未比對，不再用好房網或其他代理資料覆蓋。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "fetchMode": payload["fetchMode"],
        "companySnapshotCapturedAt": payload.get("companySnapshotCapturedAt"),
        "officialBrowserCompany": OFFICIAL_STATS,
        "companyDataGuard": payload.get("companyDataGuard"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
