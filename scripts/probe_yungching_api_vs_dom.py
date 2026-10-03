import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROADS = [
    "中山路二段",
    "三民路一段",
    "三民路二段",
    "翠華街",
    "林森街",
    "萬安街",
    "光復街",
]
AREA = "新北市-板橋區"
DOM_PATH = Path("docs/preview/yungching-browser-snapshot.json")
OUT = Path("artifacts/yungching-api-vs-dom-report.json")

JS = r"""
async ({roads, area}) => {
  async function derive(serviceName) {
    const salt = new Uint8Array([2,7,0,5,1,3,8,0]);
    const digest = new Uint8Array(
      await crypto.subtle.digest('SHA-256', new TextEncoder().encode(serviceName))
    );
    const baseKey = await crypto.subtle.importKey('raw', digest, 'PBKDF2', false, ['deriveBits']);
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
    const u = new URL('/api/v2/list', location.origin);
    const params = {
      area,
      pinType: '0',
      isAddRoom: 'true',
      keyword: road,
      filter: '0',
      pg: String(pg),
      ps: '30'
    };
    for (const [k,v] of Object.entries(params)) u.searchParams.set(k,v);
    const resp = await fetch(u.toString(), {
      credentials:'include',
      headers:{accept:'application/json, text/plain, */*'}
    });
    const wrapper = await resp.json();
    if (!resp.ok || wrapper?.status !== 'Success' || !wrapper?.data) {
      throw new Error(JSON.stringify({
        road, pg, http:resp.status, status:wrapper?.status,
        apiVersion:wrapper?.apiVersion, method:wrapper?.method
      }));
    }
    return {
      http: resp.status,
      wrapper: {
        status: wrapper.status,
        apiVersion: wrapper.apiVersion,
        method: wrapper.method,
        dataLen: String(wrapper.data).length
      },
      body: await decryptData(wrapper.data)
    };
  }

  async function fetchRoad(road) {
    const first = await getPage(road, 1);
    const totalPages = Number(first.body?.pa?.totalPageCount || 1);
    const pages = [first];
    for (let pg=2; pg<=totalPages; pg++) pages.push(await getPage(road, pg));

    const raw = pages.flatMap(p => Array.isArray(p.body?.list) ? p.body.list : []);
    const uniq = [...new Map(
      raw.filter(x => x?.caseSId != null).map(x => [String(x.caseSId), x])
    ).values()];
    const prefix = '新北市板橋區' + road;
    const exact = uniq.filter(x => String(x?.address || '').startsWith(prefix));

    return {
      road,
      totalPages,
      apiTotalCount: first.body?.totalCount ?? null,
      paTotalItemCount: first.body?.pa?.totalItemCount ?? null,
      rawRows: raw.length,
      uniqueRows: uniq.length,
      exactRoadRows: exact.length,
      wrappers: pages.map((p,i)=>({pg:i+1, ...p.wrapper})),
      listings: exact.map(x => ({
        id: String(x.caseSId),
        title: x.caseName ?? null,
        address: x.address ?? null,
        price: x.price ?? null,
        area: x?.pinInfo?.regArea ?? null,
        floorInfo: x.floorInfo ?? null,
        patternInfo: x.patternInfo ?? null
      }))
    };
  }

  const results = [];
  for (const road of roads) results.push(await fetchRoad(road));
  return results;
}
"""

def nnum(v):
    try:
        return float(v)
    except Exception:
        return None

def norm_floor_from_api(info):
    if not isinstance(info, dict):
        return None
    f = info.get("fromFloor")
    t = info.get("toFloor")
    up = info.get("upFloor")
    if f is None or up is None:
        return None
    if t is not None and t != f:
        return f"{f}~{t}/{up}樓"
    return f"{f}/{up}樓"

def parse_pattern_from_dom(text):
    text = str(text or "")
    m = re.search(r"(\d+(?:\.\d+)?)房\(室\)(\d+(?:\.\d+)?)廳(\d+(?:\.\d+)?)衛", text)
    if not m:
        return None
    def cv(s):
        f=float(s)
        return int(f) if f.is_integer() else f
    return {"room":cv(m.group(1)), "livingRoom":cv(m.group(2)), "bathRoom":cv(m.group(3))}

def compact_pattern_api(p):
    if not isinstance(p, dict):
        return None
    return {
        "room": p.get("room"),
        "livingRoom": p.get("livingRoom"),
        "bathRoom": p.get("bathRoom"),
    }

def main():
    dom = json.loads(DOM_PATH.read_text(encoding="utf-8"))
    dom_by_road = {}
    for x in dom.get("listings") or []:
        road = str(x.get("road") or "")
        dom_by_road.setdefault(road, {})[str(x.get("id"))] = x

    warm = f"https://buy.yungching.com.tw/list/{quote(AREA)}_c/{quote(ROADS[0])}_kw?od=80"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = ctx.new_page()
        resp = page.goto(warm, wait_until="domcontentloaded", timeout=30000)
        status = resp.status if resp else None
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text(timeout=5000)[:3000]
        if status != 200 or ROADS[0] not in body:
            raise RuntimeError(f"Yongching browser warmup failed: HTTP {status}")

        api_roads = page.evaluate(JS, {"roads":ROADS, "area":AREA})
        browser.close()

    road_reports = []
    total_api_only = total_dom_only = total_field_mismatch = 0
    for ar in api_roads:
        road = ar["road"]
        road_key = "板橋區" + road
        api_map = {str(x["id"]): x for x in ar.get("listings") or []}
        dom_map = dom_by_road.get(road_key, {})

        api_ids = set(api_map)
        dom_ids = set(dom_map)
        api_only = sorted(api_ids - dom_ids)
        dom_only = sorted(dom_ids - api_ids)

        mismatches = []
        matched = sorted(api_ids & dom_ids)
        for cid in matched:
            a = api_map[cid]
            d = dom_map[cid]
            diffs = {}

            ap, dp = nnum(a.get("price")), nnum(d.get("price"))
            if ap is not None and dp is not None and abs(ap-dp) > 0.001:
                diffs["price"] = {"api":a.get("price"), "dom":d.get("price")}

            aa, da = nnum(a.get("area")), nnum(d.get("area"))
            if aa is not None and da is not None and abs(aa-da) > 0.011:
                diffs["area"] = {"api":a.get("area"), "dom":d.get("area")}

            af = norm_floor_from_api(a.get("floorInfo"))
            df = d.get("floor")
            if af and df and af != df:
                diffs["floor"] = {"api":af, "dom":df}

            at = str(a.get("title") or "").strip()
            dt = str(d.get("title") or "").strip()
            if at and dt and at != dt:
                diffs["title"] = {"api":at, "dom":dt}

            api_pat = compact_pattern_api(a.get("patternInfo"))
            dom_pat = parse_pattern_from_dom(d.get("rawText") or d.get("text"))
            if api_pat and dom_pat and api_pat != dom_pat:
                diffs["pattern"] = {"api":api_pat, "dom":dom_pat}

            if diffs:
                mismatches.append({"id":cid, "diffs":diffs})

        road_reports.append({
            "road": road_key,
            "api": {
                "exactCount": len(api_map),
                "totalPages": ar.get("totalPages"),
                "apiTotalCount": ar.get("apiTotalCount"),
                "paTotalItemCount": ar.get("paTotalItemCount"),
                "rawRows": ar.get("rawRows"),
                "uniqueRows": ar.get("uniqueRows"),
            },
            "dom": {
                "exactCount": len(dom_map),
                "snapshotCount": (dom.get("roadStatus") or {}).get(road_key, {}).get("count"),
            },
            "idSetsMatch": api_ids == dom_ids,
            "apiOnlyIds": api_only,
            "domOnlyIds": dom_only,
            "fieldMismatchCount": len(mismatches),
            "fieldMismatches": mismatches,
        })
        total_api_only += len(api_only)
        total_dom_only += len(dom_only)
        total_field_mismatch += len(mismatches)

    report = {
        "domCapturedAt": dom.get("capturedAt"),
        "domListingCount": dom.get("listingCount"),
        "roadsTested": len(road_reports),
        "summary": {
            "apiOnlyIdCount": total_api_only,
            "domOnlyIdCount": total_dom_only,
            "fieldMismatchListingCount": total_field_mismatch,
            "allIdSetsMatch": total_api_only == 0 and total_dom_only == 0,
            "allComparedFieldsMatch": total_field_mismatch == 0,
        },
        "roads": road_reports,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== YUNGCHING_API_VS_DOM_REPORT ===")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
