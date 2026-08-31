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
    """Return only this run's fresh Yongching rendered DOM inventory.

    No Housefun, HAR or previous-snapshot replacement is allowed in v6. A road is
    accepted only when the official page returned HTTP 200, its snapshot is fresh,
    the collector marked the road complete, and the exact-address result is either
    populated or explicitly verified empty by the official keyword page.
    """
    logs = []
    selected_company = []
    selected_status = {}

    OFFICIAL_STATS["acceptedRoadCount"] = 0
    OFFICIAL_STATS["unavailableRoadCount"] = 0
    OFFICIAL_STATS["roads"] = {}

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
        logs.append(f"永慶官方瀏覽器資料：快照讀取失敗（{type(exc).__name__}）；不使用任何替代資料。")
        return selected_company, logs, selected_status

    captured_at = snap.get("capturedAt")
    age = snapshot_age_minutes(captured_at)
    OFFICIAL_STATS["capturedAt"] = captured_at
    OFFICIAL_STATS["snapshotAgeMinutes"] = None if age is None else round(age, 1)

    fresh_snapshot = age is not None and -10 <= age <= 90
    browser_status = snap.get("roadStatus") or {}
    browser_rows = snap.get("listings") or []

    for road in v5.v4.prev.base.ROADS:
        ost = dict(browser_status.get(road) or {})
        official_rows = [browser_row(x, road) for x in browser_rows if x.get("road") == road]
        official_count = len(official_rows)
        road_http = ost.get("mainHttp")
        pagination_ok = (not ost.get("paginationExpected")) or ost.get("paginationComplete") is True
        empty_verified = bool(official_count == 0 and ost.get("emptyResultVerified") is True)
        road_ok = bool(
            fresh_snapshot and road_http == 200 and ost.get("available") and
            (official_count > 0 or empty_verified) and pagination_ok
        )

        if road_ok:
            selected_company.extend(official_rows)
            selected_status[road] = {
                "count": official_count,
                "http": 200,
                "available": True,
                "mode": "yungching_official_browser",
                "officialCount": official_count,
                "browserCapturedAt": captured_at,
                "paginationExpected": ost.get("paginationExpected"),
                "paginationComplete": ost.get("paginationComplete"),
                "paginationActivePage": ost.get("paginationActivePage"),
                "emptyResultVerified": empty_verified,
                "source": "永慶房仲網官方公開搜尋頁實際渲染 DOM",
            }
            OFFICIAL_STATS["acceptedRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "official",
                "officialCount": official_count,
                "http": road_http,
                "paginationComplete": ost.get("paginationComplete"),
                "emptyResultVerified": empty_verified,
            }
            if empty_verified:
                logs.append(f"永慶官方瀏覽器資料：{road} 官方關鍵字頁已驗證目前為 0 筆。")
            else:
                logs.append(f"永慶官方瀏覽器資料：{road} 採用官方渲染 DOM {official_count} 筆。")
        else:
            if not fresh_snapshot:
                reason = "官方快照過期或時間異常"
            elif ost.get("paginationExpected") and ost.get("paginationComplete") is not True:
                reason = "官方頁有分頁但未完成全部頁面擷取"
            else:
                reason = f"官方頁不可用（HTTP {road_http} / {official_count} 筆）"
            selected_status[road] = {
                "count": 0,
                "http": road_http,
                "available": False,
                "mode": "yungching_official_browser_unavailable",
                "officialCount": official_count,
                "browserCapturedAt": captured_at,
                "paginationExpected": ost.get("paginationExpected"),
                "paginationComplete": ost.get("paginationComplete"),
                "paginationActivePage": ost.get("paginationActivePage"),
                "error": reason,
            }
            OFFICIAL_STATS["unavailableRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "unavailable",
                "officialCount": official_count,
                "http": road_http,
                "reason": reason,
            }
            logs.append(f"永慶官方瀏覽器資料：{road} 本輪不採用；{reason}。不回退 HAR、代理或前次快照。")

    return selected_company, logs, selected_status


def no_har_fallback(company, road_status, logs):
    """Disable v2/v3's historical HAR replacement for official-only Preview v6."""
    logs.append("PREVIEW v6：HAR fallback 已停用；公司資料僅允許本輪永慶官方 Chromium DOM。")
    return company, None


def floors_from_structured_value(raw):
    floors = set()
    if raw in (None, ""):
        return floors
    floor_text = str(raw)
    floors |= v5.floors_from_text(floor_text, company_text=True)
    for m in re.finditer(r"(\d{1,2})\s*[~～-]\s*(\d{1,2})\s*/\s*\d{1,2}\s*樓", floor_text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 99 and hi - lo <= 5:
            floors.update(range(lo, hi + 1))
    return floors


def structured_listing_floors(x, company=False):
    """Use Yongching's structured floor as the sole company-floor truth when present.

    The official list DOM can concatenate area and floor text (for example
    `主32.333/3樓`). Scanning the entire company text can therefore invent a fake
    33rd floor. Once a structured `floor` field exists, do not union text-inferred
    company floors back into it. External 591/Sinyi matching keeps the legacy title
    inference because those feeds do not have the same structured field guarantee.
    """
    if not x:
        return set()

    raw = x.get("floor")
    if company and raw not in (None, ""):
        return floors_from_structured_value(raw)

    floors = set(ORIGINAL_LISTING_FLOORS(x, company=company))
    if raw not in (None, ""):
        floors |= floors_from_structured_value(raw)
    return floors


def expose_company_candidate_fields(payload):
    """Expose the exact official ID/floor used by the matcher for human Preview review."""
    by_id = {str(x.get("id")): x for x in (payload.get("companyListings") or []) if x.get("id")}
    for cmp_row in payload.get("comparisons") or []:
        candidate = cmp_row.get("companyCandidate")
        if not candidate:
            continue
        source = by_id.get(str(candidate.get("id")))
        if not source:
            continue
        candidate["officialId"] = source.get("officialId") or str(source.get("id") or "").removeprefix("YC:")
        candidate["officialCaseId"] = source.get("officialCaseId")
        candidate["floor"] = source.get("floor")
        candidate["floorSourceMode"] = source.get("floorSourceMode")
        candidate["floorEvidence"] = source.get("floorEvidence")
        candidate["type"] = source.get("type")


def main():
    # PREVIEW only. Production crawler and production UI remain untouched.
    # Patch every legacy escape hatch: v5 previous-snapshot guard AND v3 HAR fallback.
    v5.ORIGINAL_FETCH_COMPANY = official_rendered_fetch_company
    v5.guarded_fetch_company = official_rendered_fetch_company
    v5.v4.prev.base.load_har_fallback = no_har_fallback
    v5.listing_floors = structured_listing_floors
    v5.main()

    path = v5.v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware_official_rendered_v6"
    payload["fetchMode"] = "yungching_official_rendered_dom_only"
    payload["companyDataSource"] = "永慶房仲網官方公開搜尋頁：Surfshark → Chromium → 實際渲染 DOM；缺樓層時同路徑開官方案件頁補值"
    payload["companySnapshotCapturedAt"] = OFFICIAL_STATS.get("capturedAt")
    payload["officialBrowserCompany"] = dict(OFFICIAL_STATS)
    payload["structuredFloorMatching"] = True
    payload["companyDataGuard"] = {
        "enabled": False,
        "rule": "官方 DOM only：停用 HAR、代理與前次快照替補；不完整路段直接標示尚未比對",
        "triggeredRoadCount": 0,
        "roads": [],
    }
    expose_company_candidate_fields(payload)
    payload["note"] = (
        "PREVIEW v6：591先重新互相比對，再與信義整併且信義為主，最後比公司庫存。"
        "公司庫存只採用本輪 Surfshark + Chromium 成功載入的永慶官方公開搜尋頁渲染結果；"
        "直接從 DOM 擷取案件 ID、案名、價格、坪數、樓層，缺樓層時再開永慶官方案件頁補值。"
        "官方路段抓取或分頁不完整時一律標示尚未比對，HAR、好房網、代理與前次快照替補全部停用。"
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
