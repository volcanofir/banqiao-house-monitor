"""Four-source Preview safety ledger. Missing advertisement ID never means delisting."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('docs/preview')
CANONICAL = Path('docs/data/listings.json')
WARELIST = Path('docs/591-preview/snapshot.json')
LEDGER = ROOT / 'platform-id-history.json'
REPORT = ROOT / 'source-integrity.json'
ROADS = {'中山路二段', '三民路一段', '三民路二段', '翠華街', '林森街', '萬安街', '光復街'}
PLATFORMS = ('591', '信義房屋', '樂屋網', '5168')

def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {'_loadError': str(exc)}

def as_time(v):
    if v in (None, ''):
        return None
    try:
        n = float(v)
        if n > 0:
            return n/1000 if n > 1e12 else n
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return d.replace(tzinfo=timezone.utc).timestamp() if d.tzinfo is None else d.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None

def older(a, b):
    if as_time(a) is None: return b
    if as_time(b) is None: return a
    return a if as_time(a) <= as_time(b) else b

def newer(a, b):
    if as_time(a) is None: return b
    if as_time(b) is None: return a
    return a if as_time(a) >= as_time(b) else b

def listing_id(source, row):
    raw = str((row.get('houseId') if source in ('591','信義房屋') else row.get('listingId')) or '').strip()
    if not raw: raw = str(row.get('id') or '').split(':',1)[-1]
    return f'{source}:{raw}' if raw else ''

def verified(source, payload):
    if not isinstance(payload, dict) or payload.get('_loadError'):
        return False, 'missing/corrupt snapshot', []
    rows = payload.get('listings')
    if not isinstance(rows, list) or not rows:
        return False, 'empty/incomplete listings', []
    if source == '信義房屋':
        if (payload.get('runs',{}).get(source) or {}).get('status') != 'ok':
            return False, 'Sinyi run incomplete; previous history held', []
        rows = [r for r in rows if isinstance(r,dict) and r.get('source')==source and r.get('active',True)]
    else:
        roads = payload.get('roadCounts') or []
        if payload.get('complete') is not True or len(roads) != 7 or {str(r.get('road')) for r in roads} != ROADS:
            return False, 'seven-road snapshot not verified', []
        if any(not isinstance(r.get('count'),int) or r['count']<0 for r in roads) or sum(r['count'] for r in roads)<len(rows):
            return False, 'inconsistent road counts', []
        if source == '591' and (payload.get('schemaVersion')!=1 or payload.get('noOffmarketDecision') is not True or payload.get('noAutomaticNewPropertyDecision') is not True):
            return False, '591 safe-history flags missing', []
    if not rows: return False, 'no active listings', []
    ids = [listing_id(source,r) for r in rows if isinstance(r,dict)]
    if len(ids)!=len(rows) or any(not x or x.endswith(':') for x in ids) or len(set(ids))!=len(ids):
        return False, 'duplicate/missing IDs', []
    return True, 'verified', rows

def historic(canonical, preview):
    for state in (canonical, preview):
        for row in state.get('listings',[]) if isinstance(state.get('listings'),list) else []:
            if not isinstance(row,dict) or row.get('source') not in ('591','信義房屋'): continue
            yield row['source'], row
            for member in row.get('mergedListings') or []:
                if isinstance(member,dict): yield row['source'], member

def build(previous, sources, canonical=None, preview=None):
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    out = {'schemaVersion':1, 'updatedAt':now,
           'identityPolicy':'Permanent raw advertisement IDs; absence is never automatic delisting; new ID is not new property',
           'sources':{}, 'entries':{s:dict((previous.get('entries') or {}).get(s) or {}) for s in PLATFORMS}}
    for s,row in historic(canonical or {},preview or {}):
        sid=listing_id(s,row)
        if not sid: continue
        old=dict(out['entries'][s].get(sid) or {})
        old['firstObservedAt']=older(old.get('firstObservedAt'),row.get('firstSeenAt'))
        old['lastObservedAt']=newer(old.get('lastObservedAt'),row.get('lastSeenAt'))
        old['sourcePublishedAt']=older(old.get('sourcePublishedAt'),row.get('sourcePublishedAt') or row.get('postTime'))
        old['everObserved']=True
        out['entries'][s][sid]=old
    for s in PLATFORMS:
        payload=sources[s]
        ok,reason,rows=verified(s,payload)
        hist=out['entries'][s]
        prev=(previous.get('sources') or {}).get(s) or {}
        if not ok:
            out['sources'][s]={'status':'stale','reason':reason,'historyIdCount':len(hist),
                               'lastVerifiedAt':prev.get('lastVerifiedAt'),'missingIdIsNotDelisting':True}
            continue
        stamp=payload.get('updatedAt') or (payload.get('runs',{}).get(s) or {}).get('checkedAt') or now
        observed=set(); reappeared=0; new=0
        for row in rows:
            sid=listing_id(s,row); observed.add(sid)
            old=dict(hist.get(sid) or {})
            if not old: new+=1
            elif old.get('seenOnLastVerifiedCheck') is False: reappeared+=1
            seen=row.get('firstSeenAt') or row.get('lastSeenAt') or stamp
            old['firstObservedAt']=older(old.get('firstObservedAt'),seen)
            old['lastObservedAt']=newer(old.get('lastObservedAt'),stamp)
            published=row.get('sourcePublishedAt') or row.get('postTime')
            if published is not None:
                old['sourcePublishedAt']=older(old.get('sourcePublishedAt'),published)
                old['sourcePublishedAtType']=row.get('sourcePublishedAtType') or old.get('sourcePublishedAtType')
            old['seenOnLastVerifiedCheck']=True
            old['everObserved']=True
            hist[sid]=old
        for sid,row in hist.items():
            if sid not in observed: row['seenOnLastVerifiedCheck']=False
        out['sources'][s]={'status':'ok','lastVerifiedAt':stamp,'observedIdCount':len(observed),
                            'historyIdCount':len(hist),'firstSeenIdCount':new,'reappearedIdCount':reappeared,
                            'missingIdIsNotDelisting':True,'newIdIsNotNewProperty':True}
    return out

def write_atomic(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def main():
    canonical=load(CANONICAL)
    sources={'591':load(WARELIST),'信義房屋':canonical,
             '樂屋網':load(ROOT/'rakuya-seven-roads.json'),
             '5168':load(ROOT/'houseprice-seven-roads.json')}
    history=build(load(LEDGER),sources,canonical,load(ROOT/'preview-monitor-state.json'))
    if not any(x['status']=='ok' for x in history['sources'].values()):
        raise RuntimeError('No verified source; preserve prior Preview')
    write_atomic(LEDGER,history)
    write_atomic(REPORT,{'checkedAt':history['updatedAt'],'previewOnly':True,
                         'sourceStatus':history['sources'],
                         'rule':'Fail closed per source; ID absence cannot imply delisting; source publish time never inferred from discovery'})
    print(json.dumps(history['sources'],ensure_ascii=False))
if __name__=='__main__':
    main()
