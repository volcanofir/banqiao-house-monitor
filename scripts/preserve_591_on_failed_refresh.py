"""Preserve canonical 591 state when a background monitor run could not refresh 591.

This is a *publication merge* guard, not a crawler. It is called only after
the workflow has fetched the newest main branch, but before it copies its
candidate snapshot over that branch's canonical data.

On a failed 591 fetch, use 591 records and last authoritative source state
from the latest main branch. Preserve successful non-591 updates from the
candidate. Fail closed on missing or malformed inputs.
"""
import argparse
import json
from pathlib import Path


def reconcile(candidate, latest):
    candidate_591=(candidate.get("runs") or {}).get("591") or {}
    if candidate_591.get("status")=="ok":
        return candidate, "candidate_591_success_retained"
    latest_591=(latest.get("runs") or {}).get("591") or {}
    latest_rows=latest.get("listings")
    candidate_rows=candidate.get("listings")
    if not isinstance(latest_rows,list) or not isinstance(candidate_rows,list):
        raise ValueError("Both candidate and latest canonical need listing arrays")
    live_591=[row for row in latest_rows if isinstance(row,dict) and row.get("source")=="591"]
    if not live_591:
        raise ValueError("Cannot replace stale 591 source without canonical 591 records")
    if not latest_591:
        raise ValueError("Canonical 591 source run metadata is missing")
    other=[row for row in candidate_rows if not isinstance(row,dict) or row.get("source")!="591"]
    out=dict(candidate)
    out["listings"]=other+live_591
    out["listings"].sort(
        key=lambda x: (
            0 if x.get("active",True) else 1,
            -(x.get("postTime") or 0),
            x.get("firstSeenAt") or "",
        )
    )
    runs=dict(candidate.get("runs") or {})
    # Keep the 591 metadata associated with the canonical records.
    runs["591"]=latest_591
    out["runs"]=runs
    return out, "latest_canonical_591_preserved"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--incoming",required=True)
    parser.add_argument("--current",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    incoming_path=Path(args.incoming)
    current_path=Path(args.current)
    output_path=Path(args.output)
    if output_path.resolve()==current_path.resolve():
        raise SystemExit("Never write directly to canonical state")
    if not current_path.exists():
        raise SystemExit("Canonical state not found; refusing blind overwrite")
    incoming=json.loads(incoming_path.read_text(encoding="utf-8"))
    canonical=json.loads(current_path.read_text(encoding="utf-8"))
    out,decision=reconcile(incoming,canonical)
    if decision=="latest_canonical_591_preserved":
        output_path.write_text(
            json.dumps(out,ensure_ascii=False,indent=2)+"\n",
            encoding="utf-8"
        )
    if not out.get("listings"):
        raise SystemExit("Empty output; refusing publication")
    print(f"PUBLISH_GUARD decision={decision} "
          f"candidate_source_status={(incoming.get('runs',{}).get('591') or {}).get('status')} "
          f"canonical_591_count={sum(x.get('source')=='591' for x in canonical['listings'])} "
          f"output_listings={len(out['listings'])}")


if __name__=="__main__":
    main()
