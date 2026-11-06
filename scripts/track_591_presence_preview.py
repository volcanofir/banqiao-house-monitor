"""Preview-only presence tracking: two absences = pending, NEVER confirmed removed."""
import json
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT=Path("docs/591-preview/snapshot.json")
REPORT=Path("docs/preview/591-presence-status.json")
ROADS={"中山路二段","三民路一段","三民路二段","翠華街","林森街","萬安街","光復街"}

def time_value(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("Unzoned source time")
    return d.astimezone(timezone.utc)

def build(old, src):
    at=src.get("updatedAt")
    current=time_value(at)
    if src.get("complete") is not True or src.get("noOffmarketDecision") is not True:
        raise ValueError("591 source not fully verified")
    roads=src.get("roadCounts") or []
    if len(roads)!=7 or {x.get("road") for x in roads}!=ROADS:
        raise ValueError("Incomplete seven roads")
    rows=src.get("listings")
    if not isinstance(rows,list) or len(rows)!=src.get("counts",{}).get("totalListings"):
        raise ValueError("Invalid listing count")
    ids=[x.get("id") for x in rows if isinstance(x,dict)]
    if len(ids)!=len(rows) or len(set(ids))!=len(ids) or any(not isinstance(x,str) or not x.startswith("591:") for x in ids):
        raise ValueError("Duplicate or invalid listing IDs")
    prev=old.get("checkedAt")
    if prev:
        prior=time_value(prev)
        if prior>current: raise ValueError("Older source snapshot cannot override newer presence record")
        if prior==current: return old
    active=set(ids); history={k:dict(v) for k,v in (old.get("records") or {}).items()}
    reappeared=0
    for rid in active:
        old_row=history.get(rid) or {}
        reappeared+=int(bool(old_row.get("missingStreak",0)))
        history[rid]={
            "firstObservedAt":old_row.get("firstObservedAt") or at,
            "lastObservedAt":at,"firstMissingAt":None,
            "missingStreak":0,"state":"observed"}
    for rid,row in history.items():
        if rid in active: continue
        row["missingStreak"]=int(row.get("missingStreak") or 0)+1
        row["firstMissingAt"]=row.get("firstMissingAt") or at
        row["state"]="pending_confirmation" if row["missingStreak"]>=2 else "unobserved_once"
    return {
        "schemaVersion":1,"source":"591","previewOnly":True,"complete":True,
        "checkedAt":at,"missingIdIsNotDelisting":True,
        "policy":"Repeated absence from complete seven-road lists is pending confirmation, not delisting",
        "observedIdCount":len(active),
        "unobservedOnceIdCount":sum(r["state"]=="unobserved_once" for r in history.values()),
        "pendingConfirmationIdCount":sum(r["state"]=="pending_confirmation" for r in history.values()),
        "confirmedOffmarketIdCount":0,"reappearedThisCheckCount":reappeared,
        "trackedIdCount":len(history),"records":dict(sorted(history.items()))}

def main():
    src=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    old=json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    out=build(old,src)
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("checkedAt","observedIdCount","unobservedOnceIdCount","pendingConfirmationIdCount","confirmedOffmarketIdCount")},ensure_ascii=False))

if __name__=="__main__":main()
