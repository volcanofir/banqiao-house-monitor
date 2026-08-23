"""Scheme A Preview v7: safe floor parsing across 591/Sinyi/company matching.

Prevents concatenated DOM strings such as `主32.333/3樓` from becoming floor 33.
Company rows still prefer their structured official `floor`; this wrapper also makes the
shared 591/Sinyi floor parser physically validate subject/total expressions.
"""

import json
import re

import compare_yungching_preview_v4 as v4
import compare_yungching_preview_v5 as v5
import compare_yungching_preview_v6 as v6


def safe_floor_numbers(text, company_text=False):
    text = str(text or "").replace("～", "~")
    floors = set()
    spans = []

    # subject/total. Validate subject <= total. In glued cases such as 33/3,
    # only the final digit can be the subject floor (3/3).
    for m in re.finditer(r"(\d{1,2})(?:\s*[~-]\s*(\d{1,2}))?\s*/\s*(\d{1,2})\s*樓", text):
        raw_lo = m.group(1)
        raw_hi = m.group(2)
        total = int(m.group(3))
        if not (1 <= total <= 99):
            continue

        if raw_hi is not None:
            lo, hi = int(raw_lo), int(raw_hi)
            if 1 <= lo <= hi <= total and hi - lo <= 10:
                floors.update(range(lo, hi + 1))
        else:
            n = int(raw_lo)
            if 1 <= n <= total:
                floors.add(n)
            elif len(raw_lo) == 2:
                suffix = int(raw_lo[-1])
                if 1 <= suffix <= total:
                    floors.add(suffix)
        spans.append(m.span())

    # Remove slash expressions before matching ordinary `X樓`; otherwise the total
    # floor can be interpreted as another subject floor.
    if spans:
        chars = list(text)
        for start, end in spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    # Explicit subject range without total, e.g. 1~2樓.
    range_spans = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[~-]\s*(\d{1,2})\s*樓", text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 99 and hi - lo <= 10:
            floors.update(range(lo, hi + 1))
        range_spans.append(m.span())
    if range_spans:
        chars = list(text)
        for start, end in range_spans:
            for i in range(start, end):
                chars[i] = " "
        text = "".join(chars)

    for raw in re.findall(r"(?<!\d)(\d{1,2})\s*樓", text):
        n = int(raw)
        if 1 <= n <= 99:
            floors.add(n)

    digits = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    for raw in re.findall(r"([一二三四五六七八九十]{1,3})樓", text):
        if raw == "十":
            n = 10
        elif "十" in raw:
            left, right = raw.split("十", 1)
            n = digits.get(left, 1) * 10 + digits.get(right, 0)
        else:
            n = digits.get(raw)
        if n:
            floors.add(n)
    return floors


def safe_listing_floor_tokens(x):
    floors = set()
    if not x:
        return floors
    floors |= safe_floor_numbers(x.get("title"))
    floors |= safe_floor_numbers(x.get("address"))
    for m in (x.get("mergedListings") or []):
        floors |= safe_floor_numbers(m.get("title"))
        floors |= safe_floor_numbers(m.get("address"))
    return floors


def main():
    # Patch the shared parsers before v6 invokes v5/v4 grouping.
    v5.floors_from_text = safe_floor_numbers
    v4.title_floor_tokens = safe_floor_numbers
    v4.listing_floor_tokens = safe_listing_floor_tokens
    v6.main()

    path = v5.v4.prev.OUT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mode"] = "preview_only_591_then_sinyi_then_company_floor_aware_official_rendered_v7"
    payload["safeFloorParser"] = True
    payload["safeFloorParserRule"] = "subject floor must be physically valid against total floor; glued area digits are trimmed instead of becoming impossible floors"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"safeFloorParser": True, "mode": payload["mode"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
