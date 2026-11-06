"""Run the scheme A ambiguity audit with preserved, verified source floors.

An advertising title or address cannot override authoritative 591/Sinyi/5168
floors. This audit reports suspected weak merges; it does not split homes.
"""

import audit_scheme_a_ambiguity as base
import compare_yungching_preview_v4 as matching

ORIGINAL_LISTING_FLOORS = base.listing_floors


def structured_listing_floors(x, company=False):
    if not x:
        return set()
    if company:
        raw = x.get("floor")
        if raw not in (None, ""):
            parsed = base.floors(raw)
            if parsed:
                return parsed
        return ORIGINAL_LISTING_FLOORS(x, company=True)

    verified = matching._trusted_floor_tokens(x)
    for m in x.get("mergedListings") or []:
        item = dict(m)
        item.setdefault("source", x.get("source"))
        verified |= matching._trusted_floor_tokens(item)
    if verified:
        return verified
    # Unknown source floors remain unknown; do not infer from price or area.
    return ORIGINAL_LISTING_FLOORS(x, company=False)


def main():
    base.listing_floors = structured_listing_floors
    base.main()


if __name__ == "__main__":
    main()
