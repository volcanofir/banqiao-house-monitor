import json
import os
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("docs/company/sinyi-runner-history.json")
MAX_RECORDS = 100

def main():
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload={"records":[]}
    if OUT.exists():
        try:
            payload=json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            payload={"records":[]}
    records=list(payload.get("records") or [])
    record={
        "recordedAt":now,
        "runId":os.environ.get("GITHUB_RUN_ID"),
        "runAttempt":os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerName":os.environ.get("RUNNER_NAME"),
        "runnerOs":os.environ.get("RUNNER_OS"),
        "runnerArch":os.environ.get("RUNNER_ARCH"),
    }
    records=[r for r in records if str(r.get("runId")) != str(record["runId"])]
    records.append(record)
    records=records[-MAX_RECORDS:]
    payload={"updatedAt":now,"recordCount":len(records),"records":records}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(record,ensure_ascii=False))

if __name__=="__main__":
    main()
