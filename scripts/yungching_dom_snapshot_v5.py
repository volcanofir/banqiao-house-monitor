"""PREVIEW-only Yongching DOM snapshot v5.

Extends v4 so every road is collected until Yongching's rendered pager explicitly
reaches a disabled Next control. No fixed page-5 ceiling is accepted as complete.
Then v4's cross-road ID integrity sanitizer runs unchanged.
"""

import json

import yungching_dom_snapshot_v3 as v3
import yungching_dom_snapshot_v4 as v4

SNAPSHOT = v4.SNAPSHOT
MAX_PAGES = 30


def pager_meta(page):
    try:
        return page.evaluate(
            """() => {
              const items=Array.from(document.querySelectorAll('.paginationPageListItem')).map(x=>({
                text:(x.innerText||'').replace(/\s+/g,' ').trim(), cls:String(x.className||'')
              }));
              const pages=items.map(x=>Number(x.text)).filter(Number.isInteger);
              const activeRow=items.find(x=>/actived|active/i.test(x.cls));
              const next=document.querySelector('.paginationNext');
              const nextCls=String(next?.className||'');
              return {
                items, pages,
                active:activeRow&&/^\d+$/.test(activeRow.text)?Number(activeRow.text):null,
                nextPresent:!!next,
                nextDisabled:!next||/disabled/i.test(nextCls)||next?.getAttribute('aria-disabled')==='true',
              };
            }"""
        )
    except Exception:
        return {"items": [], "pages": [], "active": None, "nextPresent": False, "nextDisabled": True}


def direct_next_page(page, target):
    meta = pager_meta(page)
    current = int(meta.get("active") or 1)
    visible = {int(x) for x in (meta.get("pages") or []) if isinstance(x, int)}
    if target not in visible and not (
        target == current + 1 and meta.get("nextPresent") and not meta.get("nextDisabled")
    ):
        return {"clicked": False, "mode": "yungching-direct-pg-v5", "target": target,
                "reason": "next page not advertised"}

    before = page.url
    target_url = v4.pg_url(before, target)
    try:
        response = page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        http = response.status if response else None
        page.wait_for_timeout(1800)
        active = v3.wait_pager_active(page, target, timeout=5000)
        after = pager_meta(page)
        ok = bool(http == 200 and active and int(after.get("active") or 0) == target)
        return {
            "clicked": ok, "mode": "yungching-direct-pg-v5", "target": target,
            "http": http, "beforeUrl": before, "targetUrl": target_url,
            "finalUrl": page.url, "activeVerified": bool(active),
            "error": None if ok else "target page did not become active",
        }
    except Exception as exc:
        return {"clicked": False, "mode": "yungching-direct-pg-v5", "target": target,
                "beforeUrl": before, "targetUrl": target_url,
                "error": f"{type(exc).__name__}: {str(exc)[:220]}"}


def raw_page_evidence(page, road):
    """Return parser-independent evidence for pagination and exact-address safety."""
    address = f"新北市{road}"
    try:
        return page.evaluate(
            """(address) => {
              const bodyText=document.body?.innerText||'';
              const exactAddressTextCount=bodyText.split(address).length-1;
              const rawHouseIds=[];
              for(const a of Array.from(document.querySelectorAll('a[href]'))){
                const href=String(a.href||'');
                if(!href.includes('/house/'))continue;
                const raw=href.split('/house/')[1].split(/[/?#]/)[0];
                if(/^[0-9]+$/.test(raw))rawHouseIds.push(raw);
              }
              return {
                exactAddressTextCount,
                rawHouseIds:[...new Set(rawHouseIds)].sort(),
              };
            }""",
            address,
        )
    except Exception:
        return {"exactAddressTextCount": 0, "rawHouseIds": []}


def collect_road_all_pages(page, road):
    all_rows = {}
    load_rounds = 0
    page_rounds = 0
    anchor_count = 0
    next_clicks = []
    new_ids_by_page = {}
    raw_new_ids_by_page = {}
    raw_ids_seen = set()
    raw_exact_address_text_count = 0

    used, anchor_count = v3.base.exhaust_lazy_load(page, road, all_rows)
    load_rounds += used
    initial = pager_meta(page)
    current = int(initial.get("active") or 1)
    new_ids_by_page[str(current)] = sorted(all_rows)

    evidence = raw_page_evidence(page, road)
    page_raw_ids = set(evidence.get("rawHouseIds") or [])
    raw_ids_seen.update(page_raw_ids)
    raw_new_ids_by_page[str(current)] = sorted(page_raw_ids)
    raw_exact_address_text_count += int(evidence.get("exactAddressTextCount") or 0)

    highest_advertised = max(initial.get("pages") or [current])
    exhausted = bool(initial.get("nextDisabled"))
    error = None

    while not exhausted and page_rounds < MAX_PAGES - 1:
        meta = pager_meta(page)
        current = int(meta.get("active") or current)
        pages = sorted({int(x) for x in (meta.get("pages") or []) if isinstance(x, int)})
        if pages:
            highest_advertised = max(highest_advertised, max(pages))
        future = [x for x in pages if x > current]
        target = min(future) if future else current + 1
        if target > MAX_PAGES:
            error = f"page safety cap {MAX_PAGES} reached"
            break

        before_ids = set(all_rows)
        before_raw_ids = set(raw_ids_seen)
        action = direct_next_page(page, target)
        next_clicks.append(action)
        if not action.get("clicked"):
            error = action.get("error") or action.get("reason") or f"failed page {target}"
            break

        page_rounds += 1
        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(300)
        used, anchor_count = v3.base.exhaust_lazy_load(page, road, all_rows, rounds=6)
        load_rounds += used
        after = pager_meta(page)
        if int(after.get("active") or 0) != target:
            error = f"page {target} active verification failed"
            break

        new_ids = sorted(set(all_rows) - before_ids)
        new_ids_by_page[str(target)] = new_ids

        evidence = raw_page_evidence(page, road)
        page_raw_ids = set(evidence.get("rawHouseIds") or [])
        raw_new_ids = sorted(page_raw_ids - before_raw_ids)
        raw_ids_seen.update(page_raw_ids)
        raw_new_ids_by_page[str(target)] = raw_new_ids
        raw_exact_address_text_count += int(evidence.get("exactAddressTextCount") or 0)
        if not raw_new_ids:
            error = f"page {target} produced no new raw house IDs"
            break

        after_pages = [int(x) for x in (after.get("pages") or []) if isinstance(x, int)]
        if after_pages:
            highest_advertised = max(highest_advertised, max(after_pages))
        current = target
        exhausted = bool(after.get("nextDisabled"))

    if not exhausted and page_rounds >= MAX_PAGES - 1 and not error:
        error = f"pagination did not exhaust before page {MAX_PAGES}"

    rows, anchor_count = v3.base.collect_current(page, road)
    all_rows.update(rows)
    final = pager_meta(page)
    final_active = int(final.get("active") or current)
    expected = bool(highest_advertised > 1 or initial.get("nextPresent") and not initial.get("nextDisabled"))
    complete = bool(exhausted and not error)

    return all_rows, {
        "loadRounds": load_rounds,
        "pageRounds": page_rounds,
        "nextClicks": next_clicks,
        "anchorCount": anchor_count,
        "controls": v3.base.page_controls(page),
        "paginationExpected": expected,
        "paginationActivePage": final_active,
        "paginationHighestAdvertisedPage": highest_advertised,
        "paginationLastPage": final_active if exhausted else None,
        "paginationExhausted": bool(exhausted),
        "paginationCompleteAllPages": complete,
        "paginationPageNewIds": new_ids_by_page,
        "paginationPageRawNewIds": raw_new_ids_by_page,
        "rawHouseIdCount": len(raw_ids_seen),
        "rawExactAddressTextCount": raw_exact_address_text_count,
        "paginationError": error,
    }

def enforce_all_pages():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for road, status in (payload.get("roadStatus") or {}).items():
        complete = status.get("paginationCompleteAllPages") is True
        status["paginationComplete"] = complete
        if not complete:
            status["available"] = False
            status["paginationIncomplete"] = True
            status["error"] = status.get("paginationError") or "未證實已抓至永慶最後一頁"
    payload["availableRoads"] = [r for r, st in (payload.get("roadStatus") or {}).items() if st.get("available")]
    payload["paginationGuard"] = True
    payload["paginationGuardVersion"] = "all-pages-v5"
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    v3.base.collect_road = collect_road_all_pages
    # v4.main performs the one and only ID sanitizer pass, preserving the original
    # before/after evidence (e.g. 88 -> 81) in idIntegrityGuard.
    v4.main()
    enforce_all_pages()


if __name__ == "__main__":
    main()
