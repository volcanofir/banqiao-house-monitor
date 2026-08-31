"""Hard release checks for Banqiao scheme A Preview.

A Preview is publishable only when one internally consistent run proves all of these:
- 7 monitored roads came from fresh Yongching official Chromium DOM only.
- Every advertised result page was collected.
- Cross-road stale house IDs were sanitized and no ID collision remains.
- Company rows, road totals, snapshot totals and comparison candidates agree exactly.
- 591 regrouping / Sinyi-primary grouping is internally one-to-one and count-consistent.
- Structured company floors are not polluted by DOM text inference.
- No HAR / Housefun / proxy / previous-snapshot fallback entered the result.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


GAP = Path("docs/preview/company-gap.json")
SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")
EXPECTED_ROADS = {
    "板橋區中山路二段", "板橋區三民路二段", "板橋區光復街", "板橋區萬安街",
    "板橋區林森街", "板橋區三民路一段", "板橋區翠華街",
}
ALLOWED_EXTERNAL_SOURCES = {"591", "信義房屋"}
FORBIDDEN_MODES = ("har", "housefun", "proxy", "previous_snapshot", "previous-snapshot")
STATUS_LABELS = {
    "company_match": "庫存",
    "review": "待確認",
    "missing": "未接回",
    "unavailable": "尚未比對",
}


def iso_time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc)
    except Exception:
        return None


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


def raw_external_ids(group):
    """Return the actual raw 591/Sinyi IDs represented by one property group."""
    ids = []
    for src in group.get("sourceListings") or []:
        merged = src.get("mergedListings") or []
        if merged:
            ids.extend(str(x.get("id")) for x in merged if x.get("id"))
        elif src.get("id"):
            ids.append(str(src.get("id")))
    return ids


def main():
    p = json.loads(GAP.read_text(encoding="utf-8"))
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    listings = s.get("listings") or []
    road_status = s.get("roadStatus") or {}

    # ----- canonical run / source-chain integrity -----
    assert s.get("previewOnly") is True, s.get("previewOnly")
    assert p.get("fetchMode") == "yungching_official_rendered_dom_only", p.get("fetchMode")
    assert p.get("structuredFloorMatching") is True, p.get("structuredFloorMatching")
    assert (p.get("companyDataGuard") or {}).get("enabled") is False, p.get("companyDataGuard")
    assert set(p.get("coveredRoads") or []) == EXPECTED_ROADS, p.get("coveredRoads")
    assert set(road_status) == EXPECTED_ROADS, sorted(road_status)
    assert p.get("companySnapshotCapturedAt") == s.get("capturedAt"), (
        p.get("companySnapshotCapturedAt"), s.get("capturedAt")
    )
    stats = p.get("officialBrowserCompany") or {}
    assert stats.get("capturedAt") == s.get("capturedAt"), (stats.get("capturedAt"), s.get("capturedAt"))
    assert int(stats.get("acceptedRoadCount") or 0) == len(EXPECTED_ROADS), stats
    assert int(stats.get("unavailableRoadCount") or 0) == 0, stats

    captured = iso_time(s.get("capturedAt"))
    generated = iso_time(p.get("generatedAt"))
    assert captured and generated, (s.get("capturedAt"), p.get("generatedAt"))
    delta_minutes = (generated - captured).total_seconds() / 60
    assert -1 <= delta_minutes <= 90, delta_minutes

    forbidden_text = " ".join([
        str(p.get("fetchMode") or ""), str(p.get("companyDataSource") or ""),
        " ".join(str((x or {}).get("mode") or "") for x in (p.get("roadStatus") or {}).values()),
    ]).lower()
    assert not any(token in forbidden_text for token in FORBIDDEN_MODES), forbidden_text

    # ----- pagination and per-road completeness for all 7 roads -----
    actual_road_counts = defaultdict(int)
    for row in listings:
        actual_road_counts[str(row.get("road") or "")] += 1

    for road in EXPECTED_ROADS:
        st = road_status.get(road) or {}
        assert st.get("mainHttp") == 200, (road, st)
        assert st.get("available") is True, (road, st)
        assert st.get("paginationComplete") is True, (road, st)
        road_count = int(st.get("count") or 0)
        assert road_count >= 0, (road, st)
        if road_count == 0:
            assert st.get("emptyResultVerified") is True, (road, st)
        assert road_count == actual_road_counts[road], (
            road, st.get("count"), actual_road_counts[road]
        )
        if st.get("paginationExpected"):
            direct = [
                x for x in (st.get("nextClicks") or [])
                if x.get("mode") == "yungching-direct-pg-v4" and int(x.get("target") or 0) >= 2
            ]
            assert int(st.get("paginationActivePage") or 0) >= 2, (road, st)
            assert direct, (road, st.get("nextClicks"))
            assert all(x.get("http") == 200 and x.get("activeVerified") is True for x in direct), direct

    assert sum(actual_road_counts.values()) == len(listings) == int(s.get("listingCount") or -1), (
        dict(actual_road_counts), len(listings), s.get("listingCount")
    )

    # ----- official ID integrity -----
    integrity = s.get("idIntegrityGuard") or {}
    assert integrity.get("enabled") is True, integrity
    assert not (integrity.get("remainingCollisionIds") or []), integrity
    assert int(integrity.get("beforeCount") or 0) - int(integrity.get("removedCount") or 0) == int(integrity.get("afterCount") or -1), integrity
    assert int(integrity.get("afterCount") or -1) == len(listings), integrity

    roads_by_id = defaultdict(set)
    snapshot_by_id = {}
    for row in listings:
        rid = str(row.get("id") or "").strip()
        road = str(row.get("road") or "").strip()
        assert rid and road in EXPECTED_ROADS, row
        assert rid not in snapshot_by_id, f"duplicate final Yongching ID: {rid}"
        snapshot_by_id[rid] = row
        roads_by_id[rid].add(road)
        assert str(row.get("url") or "").rstrip("/").endswith(f"/house/{rid}"), row
    collisions = {rid: sorted(roads) for rid, roads in roads_by_id.items() if len(roads) > 1}
    assert not collisions, collisions

    # ----- company rows must be a lossless view of the exact same snapshot -----
    company = p.get("companyListings") or []
    assert company and len(company) == int(p.get("companyListingCount") or -1), (len(company), p.get("companyListingCount"))
    assert len(company) == len(listings), (len(company), len(listings))
    company_by_id = {}
    company_road_counts = defaultdict(int)
    for row in company:
        cid = str(row.get("id") or "")
        oid = str(row.get("officialId") or "")
        assert cid == f"YC:{oid}" and oid in snapshot_by_id, row
        assert cid not in company_by_id, f"duplicate company candidate ID: {cid}"
        assert row.get("sourceMode") == "yungching_official_browser", row
        assert row.get("road") == snapshot_by_id[oid].get("road"), row
        company_by_id[cid] = row
        company_road_counts[row.get("road")] += 1
    normalized_company_road_counts = {r: int(company_road_counts.get(r, 0)) for r in EXPECTED_ROADS}
    normalized_actual_road_counts = {r: int(actual_road_counts.get(r, 0)) for r in EXPECTED_ROADS}
    assert normalized_company_road_counts == normalized_actual_road_counts, (
        normalized_company_road_counts, normalized_actual_road_counts
    )

    for road in EXPECTED_ROADS:
        pst = (p.get("roadStatus") or {}).get(road) or {}
        assert pst.get("available") is True and pst.get("mode") == "yungching_official_browser", (road, pst)
        assert int(pst.get("count") or 0) == actual_road_counts[road], (road, pst, actual_road_counts[road])
        assert pst.get("browserCapturedAt") == s.get("capturedAt"), (road, pst.get("browserCapturedAt"), s.get("capturedAt"))

    # ----- 591 -> Sinyi property-group integrity -----
    groups = p.get("propertyGroups") or []
    comparisons = p.get("comparisons") or []
    assert len(groups) == int(p.get("propertyGroupCount") or -1), (len(groups), p.get("propertyGroupCount"))
    assert len(comparisons) == len(groups), (len(comparisons), len(groups))

    group_ids = [str(g.get("groupId") or "") for g in groups]
    assert all(group_ids) and len(group_ids) == len(set(group_ids)), "duplicate/empty groupId"
    comp_group_ids = [str(c.get("groupId") or "") for c in comparisons]
    assert len(comp_group_ids) == len(set(comp_group_ids)), "duplicate comparison groupId"
    assert set(comp_group_ids) == set(group_ids), "propertyGroups/comparisons groupId mismatch"

    seen_raw_ids = {}
    raw_total = 0
    cross_platform = 0
    for g in groups:
        sources = set(g.get("sources") or [])
        assert sources and sources <= ALLOWED_EXTERNAL_SOURCES, (g.get("groupId"), sources)
        assert g.get("road") in EXPECTED_ROADS, g
        if "信義房屋" in sources:
            assert g.get("primarySource") == "信義房屋", g
        elif sources == {"591"}:
            assert g.get("primarySource") == "591", g
        if len(sources) > 1:
            cross_platform += 1
            assert g.get("crossPlatformMerged") is True, g

        ids = raw_external_ids(g)
        assert len(ids) == len(set(ids)), (g.get("groupId"), ids)
        assert int(g.get("rawListingCount") or 0) == len(ids), (g.get("groupId"), g.get("rawListingCount"), len(ids))
        raw_total += len(ids)
        for rid in ids:
            assert rid not in seen_raw_ids, (rid, seen_raw_ids.get(rid), g.get("groupId"))
            seen_raw_ids[rid] = g.get("groupId")

    assert raw_total == int(p.get("rawListingCount") or -1), (raw_total, p.get("rawListingCount"))
    assert cross_platform == int(p.get("crossPlatformMergedGroupCount") or -1), (
        cross_platform, p.get("crossPlatformMergedGroupCount")
    )

    # ----- comparison status / candidate / structured-floor integrity -----
    derived_counts = Counter()
    company_floor_pollution = []
    for c in comparisons:
        status = c.get("status")
        assert status in STATUS_LABELS, c
        assert c.get("statusLabel") == STATUS_LABELS[status], c
        derived_counts[status] += 1

        candidate = c.get("companyCandidate")
        if not candidate:
            continue
        cid = str(candidate.get("id") or "")
        assert cid in company_by_id, (c.get("groupId"), cid)
        source = company_by_id[cid]
        assert candidate.get("officialId") == source.get("officialId"), (candidate, source)
        assert candidate.get("floor") == source.get("floor"), (candidate, source)
        assert candidate.get("road", c.get("road")) == source.get("road"), (c, source)

        structured = subject_floors(source.get("floor")) if source.get("floor") else set()
        match_info = c.get("matchInfo") or {}
        reported = set(int(x) for x in (match_info.get("companyFloors") or []) if str(x).isdigit())
        if structured and reported != structured:
            company_floor_pollution.append({
                "groupId": c.get("groupId"), "candidate": cid,
                "structuredFloor": source.get("floor"),
                "expected": sorted(structured), "reported": sorted(reported),
            })
    assert not company_floor_pollution, company_floor_pollution[:20]

    expected_counts = {k: int((p.get("counts") or {}).get(k) or 0) for k in STATUS_LABELS}
    actual_counts = {k: int(derived_counts.get(k, 0)) for k in STATUS_LABELS}
    assert actual_counts == expected_counts, (actual_counts, expected_counts)
    assert sum(actual_counts.values()) == len(groups), (actual_counts, len(groups))
    assert actual_counts["unavailable"] == 0, actual_counts

    # ----- floor format / title consistency -----
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
        assert int(detail.get("rejectedTitleFloorConflicts") or 0) >= 0, detail

    print(json.dumps({
        "scheme": "A",
        "valid": True,
        "snapshotCapturedAt": s.get("capturedAt"),
        "companyGapGeneratedAt": p.get("generatedAt"),
        "browserListingCount": len(listings),
        "companyListingCount": len(company),
        "propertyGroupCount": len(groups),
        "rawListingCount": raw_total,
        "comparisonCounts": actual_counts,
        "roadCounts": dict(actual_road_counts),
        "crossPlatformMergedGroupCount": cross_platform,
        "idIntegrityGuard": integrity,
        "detailFloorEnrichment": detail,
        "legacyFallbacks": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
