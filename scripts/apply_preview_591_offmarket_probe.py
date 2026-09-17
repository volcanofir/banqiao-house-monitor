"""Apply confirmed rendered 591 invalid-page evidence to the Preview-only enriched copy.

Canonical docs/data/listings.json is never modified. This overlay exists only so the
Preview grouping/off-market history can show what would happen under the stricter
rendered-browser confirmation rule.
"""

import json
from pathlib import Path

ENRICHED = Path("docs/preview/scheme-a-external-enriched.json")
PROBE = Path("docs/preview/591-offmarket-probe.json")


def apply_row(row, confirmed):
    changed = 0
    rid = str(row.get("id") or "")
    evidence = confirmed.get(rid)
    if evidence:
        row["active"] = False
        row["removedAt"] = evidence.get("confirmedAt") or evidence.get("checkedAt")
        row["previewOnly591OffMarket"] = True
        row["previewOnly591OffMarketMarker"] = evidence.get("evidenceMarker")
        row["previewOnly591OffMarketEvidenceUrl"] = evidence.get("evidenceUrl")
        changed += 1
    for child in row.get("mergedListings") or []:
        changed += apply_row(child, confirmed)
    return changed


def main():
    state = json.loads(ENRICHED.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    if probe.get("previewOnly") is not True:
        raise RuntimeError("591 Preview off-market probe is not marked previewOnly")
    if probe.get("sourceDataUpdatedAt") != state.get("updatedAt"):
        raise RuntimeError(
            f"591 Preview probe/source mismatch: {probe.get('sourceDataUpdatedAt')} != {state.get('updatedAt')}"
        )

    confirmed_rows = probe.get("confirmedInactive") or []
    confirmed = {
        str(x.get("id")): x
        for x in confirmed_rows
        if x.get("id") and x.get("confirmedInactive") is True
    }

    applied = 0
    for row in state.get("listings") or []:
        applied += apply_row(row, confirmed)

    probe["appliedToPreviewEnrichedCount"] = applied
    probe["appliedConfirmedIds"] = sorted(confirmed)
    ENRICHED.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    PROBE.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "confirmedInactiveCount": len(confirmed),
        "appliedToPreviewEnrichedCount": applied,
        "confirmedIds": sorted(confirmed),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
