"""One-off, read-only 591 wareList identity and grouping dry-run.

Read public initial-search Nuxt state for seven roads (bounded 12 pages).
Compare with *flattened* historical 591 mergedListingIds, and use the
production clustering and price identity functions in memory.

Never publish or write production files. No external detail/404 requests.
No listing IDs, addresses, prices, tokens or record bodies are logged.
Outputs aggregate, potentially tentative comparison metrics only.
"""
import asyncio
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

import dedupe_listings_v2 as dedupe
import track_price_changes as price_tracking
import monitor_pages as core
import monitor_591_web_fallback as web
from diagnose_591_warelist_integrity import ROADS, HOME, SEARCH, UA, EXTRACT, normalize

MAX_PAGES_PER_ROAD = 10


def historical():
    state = json.loads(Path("docs/data/listings.json").read_text(encoding="utf-8"))
    parents = [x for x in state.get("listings", []) if x.get("source") == "591"]
    members = dedupe.flatten_591(parents)
    by_id = {str(x["id"]): x for x in members if x.get("id")}
    active_parents = [x for x in parents if x.get("active", True)]
    active_member_ids = {str(x["id"]) for x in members if x.get("active", True)}
    print(
        f"BASELINE grouped_total={len(parents)} grouped_active={len(active_parents)} "
        f"flattened_unique={len(by_id)} flattened_active={len(active_member_ids)} "
        f"flattened_inactive={len(by_id)-len(active_member_ids)} "
        f"run_status={(state.get('runs',{}).get('591') or {}).get('status')}"
    )
    return parents, active_parents, by_id, active_member_ids


async def fetch_current(page):
    out = {}
    stats = Counter()
    for road, streetid in ROADS.items():
        keyword=road.replace("板橋區", "")
        total=None
        page_n=0
        ids=set()
        rows=[]
        drop=Counter()
        failure=None
        for p in range(MAX_PAGES_PER_ROAD):
            offset=p*30
            query={
                "keywords":keyword,"regionid":"3","section":"26",
                "streetid":streetid,"firstRow":str(offset),"page":str(p+1),
                "shType":"list","itm_source":"main","itm_medium":"home",
                "itm_campaign":"prime_position","itm_content":"sale","type":"2",
            }
            try:
                response=await page.goto(SEARCH+"?"+urlencode(query),wait_until="domcontentloaded",timeout=23000)
                if response is None or response.status!=200:
                    failure=f"http_{response.status if response else 'none'}_page_{p+1}"
                    break
                payload=await page.evaluate(EXTRACT)
                source_rows=payload.get("rows")
                new_total=payload.get("total")
                if (not isinstance(source_rows,list)
                    or not isinstance(new_total,int)
                    or new_total<1 or new_total>3000):
                    failure=f"invalid_response_page_{p+1}"
                    break
                if total is None:
                    total=new_total
                    if math.ceil(total/30)>MAX_PAGES_PER_ROAD:
                        failure="page_cap_exceeded"
                        break
                elif new_total!=total:
                    failure=f"total_drift_page_{p+1}"
                    break
                if not (payload.get("firstRow")==str(offset)
                    and payload.get("streetid")==streetid
                    and payload.get("section")=="26"
                    and normalize(payload.get("keywords"))==keyword):
                    failure=f"query_mismatch_page_{p+1}"
                    break
            except Exception as e:
                failure=f"{type(e).__name__}_page_{p+1}"
                break
            page_n+=1
            for x in source_rows:
                drop["raw"]+=1
                if x.get("is_newhouse") or str(x.get("type") or "")=="8":
                    drop["newhouse_excluded"]+=1
                    continue
                norm=web.normalize_web_sale_item(x)
                if norm is None:
                    drop["invalid_location_or_missing_fields"]+=1
                    continue
                clean, _=core.parse_591_api_payload({"data":[norm]}, road)
                if not clean:
                    drop["not_monitor_road"]+=1
                    continue
                item=clean[0]
                if item["id"] in ids:
                    drop["duplicate_id"]+=1
                    continue
                ids.add(item["id"])
                rows.append(item)
                if item.get("price") is None: drop["missing_price"]+=1
                if item.get("size") is None: drop["missing_size"]+=1
                if item.get("postTime") is None: drop["missing_posttime"]+=1
            if (p+1)*30 >= total:
                break
        expected=math.ceil(total/30) if total else None
        complete=(failure is None and expected==page_n
                  and len(rows)>0 and not (
                      drop["missing_price"] or drop["missing_size"]
                      or drop["missing_posttime"]))
        print(
            f"ROAD road={keyword} page_count={page_n}/{expected} "
            f"source_total={total} original_rows={drop['raw']} "
            f"normalized_unique={len(rows)} not_road={drop['not_monitor_road']} "
            f"invalid_fields={drop['invalid_location_or_missing_fields']} "
            f"excluded_newhouse={drop['newhouse_excluded']} "
            f"duplicate_id={drop['duplicate_id']} "
            f"missing_price={drop['missing_price']} missing_size={drop['missing_size']} "
            f"missing_posttime={drop['missing_posttime']} "
            f"complete_candidate={complete} failure={failure or 'none'}"
        )
        out[road]=rows if complete else None
        stats["roads_ok"]+=int(complete)
        stats["total"]+=total or 0
        stats["raw"]+=drop["raw"]
        stats["normalized"]+=len(rows)
        await asyncio.sleep(1.0)
    return out,stats


def compare(current, old_parents, old_active, old_by_id, old_active_ids):
    rows=[x for road_rows in current.values() for x in road_rows]
    current_by_id={x["id"]:x for x in rows}
    if len(current_by_id)!=len(rows):
        print(f"WARNING cross_road_duplicate_ids={len(rows)-len(current_by_id)}")
    ids=set(current_by_id)
    old_ids=set(old_by_id)
    exact_active=ids & old_active_ids
    exact_inactive=ids & (old_ids-old_active_ids)
    unseen=ids-old_ids
    price_changes_same_id=0
    for item_id in exact_active | exact_inactive:
        previous=old_by_id[item_id]
        newer=current_by_id[item_id]
        p_old=price_tracking.number(previous.get("price"))
        p_new=price_tracking.number(newer.get("price"))
        if p_old is not None and p_new is not None and abs(p_new-p_old)>=.1:
            price_changes_same_id+=1
    print(
        f"EXACT_ID curr_unique={len(ids)} old_unique={len(old_ids)} "
        f"old_active_ids={len(old_active_ids)} exact_active={len(exact_active)} "
        f"exact_inactive={len(exact_inactive)} unseen_id={len(unseen)} "
        f"same_id_price_different={price_changes_same_id} "
        f"old_active_not_seen_now={len(old_active_ids-ids)} "
        f"NOT_DELISTINGS=True"
    )
    # Identity match of new listing ID against old *property groups*.
    # Matching here is heuristic and must not be treated as confirmed.
    candidate_stats=Counter()
    for new_id in unseen:
        item=current_by_id[new_id]
        matches=[
            old for old in old_active
            if price_tracking.same_property(item,old)
        ]
        if len(matches)==0:
            candidate_stats["no_strong_property_match"]+=1
        elif len(matches)==1:
            candidate_stats["one_strong_property_match"]+=1
        else:
            candidate_stats["multiple_property_matches"]+=1
    print(
        "NEW_ID_STRONG_MATCH " +
        " ".join(f"{key}={candidate_stats[key]}" for key in (
            "one_strong_property_match",
            "multiple_property_matches",
            "no_strong_property_match",
        ))+
        " UNCONFIRMED_NEW_PROPERTIES=True"
    )
    # Production same-property clustering on a current-only snapshot in memory.
    current_grouped,removed_current,raw_current=dedupe.dedupe(rows)
    current_groups=[x for x in current_grouped if x.get("source")=="591" and x.get("active",True)]
    prior_groups=[x for x in old_active]
    group_match=Counter()
    effective_price_diffs=0
    for group in current_groups:
        matches=[old for old in prior_groups if price_tracking.same_property(group,old)]
        if not matches:
            group_match["unmatched"]+=1
        elif len(matches)==1:
            group_match["single"]+=1
            p0=price_tracking.effective_price(matches[0])
            p1=price_tracking.effective_price(group)
            if p0 is not None and p1 is not None and abs(p0-p1)>=.1:
                effective_price_diffs+=1
        else:
            group_match["ambiguous"]+=1
    print(
        f"DRYRUN_CURRENT_ONLY input_records={raw_current} "
        f"grouped_properties={len(current_groups)} merged_duplicates={removed_current} "
        f"matched_one_old_group={group_match['single']} "
        f"matched_multiple_old_groups={group_match['ambiguous']} "
        f"no_old_group_match={group_match['unmatched']} "
        f"old_group_effective_price_differences={effective_price_diffs}"
    )
    # Literal old+new in-memory merge using the deployed clustering algorithm.
    # Active old members persist in this simulation; this is NOT a valid
    # updated snapshot or an instruction to set the old records as active.
    combined_groups,combined_removed,combined_raw=dedupe.dedupe(old_parents+rows)
    combined_active=sum(x.get("source")=="591" and x.get("active",True) for x in combined_groups)
    print(
        f"DRYRUN_WITH_HISTORY old_grouped={len(old_parents)} "
        f"combined_unique_members={combined_raw} "
        f"result_groups={len(combined_groups)} "
        f"combined_active_groups={combined_active} "
        f"combined_merged_count={combined_removed} "
        f"WARN_old_active_flags_are_carried_forward=True"
    )
    # The current production merge_source has parent-level identities only.
    # Count its theoretical 'new ID' logic WITHOUT calling network-backed
    # definitely_inactive and WITHOUT writing any state.
    parent_ids={x["id"] for x in old_parents}
    print(
        f"SAFETY production_parent_id_not_found={len(ids-parent_ids)} "
        f"actual_unseen_id={len(unseen)} "
        f"potential_false_new_id_events={len((ids-parent_ids)&old_ids)} "
        f"PRODUCTION_AUTO_PUBLISH_SAFE=False"
    )


async def main():
    old_parents,old_active,old_by_id,old_active_ids=historical()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True,
                                       args=["--disable-dev-shm-usage"])
        try:
            context=await browser.new_context(
                user_agent=UA,viewport={"width":390,"height":844},
                is_mobile=True,has_touch=True,
                locale="zh-TW",timezone_id="Asia/Taipei"
            )
            try:
                page=await context.new_page()
                home=await page.goto(HOME,wait_until="domcontentloaded",timeout=25000)
                print(f"HOME_HTTP {home.status if home else 'none'}")
                current,stats=await fetch_current(page)
            finally:
                await context.close()
        finally:
            await browser.close()
    print(
        f"FETCH_SUMMARY roads_complete={stats['roads_ok']}/{len(ROADS)} "
        f"raw={stats['raw']} normalized={stats['normalized']}"
    )
    if (stats["roads_ok"]!=len(ROADS)
        or any(x is None for x in current.values())):
        print("ABORT incomplete input; grouping and status comparison deliberately skipped")
        return
    compare(current,old_parents,old_active,old_by_id,old_active_ids)
    print("READ_ONLY no listing data written, no production state changed, no delistings published")


if __name__=="__main__":
    asyncio.run(main())
