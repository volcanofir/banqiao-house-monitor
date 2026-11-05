"""Trusted, optional fields from 591 public wareList. No title/address guessing.

Only authoritative structured fields are used as definitive floor evidence.
Fields absent from the public listing are left unknown; a whole building is
not an apartment floor. Source raw value stays available for auditing.
"""
import re

FIELDS = (
    "structuredFloor", "structuredFloorRaw", "floorSourceMode",
    "structuredLayout", "structuredCommunity", "sourceKind",
    "sourceHouseAge", "sourceParkingFlag",
)

def normalize_floor(value):
    text = str(value or "").strip().upper().replace("Ｆ","F").replace("～","~").replace("－","~").replace("-","~")
    text = re.sub(r"\s+", "", text)
    # '整棟/3F', basement levels, '高樓層' are intentionally unknown.
    match = re.fullmatch(r"(\d{1,2})F(?:~(\d{1,2})F)?/(\d{1,2})F", text)
    if not match: return None
    lo = int(match.group(1))
    hi = int(match.group(2) or match.group(1))
    total = int(match.group(3))
    if not 1 <= lo <= hi <= total <= 99: return None
    if hi - lo > 10: return None
    return f"{lo}/{total}樓" if lo == hi else f"{lo}~{hi}/{total}樓"

def source_floor_tokens(row):
    if not isinstance(row,dict): return set()
    value = row.get("structuredFloor")
    if row.get("floorSourceMode") != "591_warelist_structured" or not value:
        return set()
    m = re.fullmatch(r"(\d{1,2})(?:~(\d{1,2}))?/(\d{1,2})樓", str(value))
    if not m: return set()
    lo,hi,total = int(m.group(1)),int(m.group(2) or m.group(1)),int(m.group(3))
    return set(range(lo,hi+1)) if 1 <= lo <= hi <= total <= 99 else set()

def source_fields(item):
    if not isinstance(item,dict): return {}
    result = {}
    raw_floor = item.get("floor")
    if isinstance(raw_floor,str) and 0 < len(raw_floor) <= 32:
        result["structuredFloorRaw"] = raw_floor.strip()
    normalized = normalize_floor(raw_floor)
    if normalized:
        result["structuredFloor"] = normalized
        result["floorSourceMode"] = "591_warelist_structured"
    room = item.get("room")
    if isinstance(room,str) and room.strip() and len(room) <= 60:
        result["structuredLayout"] = room.strip()
    community = item.get("community_name")
    if isinstance(community,str) and community.strip() and len(community) <= 100:
        result["structuredCommunity"] = community.strip()
    kind = item.get("kind_name")
    if isinstance(kind,str) and kind.strip() and len(kind) <= 40:
        result["sourceKind"] = kind.strip()
    age = item.get("houseage")
    if isinstance(age,(int,float)) and not isinstance(age,bool) and 0 <= age <= 120:
        result["sourceHouseAge"] = age
    parking = item.get("has_carport")
    if parking in (0,1,"0","1") and not isinstance(parking,bool):
        result["sourceParkingFlag"] = bool(int(parking))
    return result

def carried_fields(row):
    return {key:row[key] for key in FIELDS if row.get(key) is not None}
