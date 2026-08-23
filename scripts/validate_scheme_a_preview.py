"""Hard release checks for Banqiao scheme A Preview.

This validator is Preview-only. It prevents a technically successful run from publishing
partial pagination, legacy fallback inventory, or known-bad floor extraction.
"""

import json
import re
from pathlib import Path


GAP = Path("docs/preview/company-gap.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
EXPECTED_ROADS = {
    "板橋區中山路二段", "板橋區三民路二段", "板橋區光復街", "板橋區萬安街",
    "板橋區林森街", "板橋區三民路一段", "板橋區翠華街",
}
FORBIDDEN_MODES = ("har", "housefun", "proxy", "previous_snapshot", "previous-snapshot")


def subject_floors(value):
    m = re.fullmatch(r"(\d{1,2})(?:~(\d{1,2}))?/(\d{1,2})樓", str(value or ""))
    if not m:
        return set()
    lo = int(m.group(1)); hi = int(m.group(2) or m.group(1)); total = int(m.group(3))
    if not (1 <= lo <= hi <= total <= 99):
        return set()
    return set(range(lo, hi + 1))


def main():
    p = json.loads(GAP.read_text(encoding="utf-8"))
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    assert p.get("fetchMode") == "yungching_official_rendered_dom_only", p.get("fetchMode")
    assert (p.get("companyDataGuard") or {}).get("enabled") is False, p.get("companyDataGuard")
    assert set(p.get("coveredRoads") or []) == EXPECTED_ROADS, p.get("coveredRoads")

    company = p.get("companyListings") or []
    assert company and len(company) == p.get("companyListingCount"), (len(company), p.get("companyListingCount"))
    nonofficial = [x for x in company if x.get("sourceMode") != "yungching_official_browser"]
    assert not nonofficial, nonofficial[:10]

    bad_modes = []
    for road, st in (p.get("roadStatus") or {}).items():
        mode = str((st or {}).get("mode") or "").lower()
        if any(token in mode for token in FORBIDDEN_MODES):
            bad_modes.append((road, mode))
    assert not bad_modes, bad_modes

    z = (s.get("roadStatus") or {}).get("板橋區中山路二段") or {}
    direct = [
        x for x in (z.get("nextClicks") or [])
        if x.get("mode") == "yungching-direct-pg-v4" and int(x.get("target") or 0) == 2
    ]
    assert z.get("mainHttp") == 200, z
    assert z.get("available") is True, z
    assert z.get("paginationComplete") is True, z
    assert int(z.get("paginationActivePage") or 0) >= 2, z
    assert int(z.get("count") or 0) >= 39, z
    assert direct and direct[0].get("http") == 200 and direct[0].get("activeVerified") is True, direct

    rows = {str(x.get("id")): x for x in (s.get("listings") or [])}

    # These listings are intentionally stable regression fixtures because earlier
    # global-DOM scanning grabbed a recommendation card's floor instead of the current house.
    known = rows.get("6935425") or {}
    assert known, "known floor fixture 6935425 missing"
    assert known.get("floor") == "3/14樓", known
    assert known.get("officialCaseId") == "YC1239410", known

    one = rows.get("6857079") or {}
    assert one and 1 in subject_floors(one.get("floor")), one

    three = rows.get("6693666") or {}
    assert three and 3 in subject_floors(three.get("floor")), three

    invalid = []
    for row in s.get("listings") or []:
        floor = row.get("floor")
        if floor and not subject_floors(floor):
            invalid.append({"id": row.get("id"), "floor": floor})
    assert not invalid, invalid[:20]

    detail = s.get("detailFloorEnrichment") or {}
    assert int(detail.get("enriched") or 0) >= 3, detail
    assert int(detail.get("officialCaseIdEnriched") or 0) >= 3, detail

    print(json.dumps({
        "scheme": "A",
        "valid": True,
        "companyListingCount": p.get("companyListingCount"),
        "counts": p.get("counts"),
        "zhongshanCount": z.get("count"),
        "detailFloorEnrichment": detail,
        "legacyFallbacks": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
