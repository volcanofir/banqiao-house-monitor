"""Yongching official /api/v2/list snapshot.

Primary fast path for the canonical Preview/company comparison:
- Warm one official Yongching search page in Chromium behind the already-selected VPN exit.
- Call the official encrypted /api/v2/list endpoint for all monitored roads.
- Reproduce Yongching's current frontend key derivation/decryption locally in the page.
- Keep only exact monitored-road addresses and write the same snapshot contract used by
  the previous DOM collector.

This script is intentionally all-or-nothing. Any road/API/decrypt/completeness failure
raises before replacing the canonical snapshot so the workflow can fall back to DOM v5.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUT = Path("docs/preview/yungching-browser-snapshot.json")
BASE = "https://buy.yungching.com.tw"
ROADS = [
    "板橋區中山路二段",
    "板橋區三民路一段",
    "板橋區三民路二段",
    "板橋區翠華街",
    "板橋區林森街",
    "板橋區萬安街",
    "板橋區光復街",
]
AREA = "新北市-板橋區"
PAGE_SIZE = 30
MAX_PAGES = 30

JS = r"""
async ({roads, area, pageSize, maxPages}) => {
  async function derive(serviceName) {
    const salt = new Uint8Array([2,7,0,5,1,3,8,0]);
    const digest = new Uint8Array(
      await crypto.subtle.digest('SHA-256', new TextEncoder().encode(serviceName))
    );
    const baseKey = await crypto.subtle.importKey(
      'raw', digest, 'PBKDF2', false, ['deriveBits']
    );
    const bits = await crypto.subtle.deriveBits(
      {name:'PBKDF2', salt, iterations:1000, hash:'SHA-1'},
      baseKey,
      384
    );
    const key = await crypto.subtle.importKey(
      'raw', bits.slice(0,32), {name:'AES-CBC'}, false, ['decrypt']
    );
    return [key, bits.slice(32,48)];
  }

  const keyMaterial = await derive('YungChing.Buy');

  async function decryptData(value) {
    const [key, iv] = keyMaterial;
    const ct = new Uint8Array(Array.from(atob(value), c => c.charCodeAt(0)));
    const raw = await crypto.subtle.decrypt(
      {name:'AES-CBC', iv:new Uint8Array(iv)}, key, ct
    );
    return JSON.parse(new TextDecoder().decode(raw));
  }

  async function getPage(road, pg) {
    const keyword = road.replace('板橋區', '');
    const u = new URL('/api/v2/list', location.origin);
    const params = {
      area,
      pinType: '0',
      isAddRoom: 'true',
      keyword,
      filter: '0',
      pg: String(pg),
      ps: String(pageSize)
    };
    for (const [k,v] of Object.entries(params)) u.searchParams.set(k,v);

    const resp = await fetch(u.toString(), {
      method:'GET',
      credentials:'include',
      headers:{accept:'application/json, text/plain, */*'}
    });
    let wrapper = null;
    try {
      wrapper = await resp.json();
    } catch (e) {
      throw new Error(JSON.stringify({
        road, pg, phase:'wrapper-json', http:resp.status, error:String(e)
      }));
    }
    if (!resp.ok || wrapper?.status !== 'Success' || !wrapper?.data) {
      throw new Error(JSON.stringify({
        road, pg, phase:'wrapper',
        http:resp.status, status:wrapper?.status,
        apiVersion:wrapper?.apiVersion, method:wrapper?.method
      }));
    }

    let body = null;
    try {
      body = await decryptData(wrapper.data);
    } catch (e) {
      throw new Error(JSON.stringify({
        road, pg, phase:'decrypt', http:resp.status, error:String(e)
      }));
    }

    return {
      http: resp.status,
      apiStatus: wrapper.status,
      apiVersion: wrapper.apiVersion ?? null,
      method: wrapper.method ?? null,
      dataLen: String(wrapper.data).length,
      url: u.toString(),
      body
    };
  }

  async function fetchRoad(road) {
    const first = await getPage(road, 1);
    const totalPages = Number(first.body?.pa?.totalPageCount || 1);
    if (!Number.isInteger(totalPages) || totalPages < 1 || totalPages > maxPages) {
      throw new Error(JSON.stringify({road, phase:'pagination', totalPages}));
    }

    const pages = [first];
    for (let pg=2; pg<=totalPages; pg++) {
      pages.push(await getPage(road, pg));
    }

    const perPageExactIds = {};
    const all = [];
    const prefix = '新北市' + road;
    for (let i=0; i<pages.length; i++) {
      const list = Array.isArray(pages[i].body?.list) ? pages[i].body.list : [];
      const exact = list.filter(x => String(x?.address || '').startsWith(prefix));
      perPageExactIds[String(i+1)] = [...new Set(
        exact.map(x => x?.caseSId).filter(x => x != null).map(String)
      )].sort();
      all.push(...list);
    }

    const uniqMap = new Map();
    for (const x of all) {
      if (x?.caseSId != null) uniqMap.set(String(x.caseSId), x);
    }
    const unique = [...uniqMap.values()];
    const exact = unique.filter(x => String(x?.address || '').startsWith(prefix));

    const rows = exact.map(x => ({
      caseSId: x.caseSId ?? null,
      caseName: x.caseName ?? null,
      address: x.address ?? null,
      price: x.price ?? null,
      pinInfo: x.pinInfo ?? null,
      floorInfo: x.floorInfo ?? null,
      patternInfo: x.patternInfo ?? null,
      caseType: x.caseType ?? null,
      caseTypeName: x.caseTypeName ?? null,
      objectType: x.objectType ?? null,
      objectTypeName: x.objectTypeName ?? null,
      buildingType: x.buildingType ?? null,
      buildingTypeName: x.buildingTypeName ?? null,
      typeName: x.typeName ?? null,
      useType: x.useType ?? null,
      useTypeName: x.useTypeName ?? null
    }));

    return {
      road,
      totalPages,
      apiTotalCount: first.body?.totalCount ?? null,
      paTotalItemCount: first.body?.pa?.totalItemCount ?? null,
      rawRows: all.length,
      uniqueRows: unique.length,
      exactRoadRows: rows.length,
      wrappers: pages.map((p,idx) => ({
        pg: idx+1,
        http: p.http,
        apiStatus: p.apiStatus,
        apiVersion: p.apiVersion,
        method: p.method,
        dataLen: p.dataLen,
        url: p.url
      })),
      perPageExactIds,
      listings: rows
    };
  }

  const out = [];
  for (const road of roads) out.push(await fetchRoad(road));
  return out;
}
"""


def road_url(road: str) -> str:
    keyword = road.replace("板橋區", "")
    return f"{BASE}/list/{quote(AREA)}_c/{quote(keyword)}_kw?od=80"


def clean_num(value):
    if value in (None, ""):
        return None
    try:
        f = float(value)
        if f.is_integer():
            return int(f)
        return round(f, 2)
    except Exception:
        m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if not m:
            return None
        f = float(m.group(0))
        return int(f) if f.is_integer() else round(f, 2)


def normalize_floor(info):
    if not isinstance(info, dict):
        return None
    lo = clean_num(info.get("fromFloor"))
    hi = clean_num(info.get("toFloor"))
    total = clean_num(info.get("upFloor"))
    if not all(isinstance(x, int) for x in (lo, total)):
        return None
    if not (1 <= lo <= total <= 99):
        return None
    if isinstance(hi, int) and hi != lo:
        if 1 <= lo <= hi <= total and hi - lo <= 10:
            return f"{lo}~{hi}/{total}樓"
        return None
    return f"{lo}/{total}樓"


def pick_type(row):
    for key in (
        "caseTypeName", "objectTypeName", "buildingTypeName", "typeName", "useTypeName",
        "caseType", "objectType", "buildingType", "useType",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return None


def room_text(pattern):
    if not isinstance(pattern, dict):
        return ""
    room = pattern.get("room")
    living = pattern.get("livingRoom")
    bath = pattern.get("bathRoom")
    bits = []
    if room is not None:
        bits.append(f"{room}房(室)")
    if living is not None:
        bits.append(f"{living}廳")
    if bath is not None:
        bits.append(f"{bath}衛")
    return "".join(bits)


def build_listing(raw, road):
    hid = str(raw.get("caseSId") or "").strip()
    if not hid:
        raise RuntimeError(f"{road}: API listing missing caseSId")
    title = re.sub(r"\s+", " ", str(raw.get("caseName") or "")).strip()
    if not title:
        raise RuntimeError(f"{road}: API listing {hid} missing caseName")

    address = re.sub(r"\s+", "", str(raw.get("address") or ""))
    expected = "新北市" + road
    if not address.startswith(expected):
        raise RuntimeError(f"{road}: exact-address guard failed for {hid}: {address!r}")

    area = clean_num((raw.get("pinInfo") or {}).get("regArea"))
    price = clean_num(raw.get("price"))
    floor = normalize_floor(raw.get("floorInfo"))
    ptype = pick_type(raw)
    pattern = raw.get("patternInfo") if isinstance(raw.get("patternInfo"), dict) else None

    pieces = [title, expected]
    if ptype:
        pieces.append(ptype)
    if area is not None:
        pieces.append(f"建坪{area}")
    if floor:
        pieces.append(floor)
    rt = room_text(pattern)
    if rt:
        pieces.append(rt)
    if price is not None:
        pieces.append(f"{price}萬")
    text = " ".join(str(x) for x in pieces if x not in (None, ""))

    return {
        "id": hid,
        "road": road,
        "title": title[:100],
        "price": price,
        "area": area,
        "floor": floor,
        "address": expected,
        "type": ptype,
        "url": f"{BASE}/house/{hid}",
        "sourceMode": "yungching_official_api",
        "text": text[:700],
        "rawText": text[:700],
        "patternInfo": pattern,
        "floorInfo": raw.get("floorInfo"),
    }


def warm_browser(page):
    url = road_url(ROADS[0])
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    status = resp.status if resp else None
    page.wait_for_timeout(1400)
    title = page.title()
    try:
        body = page.locator("body").inner_text(timeout=5000)[:3500]
    except Exception:
        body = ""
    ok = bool(
        status == 200
        and ROADS[0].replace("板橋區", "") in body
        and "request could not be satisfied" not in title.lower()
    )
    if not ok:
        raise RuntimeError(
            f"Yongching API warmup failed: HTTP {status}, title={title!r}, roadText={ROADS[0].replace('板橋區','') in body}"
        )
    return {"http": status, "url": page.url, "title": title[:160]}


def main():
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = context.new_page()
        warm = warm_browser(page)
        api_roads = page.evaluate(
            JS,
            {
                "roads": ROADS,
                "area": AREA,
                "pageSize": PAGE_SIZE,
                "maxPages": MAX_PAGES,
            },
        )
        browser.close()

    if len(api_roads) != len(ROADS):
        raise RuntimeError(f"Yongching API returned {len(api_roads)} roads, expected {len(ROADS)}")

    road_status = {}
    listings = []
    seen_ids = set()

    for result in api_roads:
        road = result.get("road")
        if road not in ROADS:
            raise RuntimeError(f"Unexpected Yongching API road: {road!r}")
        wrappers = result.get("wrappers") or []
        total_pages = int(result.get("totalPages") or 0)
        if total_pages < 1 or len(wrappers) != total_pages:
            raise RuntimeError(f"{road}: incomplete API pagination {len(wrappers)}/{total_pages}")
        if any(
            int(x.get("http") or 0) != 200
            or x.get("apiStatus") != "Success"
            or not x.get("dataLen")
            for x in wrappers
        ):
            raise RuntimeError(f"{road}: API wrapper completeness failure: {wrappers}")

        road_rows = []
        for raw in result.get("listings") or []:
            row = build_listing(raw, road)
            key = (road, row["id"])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            road_rows.append(row)
            listings.append(row)

        exact_count = len(road_rows)
        empty_verified = exact_count == 0
        page_ids = result.get("perPageExactIds") or {}
        raw_count = int(result.get("rawRows") or 0)
        unique_count = int(result.get("uniqueRows") or 0)

        road_status[road] = {
            "mainHttp": 200,
            "count": exact_count,
            "primarySearchUrl": road_url(road),
            "confirmationUsed": False,
            "primaryHttp": 200,
            "primaryFinalUrl": road_url(road),
            "primaryApiListHttp": 200,
            "primaryApiListSuccess": True,
            "primaryApiListStatus": "Success",
            "primaryApiListVersion": wrappers[0].get("apiVersion"),
            "primaryApiListDataLength": sum(int(x.get("dataLen") or 0) for x in wrappers),
            "primaryNavigationError": None,
            "title": "永慶房仲網官方 API",
            "roadTextCount": exact_count,
            "summary": [],
            "searchUrl": wrappers[0].get("url"),
            "loadRounds": 0,
            "pageRounds": max(0, total_pages - 1),
            "nextClicks": [],
            "anchorCount": 0,
            "controls": [],
            "paginationExpected": total_pages > 1,
            "paginationActivePage": total_pages,
            "paginationHighestAdvertisedPage": total_pages,
            "paginationLastPage": total_pages,
            "paginationExhausted": True,
            "paginationCompleteAllPages": True,
            "paginationComplete": True,
            "paginationPageNewIds": page_ids,
            "paginationPageRawNewIds": page_ids,
            "rawHouseIdCount": unique_count,
            "rawExactAddressTextCount": exact_count,
            "paginationError": None,
            "apiTotalCount": result.get("apiTotalCount"),
            "apiTotalItemCount": result.get("paTotalItemCount"),
            "apiRawRowCount": raw_count,
            "apiUniqueRowCount": unique_count,
            "emptyResultVerified": empty_verified,
            "skippedConfirmedEmpty": empty_verified,
            "transportEvidence": "official_api_v2_decrypted",
            "available": True,
            "rawCountBeforeIdIntegrity": exact_count,
            "idIntegrityRemoved": 0,
            "mode": "yungching_official_api",
            "source": "永慶房仲網官方 /api/v2/list（官方前端同演算法解密）",
        }

    # Cross-road duplicate IDs should never happen after exact-address filtering.
    roads_by_id = {}
    for row in listings:
        roads_by_id.setdefault(row["id"], set()).add(row["road"])
    collisions = sorted(k for k, roads in roads_by_id.items() if len(roads) > 1)
    if collisions:
        raise RuntimeError(f"Yongching API cross-road ID collision: {collisions[:10]}")

    payload = {
        "capturedAt": captured,
        "previewOnly": True,
        "source": "buy.yungching.com.tw official /api/v2/list decrypted after Chromium warmup",
        "captureMode": "yungching_official_api",
        "warmup": warm,
        "availableRoads": list(ROADS),
        "roadStatus": road_status,
        "listingCount": len(listings),
        "listings": listings,
        "paginationGuard": True,
        "paginationGuardVersion": "api-all-pages-v1",
        "idIntegrityGuard": {
            "enabled": True,
            "beforeCount": len(listings),
            "afterCount": len(listings),
            "removedCount": 0,
            "collisionIds": [],
            "remainingCollisionIds": [],
            "removed": [],
            "rule": "API精確地址過濾後，同一永慶 house ID 不得跨不同監控道路",
        },
        "apiSnapshot": {
            "enabled": True,
            "serviceName": "YungChing.Buy",
            "endpoint": "/api/v2/list",
            "pageSize": PAGE_SIZE,
            "roads": len(ROADS),
            "allRoadsComplete": True,
        },
    }

    # Atomic replace only after every road passes all completeness checks.
    tmp = OUT.with_suffix(".api.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)

    print(json.dumps({
        "mode": payload["captureMode"],
        "capturedAt": captured,
        "listingCount": len(listings),
        "roadCounts": {r: road_status[r]["count"] for r in ROADS},
        "floorsFromApi": sum(1 for x in listings if x.get("floor")),
        "missingFloors": sum(1 for x in listings if not x.get("floor")),
        "allRoadsComplete": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
