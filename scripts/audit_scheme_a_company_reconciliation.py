"""Audit review rows caused by one Yongching listing matching multiple external groups.

Diagnostic only. Looks for the narrow case where a standalone 591 group and a
Sinyi-primary group independently match the same unique official company listing,
with no floor conflict and close area/price. This can reveal a missed Sinyi/591
merge without changing scheme A output.
"""
import json, re
from datetime import datetime, timezone
from pathlib import Path

GAP=Path('docs/preview/company-gap.json')
OUT=Path('docs/preview/scheme-a-company-reconciliation-audit.json')

def num(v):
    m=re.search(r'\d+(?:\.\d+)?',str(v or '').replace(',',''))
    return float(m.group()) if m else None

def floors(v):
    text=str(v or '').replace('～','~'); out=set()
    for m in re.finditer(r'(\d{1,2})(?:\s*[~-]\s*(\d{1,2}))?\s*/\s*(\d{1,2})\s*樓',text):
        lo=int(m.group(1)); hi=int(m.group(2) or m.group(1)); total=int(m.group(3))
        if 1<=lo<=hi<=total<=99: out.update(range(lo,hi+1))
    if not out:
        for n in re.findall(r'(?<!\d)(\d{1,2})\s*樓',text):
            x=int(n)
            if 1<=x<=99: out.add(x)
    return out

def primary(g):
    rows=g.get('sourceListings') or []
    return rows[0] if rows else {}

def main():
    p=json.loads(GAP.read_text(encoding='utf-8'))
    groups={g.get('groupId'):g for g in p.get('propertyGroups') or []}
    comps=p.get('comparisons') or []
    by_company={}
    for c in comps:
        cand=c.get('companyCandidate') or {}
        cid=str(cand.get('id') or '')
        if cid: by_company.setdefault(cid,[]).append(c)
    cases=[]
    for cid,rows in by_company.items():
        keepers=[x for x in rows if x.get('status')=='company_match']
        reviews=[x for x in rows if x.get('status')=='review' and (x.get('matchInfo') or {}).get('companyCandidateConflict')]
        if len(keepers)!=1 or not reviews: continue
        keeper=keepers[0]; kg=groups.get(keeper.get('groupId')) or {}
        if kg.get('primarySource')!='信義房屋': continue
        kp=primary(kg); kf=floors(kp.get('floor'))
        company_floor=floors((keeper.get('companyCandidate') or {}).get('floor'))
        for r in reviews:
            rg=groups.get(r.get('groupId')) or {}; rp=primary(rg)
            if rg.get('primarySource')!='591': continue
            rf=floors(rp.get('floor')) or floors(rp.get('title'))
            ka=num(kp.get('size')); ra=num(rp.get('size'))
            kpr=num(kp.get('effectivePrice') if kp.get('effectivePrice') is not None else kp.get('price'))
            rpr=num(rp.get('effectivePrice') if rp.get('effectivePrice') is not None else rp.get('price'))
            ad=abs(ka-ra) if None not in (ka,ra) else None
            pd=abs(kpr-rpr) if None not in (kpr,rpr) else None
            floor_conflict=bool(rf and kf and rf.isdisjoint(kf)) or bool(rf and company_floor and rf.isdisjoint(company_floor))
            safe=bool(ad is not None and ad<=.12 and pd is not None and pd<=100 and not floor_conflict and company_floor and (not kf or bool(kf & company_floor)))
            cases.append({
              'companyId':cid,'keeperGroupId':keeper.get('groupId'),'reviewGroupId':r.get('groupId'),
              'sinyiId':kp.get('id'),'sinyiTitle':kp.get('title'),'sinyiArea':ka,'sinyiPrice':kpr,'sinyiFloors':sorted(kf),
              'listing591Id':rp.get('id'),'listing591Title':rp.get('title'),'listing591Area':ra,'listing591Price':rpr,'listing591Floors':sorted(rf),
              'companyTitle':(keeper.get('companyCandidate') or {}).get('title'),'companyFloors':sorted(company_floor),
              'areaDelta':None if ad is None else round(ad,2),'priceDelta':None if pd is None else round(pd,1),
              'floorConflict':floor_conflict,'safeReconciliationCandidate':safe,
              'reviewReason':r.get('reason') or (r.get('matchInfo') or {}).get('reason'),
            })
    out={'auditedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'mode':p.get('mode'),'caseCount':len(cases),'safeCandidateCount':sum(1 for x in cases if x['safeReconciliationCandidate']),'cases':cases}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__': main()
