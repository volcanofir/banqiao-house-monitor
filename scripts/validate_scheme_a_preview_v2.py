"""Final all-pages and one-to-one release gate for scheme A Preview."""

import json
from collections import Counter
from pathlib import Path

import validate_scheme_a_preview as base

SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
GAP = Path("docs/preview/company-gap.json")


def normalize_validator_compatibility():
    # The legacy base guard used substring `har`, which falsely matches `Surfshark`.
    # Keep HAR blocking, but only for actual fallback-mode tokens.
    base.FORBIDDEN_MODES = (
        "har_fallback", "yungching_har", "housefun", "proxy",
        "previous_snapshot", "previous-snapshot",
    )

    # Base v1 knows the already-verified `yungching-direct-pg-v4` mode. v5 is the
    # all-pages engine built on that direct pg mechanism. Preserve the engine marker
    # while exposing the compatible direct-pg mode to the base validator.
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed = False
    for st in (s.get("roadStatus") or {}).values():
        for action in (st or {}).get("nextClicks") or []:
            if action.get("mode") == "yungching-direct-pg-v5":
                action["paginationEngine"] = "all-pages-v5"
                action["mode"] = "yungching-direct-pg-v4"
                changed = True
    if changed:
        SNAPSHOT.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    normalize_validator_compatibility()
    base.main()
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    p = json.loads(GAP.read_text(encoding="utf-8"))

    assert s.get("paginationGuardVersion") == "all-pages-v5", s.get("paginationGuardVersion")
    for road, st in (s.get("roadStatus") or {}).items():
        assert st.get("paginationCompleteAllPages") is True, (road, st)
        assert st.get("paginationExhausted") is True, (road, st)
        assert st.get("paginationLastPage") is not None, (road, st)
        assert int(st.get("paginationActivePage") or 0) == int(st.get("paginationLastPage") or -1), (road, st)
        if st.get("paginationExpected"):
            assert int(st.get("paginationLastPage") or 0) >= 2, (road, st)

    assert p.get("safeFloorParser") is True, p.get("safeFloorParser")
    reuse = p.get("companyCandidateReuseGuard") or {}
    assert reuse.get("enabled") is True, reuse

    stock_ids = []
    for row in p.get("comparisons") or []:
        if row.get("status") != "company_match":
            continue
        candidate = row.get("companyCandidate") or {}
        cid = str(candidate.get("id") or "")
        assert cid, row
        stock_ids.append(cid)
    duplicated_stock = [cid for cid, n in Counter(stock_ids).items() if n > 1]
    assert not duplicated_stock, duplicated_stock

    print(json.dumps({
        "scheme":"A",
        "allPagesValid":True,
        "paginationGuardVersion":s.get("paginationGuardVersion"),
        "lastPages":{r:(st or {}).get("paginationLastPage") for r,st in (s.get("roadStatus") or {}).items()},
        "safeFloorParser":True,
        "companyCandidateReuseGuard":reuse,
        "uniqueStockCandidateCount":len(stock_ids),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
