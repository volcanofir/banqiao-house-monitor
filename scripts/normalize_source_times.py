import json
from pathlib import Path

DATA_PATH = Path("docs/data/listings.json")


def main():
    if not DATA_PATH.exists():
        print("No listings data found.")
        return

    state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    listings = state.get("listings") or []

    count_591 = 0
    count_sinyi = 0
    missing_sinyi = 0

    for item in listings:
        source = item.get("source")
        if source == "591":
            item["sourcePublishedAt"] = item.get("postTime")
            item["sourcePublishedAtType"] = "posttime" if item.get("postTime") else None
            if item.get("postTime"):
                count_591 += 1

        elif source == "信義房屋":
            # firstDisplay is the actual Sinyi API field. The type remains
            # publishTime only for compatibility with the existing frontend.
            if (
                item.get("sourcePublishedAt")
                and item.get("sourcePublishedAtField") == "firstDisplay"
            ):
                item["postTime"] = item.get("sourcePublishedAt")
                item["sourcePublishedAtType"] = "publishTime"
                count_sinyi += 1
            else:
                item["sourcePublishedAt"] = None
                item["sourcePublishedAtType"] = None
                item["sourcePublishedAtField"] = None
                item["postTime"] = None
                missing_sinyi += 1

    previous = state.get("timeNormalization") or {}
    state["timeNormalization"] = {
        **previous,
        "591RealPublishTimes": count_591,
        "sinyiRealPublishTimes": count_sinyi,
        "sinyiMissingPublishTimes": missing_sinyi,
        "sinyiSourceField": "firstDisplay",
    }

    DATA_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Source times normalized: 591={count_591}, "
        f"Sinyi firstDisplay={count_sinyi}, Sinyi missing={missing_sinyi}"
    )


if __name__ == "__main__":
    main()
