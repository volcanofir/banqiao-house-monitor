"""Hard release checks for Banqiao scheme A Preview.

Preview is publishable only when the current company inventory is fresh official Yongching
Chromium data, all advertised pagination was collected, impossible cross-road house-ID
collisions were removed, and any extracted floor is physically/title consistent.
Fixed property IDs belong in the separate regression workflow, not this release gate.
"""

import json
import re
from collections import defaultdict
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


def chinese_floor_number(raw):
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    d = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    if raw == "十":
        return 10
    if "十" in raw:
        left, right = raw.split("十", 1)
        return d.get(left, 1) * 10 + d.get(right, 0)
    return d.get(raw)


def title_floors(title):
    text = str(title or "")
    out = set()
    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            out.add(n)
    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        n = chinese_floor_number(raw)
        if n:
            out.add(n)
    return out


def main():
    p = json.loads(GAP.read_text(encoding="utf-8"))
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = s.get("listings") or []

    assert p.get("fetchMode") == "yungching_official_rendered_dom_only", p.get("fetchMode")
    assert (p.get("companyDataGuard") or {}).get("enabled") is False, p.get("companyDataGuard")
    assert set(p.get("coveredRoads") or []) == EXPECTED_ROADS, p.get("coveredRoads")

    company = p.get("companyListings") or []
    assert company and len(company) == p.get("companyListingCount"), (len(company), p.get("companyListingCount"))
    assert len(company) == len(listings), (len(company), len(listings))
    nonofficial = [x for x in company if x.get("sourceMode") != "yungching_official_browser"]
    assert not nonofficial, nonofficial[:10]

    bad_modes = []
    for road, st in (p.get("roadStatus") or {}).items():
        mode = str((st or {}).get("mode") or "").lower()
        if any(token in mode for token in FORBIDDEN_MODES):
            bad_modes.append((road, mode))
    assert not bad_modes, bad_modes

    # Every road that advertises an extra page must prove the direct pg route was loaded.
    for road, st in (s.get("roadStatus") or {}).items():
        assert st.get("mainHttp") == 200, (road, st)
        assert st.get("available") is True, (road, st)
        assert int(st.get("count") or 0) > 0, (road, st)
        if st.get("paginationExpected"):
            direct = [
                x for x in (st.get("nextClicks") or [])
                if x.get("mode") == "yungching-direct-pg-v4" and int(x.get("target") or 0) >= 2
            ]
            assert st.get("paginationComplete") is True, (road, st)
            assert int(st.get("paginationActivePage") or 0) >= 2, (road, st)
            assert direct, (road, st.get("nextClicks"))
            assert all(x.get("http") == 200 and x.get("activeVerified") is True for x in direct), direct

    # ID integrity: one official /house/<id> cannot simultaneously belong to multiple roads.
    integrity = s.get("idIntegrityGuard") or {}
    assert integrity.get("enabled") is True, integrity
    assert not (integrity.get("remainingCollisionIds") or []), integrity
    roads_by_id = defaultdict(set)
    for row in listings:
        rid = str(row.get("id") or "").strip()
        road = str(row.get("road") or "").strip()
        assert rid and road, row
        roads_by_id[rid].add(road)
    collisions = {rid: sorted(roads) for rid, roads in roads_by_id.items() if len(roads) > 1}
    assert not collisions, collisions

    # Each final road count must equal the actual post-integrity listing count.
    actual_road_counts = defaultdict(int)
    for row in listings:
        actual_road_counts[row.get("road")] += 1
    for road in EXPECTED_ROADS:
        st = (s.get("roadStatus") or {}).get(road) or {}
        assert int(st.get("count") or 0) == actual_road_counts[road], (road, st.get("count"), actual_road_counts[road])

    # Floors: reject malformed subject/total floors and conflicts with explicit title floors.
    invalid = []
    conflicts = []
    for row in listings:
        floor = row.get("floor")
        if not floor:
            continue
        subjects = subject_floors(floor)
        if not subjects:
            invalid.append({"id": row.get("id"), "floor": floor})
            continue
        expected = title_floors(row.get("title"))
        if expected and expected.isdisjoint(subjects):
            conflicts.append({
                "id": row.get("id"), "title": row.get("title"), "floor": floor,
                "titleFloors": sorted(expected), "subjectFloors": sorted(subjects),
            })
    assert not invalid, invalid[:20]
    assert not conflicts, conflicts[:20]

    detail = s.get("detailFloorEnrichment") or {}
    if int(detail.get("attempted") or 0) > 0:
        assert int(detail.get("enriched") or 0) > 0, detail
        assert int(detail.get("officialCaseIdEnriched") or 0) > 0, detail

    print(json.dumps({
        "scheme": "A",
        "valid": True,
        "browserListingCount": len(listings),
        "companyListingCount": p.get("companyListingCount"),
        "counts": p.get("counts"),
        "roadCounts": dict(actual_road_counts),
        "idIntegrityGuard": integrity,
        "detailFloorEnrichment": detail,
        "legacyFallbacks": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
