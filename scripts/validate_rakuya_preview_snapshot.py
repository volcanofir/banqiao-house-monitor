import json
from pathlib import Path

P=Path("docs/preview/rakuya-seven-roads.json")
ROADS=["中山路二段","三民路一段","三民路二段","翠華街","林森街","萬安街","光復街"]

p=json.loads(P.read_text(encoding="utf-8"))
assert p.get("complete") is True, p
assert p.get("roads") == ROADS, p.get("roads")
counts=p.get("roadCounts") or []
assert [x.get("road") for x in counts] == ROADS, counts
assert sum(int(x.get("count") or 0) for x in counts) == int(p.get("placementCount") or -1)
assert int(p.get("uniqueListingCount") or -1) == len(p.get("listings") or [])
assert len({x.get("listingId") for x in p.get("listings") or []}) == len(p.get("listings") or [])
rows=p.get("listings") or []
allowed_types={"rakuyaListingDate","rakuyaListingDateUnavailable"}
assert all(x.get("sourcePublishedAtType") in allowed_types for x in rows), {
    x.get("listingId"): x.get("sourcePublishedAtType")
    for x in rows if x.get("sourcePublishedAtType") not in allowed_types
}
assert not any(x.get("sourcePublishedAtType") == "monitorFirstSeen" for x in rows)
for x in rows:
    if x.get("sourcePublishedAtType") == "rakuyaListingDate":
        assert x.get("sourcePublishedAt"), x
        assert x.get("sourcePublishedDate"), x
summary=p.get("sourcePublishedAtSummary") or {}
assert summary.get("noFirstSeenFallback") is True, summary
assert int(summary.get("availableCount") or 0) + int(summary.get("unavailableCount") or 0) == len(rows), summary
print(json.dumps({
    "complete": True,
    "placementCount": p.get("placementCount"),
    "uniqueListingCount": p.get("uniqueListingCount"),
    "roadCounts": counts,
    "sourcePublishedAtSummary": summary,
}, ensure_ascii=False))
