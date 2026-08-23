"""Scheme A Preview v9: re-expand raw 591 members and regroup with detail floors.

The v9 external snapshot is created by enrich_591_preview_detail_floor.py. Production
monitor data remains untouched. v8's proven Sinyi structured-floor matching and
company near-tie guard remain in force; the only new grouping evidence is fresh 591
public detail floor data on medium-risk members.
"""

import json
from pathlib import Path

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v7 as v7
import compare_yungching_preview_v8 as v8

V9_EXTERNAL=Path("docs/preview/scheme-a-external-v9.json")
FLOOR_STATS=Path("docs/preview/591-detail-floor-enrichment.json")

ORIGINAL_SAFE=v8.safe_listing_floor_tokens_with_structured


def safe_listing_floor_tokens_v9(x):
    floors=set(ORIGINAL_SAFE(x))
    if not x:
        return floors
    for key in ("structuredFloor","floor"):
        raw=x.get(key)
        if raw not in (None,""):
            floors |= v7.safe_floor_numbers(raw)
    return floors


def main():
    if not V9_EXTERNAL.exists() or not FLOOR_STATS.exists():
        raise RuntimeError("missing v9 591 detail-floor enrichment")
    fs=json.loads(FLOOR_STATS.read_text(encoding="utf-8"))
    if fs.get("complete") is not True:
        raise RuntimeError(f"591 detail floor enrichment incomplete: {fs.get('detailErrorCount')} errors")

    # v8 points the Preview comparator at ENRICHED. Redirect it only for this replay.
    v8.ENRICHED=V9_EXTERNAL
    v8.ORIGINAL_SAFE_LISTING_FLOORS=safe_listing_floor_tokens_v9
    # Reset mutable statistics because diagnostics can run multiple comparator passes.
    for d in (v4.REGROUP_STATS, v4.GROUP_INTEGRITY_STATS):
        for k in list(d): d[k]=0

    v8.main()
    path=v4.prev.OUT_PATH
    payload=json.loads(path.read_text(encoding="utf-8"))
    payload["mode"]="preview_only_raw591_detail_floor_regroup_then_sinyi_then_company_v9"
    payload["structured591DetailFloorMatching"]=True
    payload["listing591DetailFloorEnrichment"]={k:fs.get(k) for k in (
        "generatedAt","source","targetMediumGroupCount","targetIdCount","detailSuccessCount","detailErrorCount",
        "withStructuredFloorCount","raw591ReexpandedCount","detailAppliedToV9Count","withFloorAppliedToV9Count","complete"
    )}
    payload["note"]=(
        "PREVIEW v9：先把既有591合併成員重新展開，對medium-risk成員使用591官方公開detail JSON結構化樓層，"
        "再用既有cluster-level樓層衝突保護重分組；沒有明確樓層衝突時維持原有坪數/價格/文字規則。"
        "之後沿用v8信義結構化樓層、信義優先、永慶官方DOM與near-tie guard。正式監控資料不改寫。"
    )
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "mode":payload["mode"],"propertyGroupCount":payload.get("propertyGroupCount"),"counts":payload.get("counts"),
        "preview591Regroup":payload.get("preview591Regroup"),"detailFloor":payload.get("listing591DetailFloorEnrichment")
    },ensure_ascii=False))


if __name__=="__main__": main()
