"""Classify scheme A 591 medium-risk groups using fresh 591 structured list fields.

Diagnostic only. Different non-empty community_id values inside one merged group are
strong evidence the group contains different properties. Same community_id alone is
not treated as proof of the same unit because different floors/units can share it.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROBE=Path('docs/preview/591-medium-field-probe.json')
OUT=Path('docs/preview/591-medium-community-audit.json')


def all_probe_rows(p):
    rows={}
    for road, rec in (p.get('roads') or {}).items():
        for pid, row in ((rec or {}).get('rows') or {}).items():
            x=dict(row.get('fields') or {})
            x['_road']=road
            rows[str(pid)]=x
    return rows


def norm(v):
    return str(v or '').strip()


def main():
    p=json.loads(PROBE.read_text(encoding='utf-8'))
    rows=all_probe_rows(p)
    out_rows=[]
    counts=Counter()
    for gid,g in (p.get('groups') or {}).items():
        members=[]
        community=defaultdict(list)
        missing=[]
        for pid in g.get('memberIds') or []:
            f=rows.get(str(pid))
            if not f:
                missing.append(str(pid)); continue
            cid=norm(f.get('community_id'))
            ca=norm(f.get('community_addr'))
            layout=norm(f.get('layout_str'))
            kind=norm(f.get('kindStr') or f.get('kind'))
            rec={'id':str(pid),'communityId':cid or None,'communityAddr':ca or None,'layout':layout or None,'kind':kind or None,'price':f.get('price'),'area':f.get('area_str'),'carport':f.get('price_has_carport'),'title':f.get('title')}
            members.append(rec)
            if cid: community[cid].append(rec)
        cids=sorted(community)
        if len(cids)>=2:
            risk='confirmed_mixed_community'
            action='split_by_community_id'
        elif len(cids)==1:
            risk='same_community_unit_ambiguous'
            action='keep_pending_detail_floor'
        else:
            risk='no_community_anchor'
            action='keep_pending_more_evidence'
        counts[risk]+=1
        out_rows.append({
            'groupId':gid,'road':g.get('road'),'title':g.get('title'),'memberCount':len(g.get('memberIds') or []),
            'matchedCurrentCount':len(members),'missingCurrentIds':missing,'distinctCommunityIds':cids,
            'communityCount':len(cids),'risk':risk,'recommendedAction':action,
            'communities':[{'communityId':cid,'count':len(ms),'communityAddrs':sorted({x.get('communityAddr') for x in ms if x.get('communityAddr')}),'layouts':sorted({x.get('layout') for x in ms if x.get('layout')}),'members':ms} for cid,ms in community.items()],
            'unanchoredMembers':[x for x in members if not x.get('communityId')],
        })
    out_rows.sort(key=lambda x:({'confirmed_mixed_community':0,'same_community_unit_ambiguous':1,'no_community_anchor':2}[x['risk']],-x['communityCount'],-x['memberCount']))
    out={'auditedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'previewOnly':True,'groupCount':len(out_rows),'riskCounts':dict(counts),'rows':out_rows}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'groupCount':len(out_rows),'riskCounts':dict(counts)},ensure_ascii=False))

if __name__=='__main__': main()
