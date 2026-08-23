"""Final all-pages release gate layered on the scheme A integrity validator."""

import json
from pathlib import Path

import validate_scheme_a_preview as base


SNAPSHOT = Path("docs/preview/yungching-browser-snapshot.json")


def main():
    base.main()
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert s.get("paginationGuardVersion") == "all-pages-v5", s.get("paginationGuardVersion")
    for road, st in (s.get("roadStatus") or {}).items():
        assert st.get("paginationCompleteAllPages") is True, (road, st)
        assert st.get("paginationExhausted") is True, (road, st)
        assert st.get("paginationLastPage") is not None, (road, st)
        assert int(st.get("paginationActivePage") or 0) == int(st.get("paginationLastPage") or -1), (road, st)
        if st.get("paginationExpected"):
            assert int(st.get("paginationLastPage") or 0) >= 2, (road, st)
    print(json.dumps({
        "scheme":"A",
        "allPagesValid":True,
        "paginationGuardVersion":s.get("paginationGuardVersion"),
        "lastPages":{r:(st or {}).get("paginationLastPage") for r,st in (s.get("roadStatus") or {}).items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
