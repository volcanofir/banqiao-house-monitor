"""Release gate for the Preview-only 5168 seven-road snapshot."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def matches_taipei_date(source_timestamp, source_date):
    """Stored source dates are Taiwan calendar dates, not UTC calendar dates."""
    try:
        return datetime.fromtimestamp(float(source_timestamp), TAIPEI).date().isoformat() == str(source_date)
    except (TypeError, ValueError, OverflowError, OSError):
        return False

P = Path("docs/preview/houseprice-seven-roads.json")
ROADS = ["中山路二段","三民路一段","三民路二段","翠華街","林森街","萬安街","光復街"]

p=json.loads(P.read_text(encoding="utf-8"))
assert p.get("source")=="5168", p.get("source")
assert p.get("complete") is True, p
assert p.get("roads")==ROADS, p.get("roads")
rows=p.get("listings") or []
assert int(p.get("uniqueListingCount") or 0)==len(rows), (p.get("uniqueListingCount"),len(rows))
ids=[str(x.get("listingId") or "") for x in rows]
assert all(ids), "missing listingId"
assert len(ids)==len(set(ids)), "duplicate 5168 listingId"
counts={x.get("road"):int(x.get("count") or 0) for x in p.get("roadCounts") or []}
assert set(counts)==set(ROADS), counts
assert int(p.get("placementCount") or 0)==sum(counts.values()), (p.get("placementCount"),counts)
detail=p.get("detailSummary") or {}
assert detail.get("allComplete") is True, detail
assert int(detail.get("failedCount") or 0)==0, detail
assert int(detail.get("completeCount") or 0)==len(rows), detail
policy=p.get("sourceTimePolicy") or {}
assert policy.get("monitorFirstSeenUsedAsSourceTime") is False, policy
assert policy.get("exactDateExposed") is True, policy
assert policy.get("exactDateField") == "PriceAnalyze.newKeyInDate", policy
assert policy.get("relativeTagConvertedToTaipeiDate") is True, policy
summary=p.get("sourcePublishedAtSummary") or {}
assert summary.get("noFirstSeenFallback") is True, summary
assert int(summary.get("availableCount") or 0)+int(summary.get("unavailableCount") or 0)==len(rows), summary
for x in rows:
    assert x.get("road") in ROADS, x
    assert x.get("detailComplete") is True, x
    assert str(x.get("url") or "").startswith("https://buy.houseprice.tw/house/"), x.get("url")
    assert x.get("sourcePublishedAtType") in {"housepriceGroupNewKeyInDate","housepriceRelativeTagInferred","housepriceListingDateUnavailable"}, x
    if x.get("sourcePublishedAtType")=="housepriceGroupNewKeyInDate":
        assert x.get("sourcePublishedAt"), x
        assert x.get("sourcePublishedDate"), x
        # 5168's PriceAnalyze sometimes omits newKeyInDate in a later response.
        # The crawler intentionally retains the previously verified source date
        # as sourcePublishedRaw; do not reject that valid historical evidence.
        current_raw = str(x.get("groupNewKeyInDate") or "").strip()
        retained_raw = str(x.get("sourcePublishedRaw") or "").strip()
        assert current_raw or retained_raw, x
        expected_date = str(x["sourcePublishedDate"])
        assert (current_raw or retained_raw)[:10] == expected_date, x
        if current_raw and retained_raw:
            assert current_raw[:10] == retained_raw[:10], x
        assert matches_taipei_date(x["sourcePublishedAt"], expected_date), x
    elif x.get("sourcePublishedAtType")=="housepriceRelativeTagInferred":
        assert x.get("sourcePublishedAt"), x
        assert x.get("sourcePublishedDate"), x
        # The original relative tag may also disappear; its recorded evidence
        # is retained separately by the crawler.
        assert x.get("sourcePublishText") or x.get("sourcePublishedRaw"), x
        assert matches_taipei_date(x["sourcePublishedAt"], x["sourcePublishedDate"]), x
    else:
        assert x.get("sourcePublishedAt") is None, x

print(json.dumps({
    "source":"5168",
    "valid":True,
    "uniqueListingCount":len(rows),
    "placementCount":p.get("placementCount"),
    "roadCounts":counts,
    "detailComplete":detail.get("completeCount"),
},ensure_ascii=False))
