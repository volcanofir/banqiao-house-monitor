"""Read-only Preview source freshness audit for GitHub Actions alerts."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path

MAX_AGE_MINUTES=240
SOURCES=(
 ("591",Path("docs/591-preview/snapshot.json")),
 ("信義房屋",Path("docs/data/listings.json")),
 ("樂屋網",Path("docs/preview/rakuya-seven-roads.json")),
 ("5168",Path("docs/preview/houseprice-seven-roads.json")),
)

def audit_source(name,payload,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(payload,dict):return {"source":name,"status":"error","reason":"Invalid JSON"}
    if name=="信義房屋":
        run=(payload.get("runs") or {}).get(name) or {}
        ok=run.get("status")=="ok"
        stamp=run.get("checkedAt")
    else:
        ok=payload.get("complete") is True
        stamp=payload.get("updatedAt")
    if not ok:return {"source":name,"status":"error","reason":"Last source capture not verified","at":stamp}
    try:
        dt=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
        if dt.tzinfo is None:raise ValueError("Unzoned date")
        age=(now-dt.astimezone(timezone.utc)).total_seconds()/60
    except (ValueError,TypeError,OverflowError):
        return {"source":name,"status":"error","reason":"Invalid source checkedAt"}
    if age < -5:return {"source":name,"status":"error","reason":"Future timestamp","ageMinutes":round(age)}
    if age>=MAX_AGE_MINUTES:return {"source":name,"status":"stale","reason":"No successful source capture for four hours","at":stamp,"ageMinutes":round(age)}
    return {"source":name,"status":"ok","at":stamp,"ageMinutes":round(age)}

def main():
    now=datetime.now(timezone.utc)
    reports=[]
    for name,path in SOURCES:
        try:payload=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):payload=None
        reports.append(audit_source(name,payload,now))
    summary=["## 板橋預覽版四平台來源更新狀態","",
             "| 平台 | 狀態 | 最近成功時間（UTC） | 距今分鐘 |",
             "|---|---|---|---:|"]
    for r in reports:
        summary.append(f"| {r['source']} | {r['status']} | {r.get('at') or '未取得'} | {r.get('ageMinutes','—')} |")
        print(json.dumps(r,ensure_ascii=False))
        if r['status']!='ok':
            print(f"::error title=預覽版來源超時::{r['source']} {r.get('reason')}")
    target=os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target,"a",encoding="utf-8") as f:f.write("\n".join(summary)+"\n")
    if any(r["status"]!="ok" for r in reports):
        raise SystemExit("One or more source feeds stale or unverified (no listing/status changes made)")
if __name__=="__main__":main()
