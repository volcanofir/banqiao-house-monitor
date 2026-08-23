"""Enrich Preview-only 591 medium-risk members from the public detail JSON endpoint.

Only 591 top-level rows belonging to the current medium-risk groups are expanded back
to raw members; every other 591 group stays exactly as v8 supplied it. Detail fields
come from fresh 591 mobile pages/XHR inside Surfshark + Chromium. Production data is
never modified.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

EXTERNAL=Path("docs/preview/scheme-a-external-enriched.json")
WEAK=Path("docs/preview/scheme-a-weak-group-audit.json")
OUT=Path("docs/preview/591-detail-floor-enrichment.json")
V9_EXTERNAL=Path("docs/preview/scheme-a-external-v9.json")
MAX_CONCURRENCY=8


def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_floor(raw):
    text=str(raw or "").strip().upper().replace("Ｆ","F").replace("～","~").replace("-","~")
    m=re.fullmatch(r"(\d{1,2})F(?:\s*~\s*(\d{1,2})F)?\s*/\s*(\d{1,2})F",text)
    if not m: return None
    lo,hi,total=int(m.group(1)),int(m.group(2) or m.group(1)),int(m.group(3))
    if not (1 <= lo <= hi <= total <= 99): return None
    return f"{lo}/{total}樓" if lo==hi else f"{lo}~{hi}/{total}樓"


def medium_ids():
    audit=json.loads(WEAK.read_text(encoding="utf-8")); ids=set(); groups=[]
    for g in audit.get("groups") or []:
        if g.get("risk")!="medium": continue
        groups.append(g.get("groupId"))
        for ex in g.get("weakExamples") or []:
            for key in ("aId","bId"):
                rid=str(ex.get(key) or "")
                if rid.startswith("591:"): ids.add(rid.split(":",1)[1])
    try:
        gap=json.loads(Path("docs/preview/company-gap.json").read_text(encoding="utf-8")); wanted=set(groups)
        for g in gap.get("propertyGroups") or []:
            if g.get("groupId") not in wanted: continue
            for src in g.get("sourceListings") or []:
                if src.get("source")!="591": continue
                for x in (src.get("mergedListings") or [src]):
                    rid=str(x.get("id") or "")
                    if rid.startswith("591:"): ids.add(rid.split(":",1)[1])
    except Exception: pass
    return sorted(ids),groups


def all_591_ids_from_external(state):
    ids=set()
    for x in state.get("listings") or []:
        if x.get("source")!="591": continue
        for m in (x.get("mergedListings") or [x]):
            rid=str(m.get("id") or x.get("id") or "")
            if rid.startswith("591:"): ids.add(rid.split(":",1)[1])
    return ids


def mutate_detail_url(template,pid):
    p=urlparse(template); q=dict(parse_qsl(p.query,keep_blank_values=True)); q["id"]=f"S{pid}"
    return urlunparse(p._replace(query=urlencode(q)))


def public_detail(data):
    if not isinstance(data,dict): return None
    raw=data.get("floor")
    return {"floor":normalize_floor(raw),"rawFloor":raw,"originFloor":data.get("origin_floor"),
            "layout":data.get("layout"),"layout2":data.get("layout2"),"listLayout":data.get("listLayout"),
            "room":data.get("room"),"community":data.get("community"),
            "communityId":data.get("new_community_id") or data.get("community_id"),"kind":data.get("kind"),
            "houseAge":data.get("houseage"),"parkingKind":data.get("parking_kind")}


async def capture_from_page(context,pid,timeout=12):
    page=await context.new_page(); found=asyncio.get_running_loop().create_future(); tasks=[]
    async def inspect(resp):
        if "/v1/touch/sale/detail" not in resp.url or resp.status!=200 or found.done(): return
        try:
            payload=await resp.json(); data=payload.get("data") if isinstance(payload,dict) else None
            rec=public_detail(data)
            if rec and not found.done(): found.set_result((resp.url,rec,payload))
        except Exception: pass
    def on_response(resp): tasks.append(asyncio.create_task(inspect(resp)))
    page.on("response",on_response); nav_status=None; body_marker=None
    try:
        nav=await page.goto(f"https://m.591.com.tw/v2/sale/{pid}",wait_until="domcontentloaded",timeout=45000)
        nav_status=nav.status if nav else None
        try:
            url,rec,payload=await asyncio.wait_for(asyncio.shield(found),timeout=timeout)
            return {"ok":True,"url":url,"record":rec,"payload":payload,"navHttp":nav_status,"bodyMarker":None}
        except asyncio.TimeoutError:
            try:
                body=(await page.locator("body").inner_text(timeout=3000))[:3000]
                for marker in ("物件已下架","此物件已下架","刊登已結束","物件不存在","找不到物件","已成交"):
                    if marker in body: body_marker=marker; break
            except Exception: pass
            return {"ok":False,"navHttp":nav_status,"bodyMarker":body_marker}
    except Exception as exc:
        return {"ok":False,"navHttp":nav_status,"bodyMarker":body_marker,"error":f"{type(exc).__name__}: {exc}"}
    finally:
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        await page.close()


async def fetch_one(context,sem,template,pid):
    async with sem:
        try:
            resp=await context.request.get(mutate_detail_url(template,pid),headers={"Accept":"application/json, text/plain, */*","Referer":f"https://m.591.com.tw/v2/sale/{pid}","Origin":"https://m.591.com.tw"},timeout=15000)
            if resp.status==200:
                payload=await resp.json(); rec=public_detail(payload.get("data") if isinstance(payload,dict) else None)
                if rec: return pid,rec,None,"direct",None
            direct_error=f"HTTP {resp.status}" if resp.status!=200 else "detail data missing"
        except Exception as exc:
            direct_error=f"{type(exc).__name__}: {exc}"
        # Retry through the real listing page. This allows per-listing query/cookie differences.
        fallback=await capture_from_page(context,pid,timeout=10)
        if fallback.get("ok"):
            return pid,fallback.get("record"),None,"page_fallback",{"navHttp":fallback.get("navHttp")}
        return pid,None,direct_error,"failed",{"navHttp":fallback.get("navHttp"),"bodyMarker":fallback.get("bodyMarker"),"fallbackError":fallback.get("error")}


def child_pid(x):
    rid=str(x.get("id") or "")
    return rid.split(":",1)[1] if rid.startswith("591:") else ""


def enrich_row(row,top,details):
    row=dict(row); row.setdefault("source","591"); row.setdefault("road",top.get("road")); row.setdefault("active",top.get("active",True)); row.setdefault("firstSeenAt",top.get("firstSeenAt")); row.setdefault("lastSeenAt",top.get("lastSeenAt"))
    rec=details.get(child_pid(row))
    if rec:
        row["floorSourceMode"]="591_public_detail_api"; row["structuredFloorRaw"]=rec.get("rawFloor"); row["structuredFloor"]=rec.get("floor")
        if rec.get("floor"): row["floor"]=rec.get("floor")
        row["structuredLayout"]=rec.get("layout2") or rec.get("layout") or rec.get("listLayout"); row["structuredRoom"]=rec.get("room"); row["structuredCommunityId"]=rec.get("communityId"); row["structuredCommunity"]=rec.get("community")
    return row,rec


def apply_to_external(state,details,target_ids):
    out_rows=[]; seen=set(); expanded_raw=0; preserved_top=0; applied=0; with_floor=0; expanded_top=0; targets=set(target_ids)
    for top in state.get("listings") or []:
        if top.get("source")!="591": out_rows.append(top); continue
        candidates=top.get("mergedListings") or [top]; member_pids={child_pid(x) for x in candidates if child_pid(x)}
        if not (member_pids & targets): out_rows.append(top); preserved_top+=1; continue
        expanded_top+=1
        for src in candidates:
            row,rec=enrich_row(src,top,details); rid=str(row.get("id") or "")
            if not rid or rid in seen: continue
            seen.add(rid)
            for key in ("mergedListingCount","mergedDuplicateCount","mergedActiveListingCount","mergedListingIds","mergedListings"): row.pop(key,None)
            out_rows.append(row); expanded_raw+=1
            if rec:
                applied+=1
                if rec.get("floor"): with_floor+=1
    out=dict(state); out["listings"]=out_rows
    out.setdefault("previewEnrichment",{})["raw591ReexpandedForFloorAwareRegroup"]={"mediumTopLevelExpandedCount":expanded_top,"mediumRaw591Count":expanded_raw,"nonMediumTopLevelPreservedCount":preserved_top,"detailAppliedCount":applied,"withStructuredFloorCount":with_floor}
    return out,expanded_top,expanded_raw,preserved_top,applied,with_floor


async def main_async():
    state=json.loads(EXTERNAL.read_text(encoding="utf-8")); target,groups=medium_ids(); available=all_591_ids_from_external(state); target=[x for x in target if x in available]
    if not target: raise RuntimeError("No current medium-risk 591 IDs found")
    details={}; errors=[]; modes={}
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True,args=["--disable-dev-shm-usage"])
        context=await browser.new_context(locale="zh-TW",timezone_id="Asia/Taipei",viewport={"width":390,"height":844},is_mobile=True,has_touch=True,user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
        try:
            boot=await capture_from_page(context,target[0],timeout=12)
            if not boot.get("ok"): raise RuntimeError(f"cannot bootstrap 591 detail endpoint: {boot}")
            template=boot["url"]; details[target[0]]=boot["record"]; modes[target[0]]="page_bootstrap"
            sem=asyncio.Semaphore(MAX_CONCURRENCY); results=await asyncio.gather(*(fetch_one(context,sem,template,pid) for pid in target[1:]))
            for pid,rec,error,mode,meta in results:
                modes[pid]=mode
                if rec: details[pid]=rec
                else: errors.append({"id":pid,"error":error,"retry":meta})
        finally: await context.close(); await browser.close()
    v9_state,expanded_top,expanded_raw,preserved_top,applied,with_floor=apply_to_external(state,details,target); V9_EXTERNAL.write_text(json.dumps(v9_state,ensure_ascii=False,indent=2),encoding="utf-8")
    report={"generatedAt":now_iso(),"previewOnly":True,"source":"591 public detail JSON /v1/touch/sale/detail via Surfshark + Chromium session; direct request with real-page fallback",
            "targetMediumGroupCount":len(groups),"targetIdCount":len(target),"detailSuccessCount":len(details),"detailErrorCount":len(errors),"withStructuredFloorCount":sum(1 for x in details.values() if x and x.get("floor")),"errors":errors,
            "fetchModes":{"direct":sum(1 for x in modes.values() if x=="direct"),"pageFallback":sum(1 for x in modes.values() if x=="page_fallback"),"pageBootstrap":sum(1 for x in modes.values() if x=="page_bootstrap"),"failed":sum(1 for x in modes.values() if x=="failed")},
            "mediumTopLevelExpandedCount":expanded_top,"raw591ReexpandedCount":expanded_raw,"nonMediumTopLevelPreservedCount":preserved_top,"detailAppliedToV9Count":applied,"withFloorAppliedToV9Count":with_floor,"complete":len(details)==len(target) and not errors,"details":details}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("targetMediumGroupCount","targetIdCount","detailSuccessCount","detailErrorCount","withStructuredFloorCount","fetchModes","mediumTopLevelExpandedCount","raw591ReexpandedCount","nonMediumTopLevelPreservedCount","complete")},ensure_ascii=False))

if __name__=="__main__": asyncio.run(main_async())
