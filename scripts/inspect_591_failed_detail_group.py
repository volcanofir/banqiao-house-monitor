import json
from datetime import datetime, timezone
from pathlib import Path

GAP=Path('docs/preview/company-gap.json')
ENR=Path('docs/preview/591-detail-floor-enrichment.json')
OUT=Path('docs/preview/591-detail-failure-group-audit.json')


def raw_members(g):
    rows=[]
    for src in g.get('sourceListings') or []:
        if src.get('source')!='591': continue
        for x in (src.get('mergedListings') or [src]):
            rid=str(x.get('id') or '')
            if rid.startswith('591:'):
                rows.append({'id':rid.split(':',1)[1],'title':x.get('title'),'price':x.get('price'),'size':x.get('size'),'address':x.get('address')})
    return rows


def main():
    gap=json.loads(GAP.read_text(encoding='utf-8'))
    enr=json.loads(ENR.read_text(encoding='utf-8'))
    details=enr.get('details') or {}
    failed={str(x.get('id')):x for x in enr.get('errors') or [] if x.get('id')}
    cmp={x.get('groupId'):x for x in gap.get('comparisons') or []}
    rows=[]
    for g in gap.get('propertyGroups') or []:
        members=raw_members(g)
        mids={x['id'] for x in members}
        hits=sorted(mids & set(failed))
        if not hits: continue
        enriched=[]
        for m in members:
            d=details.get(m['id']) or {}
            enriched.append({**m,'detailFloor':d.get('floor'),'rawFloor':d.get('rawFloor'),'layout':d.get('layout2') or d.get('layout'),'communityId':d.get('communityId'),'detailAvailable':bool(d)})
        c=cmp.get(g.get('groupId')) or {}
        rows.append({'groupId':g.get('groupId'),'road':g.get('road'),'title':g.get('title'),'failedIds':hits,'status':c.get('status'),'statusLabel':c.get('statusLabel'),'companyCandidate':c.get('companyCandidate'),'members':enriched})
    out={'auditedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'previewOnly':True,'failedIdCount':len(failed),'groups':rows}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__': main()
