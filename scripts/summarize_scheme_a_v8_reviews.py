"""Summarize v8 review rows for human verification. Diagnostic only."""
import json
from datetime import datetime, timezone
from pathlib import Path
p=json.loads(Path('docs/preview/company-gap.json').read_text(encoding='utf-8'))
rows=[]
for x in p.get('comparisons') or []:
    if x.get('status')!='review': continue
    c=x.get('companyCandidate') or {}
    rows.append({
      'groupId':x.get('groupId'),'primarySource':x.get('primarySource'),'road':x.get('road'),
      'score':x.get('score'),'reason':x.get('reason') or (x.get('matchInfo') or {}).get('reason'),
      'companyCandidate':{k:c.get(k) for k in ('id','officialId','officialCaseId','title','price','area','floor')},
      'nearTie':x.get('companyNearTieGuardReview',False),'nearTieCandidates':x.get('companyNearTieCandidates'),
      'matchInfo':x.get('matchInfo'),
    })
out={'auditedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'mode':p.get('mode'),'reviewCount':len(rows),'rows':rows}
Path('docs/preview/scheme-a-v8-review-summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
