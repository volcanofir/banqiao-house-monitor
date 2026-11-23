"""Read-only health audit for the four independent Preview source snapshots.

Sinyi status MUST come from the independently published source feed, never from
canonical listings.json (which can stay old when grouping verification fails).
No listing or off-market state is mutated by this script.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_MINUTES = 240
SOURCES = (
    ("591", Path("docs/591-preview/snapshot.json")),
    ("信義房屋", Path("docs/preview/sinyi-source.json")),
    ("樂屋網", Path("docs/preview/rakuya-seven-roads.json")),
    ("5168", Path("docs/preview/houseprice-seven-roads.json")),
)
SINYI_ROADS = {
    "板橋區中山路二段", "板橋區三民路一段", "板橋區三民路二段",
    "板橋區翠華街", "板橋區林森街", "板橋區萬安街", "板橋區光復街",
}


def sinyi_snapshot_error(payload):
    """Return a reason for rejecting a supposedly verified independent feed."""
    if payload.get("source") != "信義房屋" or payload.get("previewOnly") is not True:
        return "Not the independent Sinyi Preview source"
    if payload.get("complete") is not True:
        return "Independent Sinyi capture incomplete"
    if payload.get("noOffmarketDecision") is not True or payload.get("noAutomaticNewPropertyDecision") is not True:
        return "Sinyi source safety flags missing"
    run = (payload.get("runs") or {}).get("信義房屋") or {}
    if run.get("status") != "ok" or not payload.get("updatedAt") or run.get("checkedAt") != payload["updatedAt"]:
        return "Sinyi success timestamp does not match source snapshot"
    rows = payload.get("listings")
    if not isinstance(rows, list) or not rows:
        return "Sinyi snapshot has no listings"
    if (type(payload.get("uniqueListingCount")) is not int or
            payload["uniqueListingCount"] != len(rows) or
            run.get("totalCount") != len(rows)):
        return "Sinyi listing counts mismatch"
    roads = payload.get("roadCounts")
    if (not isinstance(roads, list) or len(roads) != 7 or
            any(not isinstance(r, dict) for r in roads) or
            {r.get("road") for r in roads} != SINYI_ROADS or
            any(type(r.get("count")) is not int or r["count"] < 0 for r in roads) or
            sum(r["count"] for r in roads) != len(rows)):
        return "Sinyi seven-road coverage/counts mismatch"
    expected = {r["road"]: r["count"] for r in roads}
    observed = {road: 0 for road in SINYI_ROADS}
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            return "Invalid Sinyi listing"
        rid, road = row.get("id"), row.get("road")
        if (row.get("source") != "信義房屋" or
                not isinstance(rid, str) or not rid.startswith("信義房屋:") or
                rid == "信義房屋:" or rid in ids or road not in SINYI_ROADS or
                not row.get("sinyiApiVerifiedAt")):
            return "Duplicate, unverified, or out-of-scope Sinyi listing"
        ids.add(rid)
        observed[road] += 1
    if expected != observed:
        return "Sinyi individual road counts mismatch"
    return None


def audit_source(name, payload, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict):
        return {"source": name, "status": "error", "reason": "Invalid JSON"}
    if name == "信義房屋":
        reason = sinyi_snapshot_error(payload)
        if reason:
            return {"source": name, "status": "error", "reason": reason,
                    "at": payload.get("updatedAt")}
        stamp = payload["updatedAt"]
    else:
        if payload.get("complete") is not True:
            return {"source": name, "status": "error",
                    "reason": "Last source capture not verified", "at": payload.get("updatedAt")}
        stamp = payload.get("updatedAt")
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Unzoned date")
        age = (now - dt.astimezone(timezone.utc)).total_seconds() / 60
    except (ValueError, TypeError, OverflowError):
        return {"source": name, "status": "error", "reason": "Invalid source checkedAt"}
    if age < -5:
        return {"source": name, "status": "error", "reason": "Future timestamp",
                "ageMinutes": round(age)}
    if age >= MAX_AGE_MINUTES:
        return {"source": name, "status": "stale", "reason": "No successful source capture for four hours",
                "at": stamp, "ageMinutes": round(age)}
    return {"source": name, "status": "ok", "at": stamp, "ageMinutes": round(age)}


def main():
    now = datetime.now(timezone.utc)
    reports = []
    for name, path in SOURCES:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        reports.append(audit_source(name, payload, now))
    summary = ["## 板橋預覽版四平台獨立來源更新狀態", "",
               "| 平台 | 狀態 | 最近成功時間（UTC） | 距今分鐘 |",
               "|---|---|---|---:|"]
    for r in reports:
        summary.append(f"| {r['source']} | {r['status']} | {r.get('at') or '未取得'} | {r.get('ageMinutes', '—')} |")
        print(json.dumps(r, ensure_ascii=False))
        if r["status"] != "ok":
            print(f"::error title=預覽版來源過期或不完整::{r['source']} {r.get('reason')}")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")
    if any(r["status"] != "ok" for r in reports):
        raise SystemExit("One or more independent Preview feeds stale or unverified (no listing/status changes made)")


if __name__ == "__main__":
    main()
