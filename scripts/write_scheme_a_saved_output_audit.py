"""Write a canonical saved-output audit using the strict v2 scheme A validator.

This runs inside the canonical publisher before commit so the verification manifest
and the audit are published atomically from the exact same files.
"""

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

import validate_scheme_a_preview_v2 as validator


OUT = Path("docs/preview/scheme-a-saved-output-audit.json")


def compact(path: str) -> dict:
    x = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "generatedAt": x.get("generatedAt"),
        "capturedAt": x.get("capturedAt"),
        "verifiedAt": x.get("verifiedAt"),
        "companySnapshotCapturedAt": x.get("companySnapshotCapturedAt"),
        "listingCount": x.get("listingCount"),
        "companyListingCount": x.get("companyListingCount"),
        "propertyGroupCount": x.get("propertyGroupCount"),
        "counts": x.get("counts"),
        "idIntegrityGuard": x.get("idIntegrityGuard"),
        "canonicalPublisher": x.get("canonicalPublisher"),
        "valid": x.get("valid"),
        "integrityVersion": x.get("integrityVersion"),
        "safeFloorParser": x.get("safeFloorParser"),
    }


def main():
    out = {
        "auditedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scheme": "A",
        "target": "exact canonical Preview files before atomic publish",
        "validator": "validate_scheme_a_preview_v2",
        "passed": False,
        "error": None,
    }
    failure = None
    try:
        validator.main()
        out["passed"] = True
    except Exception as exc:
        failure = exc
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceTail"] = traceback.format_exc().splitlines()[-12:]

    for name, path in {
        "companyGap": "docs/preview/company-gap.json",
        "browserSnapshot": "docs/preview/yungching-browser-snapshot.json",
        "verification": "docs/preview/scheme-a-verification.json",
    }.items():
        try:
            out[name] = compact(path)
        except Exception as exc:
            out[name] = {"readError": f"{type(exc).__name__}: {exc}"}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
