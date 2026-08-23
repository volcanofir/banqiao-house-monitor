"""Run the scheme A ambiguity audit with structured Sinyi floors as first-class truth."""

import audit_scheme_a_ambiguity as base

ORIGINAL_LISTING_FLOORS = base.listing_floors


def structured_listing_floors(x, company=False):
    if not x:
        return set()
    raw = x.get("floor")
    if raw not in (None, ""):
        parsed = base.floors(raw)
        if parsed:
            return parsed
    return ORIGINAL_LISTING_FLOORS(x, company=company)


def main():
    base.listing_floors = structured_listing_floors
    base.main()


if __name__ == "__main__":
    main()
