import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WEAK=Path('docs/preview/scheme-a-weak-group-audit.json')
GAP=Path('docs/preview/company-gap.json')
OUT=Path('docs/preview/591-medium-status-summary.json')


def main():
    w=json.loads(WEAK.read_text(encoding='utf-8'))
    p=json.loads(GAP.read_text(encoding='utf-8'))
    mids={x.get('groupId') for x in w.get('groups',[]) if x.get('risk')=='medium'}
    groups={x.get('groupId'):x for x in p.get('propertyGroups') or []}
    rows=[]
    for c in p.get('comparisons') or []:
        gid=c.get('groupId')
        if gid not in mids: continue
        g=groups.get(gid) or {}
        rows.append({
            'groupId':gid,'road':g.get('road'),'title':g.get('title'),'rawMemberCount':g.get('rawMemberCount'),
            'status':c.get('status'),'statusLabel':c.get('statusLabel'),'score':c.get('score'),
            'candidate':c.get('companyCandidate'),'reason':c.get('reason') or (c.get('matchInfo') or {}).get('reason'),
            'companyStrongCandidateCount':c.get('companyStrongCandidateCount'),
            'nearTie':c.get('companyNearTieStrong') is True,
        })
    counts=Counter(x['status'] for x in rows)
    rows.sort(key=lambda x:({'company_match':0,'review':1,'missing':2,'unavailable':3}.get(x['status'],9),-(x.get('score') or 0)))
    out={'generatedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'previewOnly':True,'mediumGroupCount':len(rows),'statusCounts':dict(counts),'rows':rows}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'mediumGroupCount':len(rows),'statusCounts':dict(counts)},ensure_ascii=False))

if __name__=='__main__': main()
