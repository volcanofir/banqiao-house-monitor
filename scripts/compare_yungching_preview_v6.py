import json
import math
from datetime import datetime, timezone
from pathlib import Path

import compare_yungching_preview_v5 as v5


BROWSER_SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
HOUSEFUN_FETCH = v5.ORIGINAL_FETCH_COMPANY
ORIGINAL_LISTING_FLOORS = v5.listing_floors

OFFICIAL_STATS = {
    "enabled": True,
    "capturedAt": None,
    "snapshotAgeMinutes": None,
    "acceptedRoadCount": 0,
    "fallbackRoadCount": 0,
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


def completeness_ok(official_count, proxy_count):
    """Conservative per-road guard before replacing the existing proxy with official DOM data."""
    if official_count <= 0:
        return False, "官方瀏覽器快照沒有案件"

    if proxy_count >= 8:
        minimum = max(5, math.ceil(proxy_count * 0.80))
        if official_count < minimum:
            return False, f"官方僅 {official_count} 筆，低於代理 {proxy_count} 筆的80%安全門檻（至少 {minimum} 筆）"
    elif proxy_count >= 5:
        minimum = max(1, proxy_count - 1)
        if official_count < minimum:
            return False, f"官方僅 {official_count} 筆，低於小樣本安全門檻 {minimum} 筆"
    elif proxy_count > 0 and official_count < proxy_count:
        return False, f"官方 {official_count} 筆少於代理 {proxy_count} 筆"

    return True, "官方快照通過完整性門檻"


def official_first_fetch_company():
    proxy_company, logs, proxy_status = HOUSEFUN_FETCH()

    if not BROWSER_SNAPSHOT.exists():
        logs.append("永慶官方瀏覽器資料：快照不存在，全部沿用好房網代理。")
        return proxy_company, logs, proxy_status

    try:
        snap = json.loads(BROWSER_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        logs.append(f"永慶官方瀏覽器資料：快照讀取失敗（{type(exc).__name__}），全部沿用好房網代理。")
        return proxy_company, logs, proxy_status

    captured_at = snap.get("capturedAt")
    age = snapshot_age_minutes(captured_at)
    OFFICIAL_STATS["capturedAt"] = captured_at
    OFFICIAL_STATS["snapshotAgeMinutes"] = None if age is None else round(age, 1)

    # This snapshot is generated earlier in the same Preview workflow. Refuse a stale
    # file so a failed browser run can never silently reuse very old official data.
    if age is None or age < -10 or age > 60:
        logs.append(f"永慶官方瀏覽器資料：快照時間異常或超過60分鐘（age={age}），全部沿用好房網代理。")
        return proxy_company, logs, proxy_status

    browser_status = snap.get("roadStatus") or {}
    browser_rows = snap.get("listings") or []
    selected_company = []
    selected_status = {}

    for road in v5.v4.prev.base.ROADS:
        proxy_rows = [dict(x) for x in proxy_company if x.get("road") == road]
        official_rows = [browser_row(x, road) for x in browser_rows if x.get("road") == road]
        pst = dict(proxy_status.get(road) or {})
        ost = dict(browser_status.get(road) or {})

        official_count = len(official_rows)
        proxy_count = len(proxy_rows)
        browser_healthy = bool(
            ost.get("available") and
            ost.get("mainHttp") == 200 and
            official_count > 0
        )

        if browser_healthy:
            ok, reason = completeness_ok(official_count, proxy_count)
        else:
            ok = False
            reason = f"官方瀏覽器路段不可用（HTTP {ost.get('mainHttp')} / {official_count} 筆）"

        if ok:
            selected_company.extend(official_rows)
            selected_status[road] = {
                "count": official_count,
                "http": 200,
                "url": v5.v4.prev.base.housefun_url(road).replace("buy.housefun.com.tw/region/新北市-板橋區_c/", "buy.yungching.com.tw/list/新北市-板橋區_c/"),
                "available": True,
                "mode": "yungching_official_browser",
                "officialCount": official_count,
                "proxyCount": proxy_count,
                "browserCapturedAt": captured_at,
                "completenessCheck": reason,
            }
            OFFICIAL_STATS["acceptedRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "official",
                "officialCount": official_count,
                "proxyCount": proxy_count,
                "reason": reason,
            }
            logs.append(f"永慶官方瀏覽器資料：{road} 採用官方 {official_count} 筆（代理 {proxy_count} 筆）。")
        else:
            selected_company.extend(proxy_rows)
            pst["officialBrowserFallback"] = True
            pst["officialCount"] = official_count
            pst["proxyCount"] = proxy_count
            pst["officialFallbackReason"] = reason
            selected_status[road] = pst
            OFFICIAL_STATS["fallbackRoadCount"] += 1
            OFFICIAL_STATS["roads"][road] = {
                "mode": "proxy_fallback",
                "officialCount": official_count,
                "proxyCount": proxy_count,
                "reason": reason,
            }
            logs.append(f"永慶官方瀏覽器資料：{road} 暫不採用官方，沿用代理 {proxy_count} 筆；{reason}。")

    return selected_company, logs, selected_status


def structured_listing_floors(x, company=False):
    floors = set(ORIGINAL_LISTING_FLOORS(x, company=company))
    if not x:
        return floors

    # Browser DOM extraction now provides a dedicated subject-floor field.
    # Prefer/use it in addition to text parsing so "9/11樓" is not lost when
    # the title itself contains no floor wording.
    raw = x.get("floor")
    if raw not in (None, ""):
        floors |= v5.floors_from_text(str(raw), company_text=company)
    return floors


def main():
    # Make v5's existing anomaly guard wrap our official-first source selector.
    # If browser data is partial or stale, it falls back per-road to the current
    # Housefun proxy; then v5's previous-snapshot guard still protects abrupt drops.
    v5.ORIGINAL_FETCH_COMPANY = official_first_fetch_company
    v5.listing_floors = structured_listing_floors
    v5.main()

    path = v5.v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware_official_first_v6"
    payload["fetchMode"] = "yungching_official_browser_guarded_fallback"
    payload["companyDataSource"] = (
        "永慶房仲網官方公開搜尋頁（Surfshark＋Chromium）優先；"
        "路段資料不完整、被擋或異常時自動回退好房網公開買屋頁（僅篩選永慶房屋(股)公司）＋必要時 HAR fallback"
    )
    payload["officialBrowserCompany"] = dict(OFFICIAL_STATS)
    payload["structuredFloorMatching"] = True
    payload["note"] = (
        "PREVIEW v6：591先重新互相比對，再與信義整併且信義為主，最後比公司庫存。"
        "公司來源優先使用永慶官方公開搜尋頁的 Chromium 渲染結果；每條路先做完整性檢查，"
        "不完整或被擋時只回退該路段到既有代理資料。公司資料異常保護仍保留。"
        "官方 DOM 的結構化樓層欄位也納入樓層比對。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "fetchMode": payload["fetchMode"],
        "officialBrowserCompany": OFFICIAL_STATS,
        "companyDataGuard": payload.get("companyDataGuard"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
