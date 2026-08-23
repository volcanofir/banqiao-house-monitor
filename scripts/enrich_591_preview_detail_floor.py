"""Enrich Preview-only 591 raw members from the public 591 detail JSON endpoint.

Run after sinyi_preview_floor_enrich.py has built scheme-a-external-enriched.json.
This script never writes docs/data/listings.json. It targets the current medium-risk
591 member IDs and stores only public identity fields needed for safer grouping.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

EXTERNAL = Path("docs/preview/scheme-a-external-enriched.json")
WEAK = Path("docs/preview/scheme-a-weak-group-audit.json")
OUT = Path("docs/preview/591-detail-floor-enrichment.json")
V9_EXTERNAL = Path("docs/preview/scheme-a-external-v9.json")

MAX_CONCURRENCY = 8


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_floor(raw):
    text = str(raw or "").strip().upper().replace("Ｆ", "F")
    m = re.fullmatch(r"(\d{1,2})F\s*/\s*(\d{1,2})F", text)
    if not m:
        return None
    floor, total = int(m.group(1)), int(m.group(2))
    if 1 <= floor <= total <= 99:
        return f"{floor}/{total}樓"
    return None


def medium_ids():
    audit = json.loads(WEAK.read_text(encoding="utf-8"))
    ids = set()
    groups = []
    for g in audit.get("groups") or []:
        if g.get("risk") != "medium":
            continue
        groups.append(g.get("groupId"))
        for ex in g.get("weakExamples") or []:
            for key in ("aId", "bId"):
                rid = str(ex.get(key) or "")
                if rid.startswith("591:"):
                    ids.add(rid.split(":", 1)[1])
    # weakExamples are capped, so also recover every member from the external copy
    # by matching the current canonical group data if available.
    try:
        gap = json.loads(Path("docs/preview/company-gap.json").read_text(encoding="utf-8"))
        wanted = set(groups)
        for g in gap.get("propertyGroups") or []:
            if g.get("groupId") not in wanted:
                continue
            for src in g.get("sourceListings") or []:
                if src.get("source") != "591":
                    continue
                for x in (src.get("mergedListings") or [src]):
                    rid = str(x.get("id") or "")
                    if rid.startswith("591:"):
                        ids.add(rid.split(":", 1)[1])
    except Exception:
        pass
    return sorted(ids), groups


def all_591_ids_from_external(state):
    ids=set()
    for x in state.get("listings") or []:
        if x.get("source") != "591":
            continue
        candidates=x.get("mergedListings") or [x]
        for m in candidates:
            rid=str(m.get("id") or x.get("id") or "")
            if rid.startswith("591:"):
                ids.add(rid.split(":",1)[1])
    return ids


def mutate_detail_url(template, pid):
    p=urlparse(template)
    q=dict(parse_qsl(p.query,keep_blank_values=True))
    q["id"] = f"S{pid}"
    return urlunparse(p._replace(query=urlencode(q)))


def public_detail(data):
    if not isinstance(data, dict):
        return None
    raw_floor=data.get("floor")
    floor=normalize_floor(raw_floor)
    return {
        "floor": floor,
        "rawFloor": raw_floor,
        "originFloor": data.get("origin_floor"),
        "layout": data.get("layout"),
        "layout2": data.get("layout2"),
        "listLayout": data.get("listLayout"),
        "room": data.get("room"),
        "community": data.get("community"),
        "communityId": data.get("new_community_id") or data.get("community_id"),
        "kind": data.get("kind"),
        "houseAge": data.get("houseage"),
        "parkingKind": data.get("parking_kind"),
    }


async def bootstrap_template(context, pid):
    page=await context.new_page()
    found=asyncio.get_running_loop().create_future()
    async def inspect(resp):
        if "/v1/touch/sale/detail" not in resp.url or resp.status != 200 or found.done():
            return
        try:
            payload=await resp.json()
            if isinstance(payload,dict) and isinstance(payload.get("data"),dict):
                found.set_result((resp.url,payload))
        except Exception:
            pass
    def on_response(resp): asyncio.create_task(inspect(resp))
    page.on("response",on_response)
    try:
        await page.goto(f"https://m.591.com.tw/v2/sale/{pid}",wait_until="domcontentloaded",timeout=45000)
        return await asyncio.wait_for(asyncio.shield(found),timeout=12)
    finally:
        await page.close()


async def fetch_one(context, sem, template, pid):
    async with sem:
        try:
            url=mutate_detail_url(template,pid)
            resp=await context.request.get(url,headers={"Accept":"application/json, text/plain, */*","Referer":f"https://m.591.com.tw/v2/sale/{pid}","Origin":"https://m.591.com.tw"},timeout=15000)
            if resp.status != 200:
                return pid,None,f"HTTP {resp.status}"
            payload=await resp.json()
            data=payload.get("data") if isinstance(payload,dict) else None
            rec=public_detail(data)
            if not rec:
                return pid,None,"detail data missing"
            return pid,rec,None
        except Exception as exc:
            return pid,None,f"{type(exc).__name__}: {exc}"


def apply_to_external(state, details):
    applied=0
    with_floor=0
    seen=set()
    raw_rows=[]
    non_591=[]

    for top in state.get("listings") or []:
        if top.get("source") != "591":
            non_591.append(top)
            continue
        candidates=top.get("mergedListings") or [top]
        for src in candidates:
            row=dict(src)
            row.setdefault("source","591")
            row.setdefault("road",top.get("road"))
            row.setdefault("active",top.get("active",True))
            row.setdefault("firstSeenAt",top.get("firstSeenAt"))
            row.setdefault("lastSeenAt",top.get("lastSeenAt"))
            rid=str(row.get("id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            pid=rid.split(":",1)[1] if rid.startswith("591:") else ""
            rec=details.get(pid)
            if rec:
                applied += 1
                row["floorSourceMode"]="591_public_detail_api"
                row["structuredFloorRaw"]=rec.get("rawFloor")
                row["structuredFloor"]=rec.get("floor")
                if rec.get("floor"):
                    row["floor"]=rec.get("floor")
                    with_floor += 1
                row["structuredLayout"]=rec.get("layout2") or rec.get("layout") or rec.get("listLayout")
                row["structuredRoom"]=rec.get("room")
                row["structuredCommunityId"]=rec.get("communityId")
                row["structuredCommunity"]=rec.get("community")
            for key in ("mergedListingCount","mergedDuplicateCount","mergedActiveListingCount","mergedListingIds","mergedListings"):
                row.pop(key,None)
            raw_rows.append(row)

    out=dict(state)
    out["listings"]=non_591+raw_rows
    out.setdefault("previewEnrichment",{})["raw591ReexpandedForFloorAwareRegroup"]={
        "raw591Count":len(raw_rows),"detailAppliedCount":applied,"withStructuredFloorCount":with_floor,
    }
    return out,len(raw_rows),applied,with_floor


async def main_async():
    state=json.loads(EXTERNAL.read_text(encoding="utf-8"))
    target, groups=medium_ids()
    available=all_591_ids_from_external(state)
    target=[x for x in target if x in available]
    if not target:
        raise RuntimeError("No current medium-risk 591 IDs found")

    details={}; errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True,args=["--disable-dev-shm-usage"])
        context=await browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei",viewport={"width":390,"height":844},is_mobile=True,has_touch=True,user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
        try:
            template, first_payload=await bootstrap_template(context,target[0])
            first_data=first_payload.get("data") or {}
            details[target[0]]=public_detail(first_data)
            sem=asyncio.Semaphore(MAX_CONCURRENCY)
            results=await asyncio.gather(*(fetch_one(context,sem,template,pid) for pid in target[1:]))
            for pid,rec,error in results:
                if rec: details[pid]=rec
                else: errors.append({"id":pid,"error":error})
        finally:
            await context.close(); await browser.close()

    v9_state,raw_count,applied,with_floor=apply_to_external(state,details)
    V9_EXTERNAL.write_text(json.dumps(v9_state,ensure_ascii=False,indent=2),encoding="utf-8")
    report={
        "generatedAt":now_iso(),"previewOnly":True,"source":"591 public detail JSON /v1/touch/sale/detail via Surfshark + Chromium session",
        "targetMediumGroupCount":len(groups),"targetIdCount":len(target),"detailSuccessCount":len(details),"detailErrorCount":len(errors),
        "withStructuredFloorCount":sum(1 for x in details.values() if x and x.get("floor")),"errors":errors,
        "raw591ReexpandedCount":raw_count,"detailAppliedToV9Count":applied,"withFloorAppliedToV9Count":with_floor,
        "complete":len(details)==len(target) and not errors,
        "details":details,
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("targetMediumGroupCount","targetIdCount","detailSuccessCount","detailErrorCount","withStructuredFloorCount","raw591ReexpandedCount","complete")},ensure_ascii=False))


if __name__=="__main__": asyncio.run(main_async())
