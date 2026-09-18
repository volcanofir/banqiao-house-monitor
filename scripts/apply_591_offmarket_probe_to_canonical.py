"""Apply rendered-Chrome 591 off-market confirmations to canonical monitor data.

The verifier is intentionally separate and conservative: it only confirms explicit
591 invalid-page wording (or HTTP 404/410). This step applies those confirmed IDs to
canonical docs/data/listings.json after a successful full 591 list crawl.
"""

import json
from pathlib import Path

DATA = Path("docs/data/listings.json")
PROBE = Path("docs/preview/591-offmarket-probe.json")
EXPECTED_MODE = "rendered_chrome_explicit_591_inactive_marker_v1"


def apply_row(row, confirmed, changed_ids):
    rid = str(row.get("id") or "")
    evidence = confirmed.get(rid)
    if evidence:
        was_active = row.get("active", True) is True
        row["active"] = False
        row["removedAt"] = evidence.get("confirmedAt") or evidence.get("checkedAt")
        row["offMarketVerifiedBy"] = EXPECTED_MODE
        row["offMarketEvidenceMarker"] = evidence.get("evidenceMarker")
        row["offMarketEvidenceUrl"] = evidence.get("evidenceUrl")
        if was_active and rid:
            changed_ids.add(rid)

    for child in row.get("mergedListings") or []:
        if isinstance(child, dict):
            apply_row(child, confirmed, changed_ids)


def main():
    state = json.loads(DATA.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))

    if probe.get("previewOnly") is not True:
        raise RuntimeError("591 rendered probe format mismatch: previewOnly flag missing")
    if probe.get("mode") != EXPECTED_MODE:
        raise RuntimeError(f"591 rendered probe mode mismatch: {probe.get('mode')}")
    if probe.get("sourceDataUpdatedAt") != state.get("updatedAt"):
        raise RuntimeError(
            f"591 rendered probe/source mismatch: {probe.get('sourceDataUpdatedAt')} != {state.get('updatedAt')}"
        )

    run = (state.get("runs") or {}).get("591") or {}
    if run.get("status") != "ok":
        raise RuntimeError("Latest 591 crawl is not successful; refuse off-market apply")
    if probe.get("source591CheckedAt") != run.get("checkedAt"):
        raise RuntimeError(
            f"591 rendered probe/run mismatch: {probe.get('source591CheckedAt')} != {run.get('checkedAt')}"
        )

    confirmed_rows = probe.get("confirmedInactive") or []
    confirmed = {
        str(x.get("id")): x
        for x in confirmed_rows
        if x.get("id") and x.get("confirmedInactive") is True
    }

    changed_ids = set()
    for row in state.get("listings") or []:
        if isinstance(row, dict):
            apply_row(row, confirmed, changed_ids)

    logs = list(run.get("logs") or [])
    logs.append(
        "591 Chrome 下架驗證："
        f"候選 {int(probe.get('candidateCount') or 0)} 筆，"
        f"明確失效 {len(confirmed)} 筆，"
        f"本輪新標記下架 {len(changed_ids)} 筆。"
    )
    run["logs"] = logs
    run["removedCount"] = int(run.get("removedCount") or 0) + len(changed_ids)
    run["renderedOffMarketCandidateCount"] = int(probe.get("candidateCount") or 0)
    run["renderedOffMarketConfirmedCount"] = len(confirmed)
    run["renderedOffMarketAppliedCount"] = len(changed_ids)
    run["renderedOffMarketCheckedAt"] = probe.get("generatedAt")
    run["renderedOffMarketMode"] = EXPECTED_MODE
    state.setdefault("runs", {})["591"] = run

    DATA.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "candidateCount": int(probe.get("candidateCount") or 0),
        "confirmedInactiveCount": len(confirmed),
        "appliedInactiveCount": len(changed_ids),
        "appliedIds": sorted(changed_ids),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
