"""Read-only seven-road sale HTML integrity diagnostic.

One-time bounded verification of Nuxt initial state from normal public search
pages. In-memory aggregate comparison with the canonical historic 591 baseline.
Never writes listing snapshots, history, delistings or preview; never logs IDs,
addresses, prices, cookies or page bodies. Fail closed on incomplete pages.
"""
import asyncio
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

ROADS = {
    "板橋區中山路二段": "27507",
    "板橋區三民路二段": "27485",
    "板橋區光復街": "27550",
    "板橋區萬安街": "27630",
    "板橋區林森街": "27574",
    "板橋區三民路一段": "27484",
    "板橋區翠華街": "27644",
}
HOME = "https://m.591.com.tw/v2/"
SEARCH = "https://sale.591.com.tw/"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
MAX_PAGES_PER_ROAD = 10
# Get field values only in browser->Python memory. Never print these raw rows.
EXTRACT = """() => {
    const unref=x=>x?.__v_isRef?x.value:x;
    const s=window.__NUXT__?.pinia?.['sale-list'];
    const rows=unref(s?.wareList);
    const total=unref(s?.wareTotal);
    const p=unref(s?.searchParams);
    return {
        total:typeof total==="number"?total:null,
        firstRow:p?.firstRow===undefined?null:String(p.firstRow),
        streetid:p?.streetid===undefined?null:String(p.streetid),
        keywords:typeof p?.keywords==="string"?p.keywords:null,
        section:p?.section===undefined?null:String(p.section),
        rows:Array.isArray(rows)?rows.map(x=>({
            houseid:x.houseid??x.post_id??null,
            address:x.address??x.address_new??null,
            price:x.price??null,
            area:x.area??null,
            posttime:x.posttime??null,
            title:x.title??null,
            region_name:x.region_name??null,
            section_name:x.section_name??null,
            section_id:x.section_id??null,
            type:x.type??null,
            isvip:x.isvip??null,
            m_recom:x.m_recom??null,
            bid_rank:x.bid_rank??null,
            is_newhouse:x.is_newhouse??null
        })):null
    }
}"""


def normalize(text):
    s = re.sub(r"\s+", "", str(text or "")).replace("臺", "台")
    return (s.replace("中山路2段", "中山路二段")
             .replace("三民路1段", "三民路一段")
             .replace("三民路2段", "三民路二段"))


def price_value(value):
    if value is None or value == "":
        return None
    try:
        p = float(str(value).replace(",", "").replace("萬", ""))
        if p >= 100000:
            p /= 10000
        return p
    except (ValueError, TypeError):
        return None


def baseline():
    obj = json.loads(Path("docs/data/listings.json").read_text(encoding="utf-8"))
    result = {}
    for row in obj.get("listings", []):
        if row.get("source") != "591" or row.get("active") is False:
            continue
        result.setdefault(row.get("road"), {})[str(row.get("houseId"))] = row
    return obj.get("runs", {}).get("591", {}), result


async def collect_road(page, road, streetid, old):
    keyword = road.replace("板橋區", "")
    first_total = None
    counts = Counter()
    seen_ids = {}
    all_pages = 0
    first_row_keys_ok = True
    totals_stable = True
    failure = None
    duplicate_count = 0
    for pn in range(MAX_PAGES_PER_ROAD):
        offset = pn * 30
        params = {
            "keywords": keyword, "regionid": "3", "section": "26",
            "streetid": streetid, "firstRow": str(offset), "page": str(pn+1),
            "shType": "list", "itm_source": "main", "itm_medium": "home",
            "itm_campaign": "prime_position", "itm_content": "sale", "type": "2",
        }
        try:
            response=await page.goto(SEARCH+"?"+urlencode(params),wait_until="domcontentloaded",timeout=23000)
            if not response or response.status!=200:
                failure=f"HTTP_{response.status if response else 'none'}_page_{pn+1}"
                break
            page_data=await page.evaluate(EXTRACT)
        except Exception as exc:
            failure=f"{type(exc).__name__}_page_{pn+1}"
            break
        rows=page_data.get("rows")
        total=page_data.get("total")
        if not isinstance(rows,list) or not isinstance(total,int) or total<1 or total>5000:
            failure=f"invalid_initial_state_page_{pn+1}"
            break
        if first_total is None:
            first_total=total
            if math.ceil(total/30)>MAX_PAGES_PER_ROAD:
                failure="expected_pages_exceed_cap"
                break
        elif total!=first_total:
            totals_stable=False
        if (page_data.get("firstRow")!=str(offset) or
            page_data.get("streetid")!=streetid or
            page_data.get("section")!="26" or
            normalize(page_data.get("keywords"))!=keyword):
            first_row_keys_ok=False
            failure=f"search_state_mismatch_page_{pn+1}"
            break
        all_pages += 1
        counts["raw"] += len(rows)
        for x in rows:
            counts["item"] += 1
            houseid=str(x.get("houseid") or "").strip()
            if not houseid.isdigit():
                counts["id_missing"] += 1
                continue
            address=normalize(x.get("address"))
            if (normalize(x.get("region_name")) not in ("", "新北市") or
                normalize(x.get("section_name")) not in ("", "板橋區") or
                str(x.get("section_id") or "") not in ("", "26")):
                counts["other_district"] += 1
                continue
            if keyword not in address:
                counts["other_road"] += 1
                continue
            counts["road_match"] += 1
            if houseid in seen_ids:
                duplicate_count += 1
                continue
            seen_ids[houseid]=x
            if not x.get("title"):
                counts["missing_title"] += 1
            if x.get("posttime") in (None,""):
                counts["missing_posttime"] += 1
            if x.get("area") in (None,""):
                counts["missing_area"] += 1
            if price_value(x.get("price")) is None:
                counts["unparsable_price"] += 1
            if houseid in old:
                counts["old_active_overlap"] += 1
                prev_price=price_value(old[houseid].get("price"))
                cur_price=price_value(x.get("price"))
                if prev_price is not None and cur_price is not None and abs(prev_price-cur_price)>0.009:
                    counts["old_id_price_difference"] += 1
            else:
                counts["not_in_old_active"] += 1
            for flag in ("isvip","m_recom","bid_rank"):
                if x.get(flag) not in (None,False,0,"0",""):
                    counts["flag_"+flag] += 1
        if offset+30>=first_total:
            break
    expected=math.ceil(first_total/30) if first_total is not None else None
    complete=(failure is None and expected is not None and all_pages==expected
              and first_row_keys_ok and totals_stable
              and len(seen_ids)>0 and counts["unparsable_price"]==0)
    print(
        f"ROAD_INTEGRITY road={keyword} total={first_total} pages={all_pages}/{expected} "
        f"raw={counts['raw']} road_rows={counts['road_match']} unique_on_road={len(seen_ids)} "
        f"cross_page_duplicates={duplicate_count} other_road={counts['other_road']} "
        f"other_district={counts['other_district']} invalid_id={counts['id_missing']} "
        f"missing_title={counts['missing_title']} missing_area={counts['missing_area']} "
        f"missing_posttime={counts['missing_posttime']} unparsable_price={counts['unparsable_price']} "
        f"old_active={len(old)} overlap={counts['old_active_overlap']} "
        f"not_in_old_active={counts['not_in_old_active']} old_id_price_diff={counts['old_id_price_difference']} "
        f"vip_flag={counts['flag_isvip']} recom_flag={counts['flag_m_recom']} "
        f"bid_rank_flag={counts['flag_bid_rank']} complete_candidate={complete} "
        f"stable_total={totals_stable} param_match={first_row_keys_ok} failure={failure or 'none'}"
    )
    # These figures are NOT published. Record counts and transient IDs can change.
    return {"road":keyword,"complete_candidate":complete,"seen":len(seen_ids),
            "expected":expected,"pages":all_pages,"baseline":len(old),"overlap":counts["old_active_overlap"]}


async def main():
    old_run, old_by_road=baseline()
    print(f"BASELINE stored_591_status={old_run.get('status')} "
          f"stored_active_591={sum(len(x) for x in old_by_road.values())}")
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True,args=["--disable-dev-shm-usage"])
        try:
            context=await browser.new_context(
                user_agent=UA,viewport={"width":390,"height":844},
                is_mobile=True,has_touch=True,locale="zh-TW",timezone_id="Asia/Taipei")
            try:
                page=await context.new_page()
                response=await page.goto(HOME,wait_until="domcontentloaded",timeout=23000)
                print(f"HOME http={response.status if response else 'none'}")
                outputs=[]
                for road,streetid in ROADS.items():
                    outputs.append(await collect_road(page,road,streetid,old_by_road.get(road,{})))
                    await asyncio.sleep(1)
                print(
                    f"AGGREGATE roads={len(outputs)} complete_candidate="
                    f"{sum(x['complete_candidate'] for x in outputs)} "
                    f"current_unique_on_road_sum={sum(x['seen'] for x in outputs)} "
                    f"history_overlap_sum={sum(x['overlap'] for x in outputs)} "
                    f"active_baseline_sum={sum(x['baseline'] for x in outputs)} "
                    f"NOT_A_VERIFIED_PUBLISHABLE_SNAPSHOT=True"
                )
                print("READ_ONLY no listing records, IDs, addresses, cookies or tokens printed; no production files changed")
            finally:
                await context.close()
        finally:
            await browser.close()


if __name__=="__main__":
    asyncio.run(main())
